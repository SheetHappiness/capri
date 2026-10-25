"""A short-lived official RPC child continuing one validated guest thread."""
import asyncio
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
import threading
from omp_rpc import RpcClient, assistant_text
from .engine import EngineError
from .prompt import CAPRI_GUEST_PROMPT
from .teardown import complete_cleanup, stop_child

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GuestEvent:
    kind: str
    text: str = ''


class GuestEngine:
    def __init__(self, executable: Path, data: Path, *, sdk_factory=RpcClient):
        self.executable = executable.resolve()
        self.data = data.resolve()
        self.sdk_factory = sdk_factory
        self.safe = True

    async def stream(self, thread_dir: Path, *, text: str, reference_text: str | None):
        directory = thread_dir.resolve()
        root = (self.data/'guest/sessions').resolve()
        relative = directory.relative_to(root) if directory.is_relative_to(root) else None
        if (relative is None or len(relative.parts) != 2
                or re.fullmatch(r'-?\d+', relative.parts[0]) is None
                or re.fullmatch(r'[a-f0-9]{12}', relative.parts[1]) is None or not self.safe):
            raise EngineError('Invalid guest session directory')
        directory.mkdir(parents=True, exist_ok=True)
        work = self.data/'guest/work'
        work.mkdir(parents=True, exist_ok=True)
        client = self.sdk_factory(executable=str(self.executable), cwd=work,
            env={'PI_CODING_AGENT_DIR': str(self.data/'agent'), 'OMP_PROFILE': '',
                 'PI_PROFILE': '', 'PI_CONFIG_DIR': '.capri-omp'},
            session_dir=directory, provider='openai-codex', model='gpt-6-luna',
            thinking='low', tools=('web_search',), no_skills=True, no_rules=True,
            no_title=True, no_ui=True, extra_args=['--no-extensions','--no-lsp','--no-pty'],
            append_system_prompt=CAPRI_GUEST_PROMPT)
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()
        cancelled = threading.Event()
        stop_lock = threading.Lock()

        def stop():
            with stop_lock:
                return stop_child(client)

        def update(event):
            item = event.assistant_message_event
            if (event.message.get('role') == 'assistant' and item.get('type') == 'text_delta'
                    and isinstance(item.get('delta'), str)):
                emit('text', item['delta'])

        def emit(kind, text=''):
            loop.call_soon_threadsafe(queue.put_nowait, GuestEvent(kind, text))

        def start(event):
            if event.message.get('role') == 'assistant': emit('start')

        def end(event):
            if event.message.get('role') == 'assistant':
                emit('message', assistant_text(event.message) or '')

        client.on_message_start(start)
        client.on_message_update(update)
        client.on_message_end(end)
        client.on_tool_execution_start(lambda event: emit('tool_start'))
        client.on_tool_execution_end(lambda event: emit('tool_end'))
        payload = {'text': text}
        if reference_text is not None: payload['reference'] = {'text': reference_text}

        def check_cancel():
            if cancelled.is_set(): raise EngineError('Guest cancelled')

        def run():
            try:
                client.start()
                check_cancel()
                if not any((m.provider,m.id) == ('openai-codex','gpt-6-luna')
                           for m in client.get_available_models()):
                    raise EngineError('Guest Luna unavailable')
                opened = client.open_session(directory)
                check_cancel()
                client.set_model('openai-codex','gpt-6-luna')
                state = client.get_state()
                if ((state.model.provider,state.model.id) != ('openai-codex','gpt-6-luna')
                        or {t.name for t in state.dump_tools} != {'web_search'}
                        or not state.session_file
                        or not Path(state.session_file).resolve().is_relative_to(directory)):
                    raise EngineError('Guest model/tools/session isolation failed')
                log.info('guest_luna: thread=%s chat=%s resumed=%s tools=web_search',
                         directory.name,directory.parent.name,opened.resumed)
                check_cancel()
                turn = client.prompt_and_wait('Capri guest input JSON:\n' +
                    json.dumps(payload,ensure_ascii=False), timeout=180)
                if turn.result is None or turn.result.status != 'completed':
                    raise EngineError('Guest response incomplete')
                # turn_end also occurs on tool-bearing steps. The prompt's own
                # completed result seals only its final assistant message.
                final = turn.assistant_message
                emit('final', (turn.assistant_text or '') if final is not None
                     and final.get('stopReason') in ('stop','length') else '')
            except Exception:
                loop.call_soon_threadsafe(queue.put_nowait, EngineError('Guest OMP response failed'))
            finally:
                try:
                    self.safe = stop()
                except Exception:
                    self.safe = False
                if not self.safe:
                    log.warning('guest_luna: child_teardown_unconfirmed')
                    loop.call_soon_threadsafe(queue.put_nowait, EngineError('Guest child teardown unconfirmed'))
                loop.call_soon_threadsafe(queue.put_nowait, None)

        self.safe = False
        task = asyncio.create_task(asyncio.to_thread(run))
        try:
            while True:
                item = await queue.get()
                if item is None: break
                if isinstance(item, Exception): raise item
                yield item
        finally:
            cancelled.set()
            async def cleanup():
                if not task.done():
                    # Interrupt the wait, then join the real worker. Protect both
                    # operations against repeated cancellation before unlocking.
                    await asyncio.to_thread(stop)
                await task
            await complete_cleanup(cleanup())
