"""Async adaptation of the official synchronous SDK; OMP owns the transcript."""
import asyncio
from collections.abc import AsyncIterator
import json
import os
import subprocess
from pathlib import Path
from enum import Enum, auto
from omp_rpc import ExtensionUiRequest, RpcAgentEvent, RpcClient
from .config import APPROVAL_MODES, omp_environment, omp_isolation_args, write_json
from .prompt import CAPRI_CONVERSATION_PROMPT
from .teardown import complete_cleanup, stop_child


class SteerResult(Enum):
    ACCEPTED = auto()
    NOT_ACTIVE = auto()
    UNSUPPORTED = auto()


class EngineError(RuntimeError):
    pass


class Engine:
    def __init__(self, executable: Path, data: Path, *, sdk_factory=RpcClient):
        self.executable = executable.resolve()
        self.data = data.resolve()
        self.sdk_factory = sdk_factory
        self.client = None
        self.safe = True
        self._lock = asyncio.Lock()
        self._queue = None
        self._loop = None
        self._failed = False
        self._active = False
        self._aborting = False
        self._steer_lock = asyncio.Lock()
        self._pending_ui = {}

    async def start(self):
        if not self.safe:
            raise EngineError('OMP teardown unconfirmed; restart Capri')
        agent = self.data / 'agent'
        work = self.data / 'work'
        sessions = agent / 'sessions'
        for path in (agent, work, sessions):
            path.mkdir(parents=True, exist_ok=True)
        args = ['--no-extensions', '--no-lsp', '--no-pty', *omp_isolation_args(self.data)]
        pointer = self.data / 'session.json'
        if pointer.exists():
            session = Path(json.loads(pointer.read_text(encoding='utf-8'))['path']).resolve()
            if not session.is_relative_to(sessions):
                raise EngineError('OMP session path is outside Capri storage')
            if session.exists():
                args += ['--resume', str(session)]
        self.client = self.sdk_factory(executable=str(self.executable), cwd=work,
            env=omp_environment(self.data), session_dir=sessions,
            provider='openai-codex', model='gpt-6-luna', thinking='low',
            no_skills=True, no_rules=True, no_title=True,
            no_ui=False, extra_args=args, append_system_prompt=CAPRI_CONVERSATION_PROMPT)
        self.client.on_message_update(self._on_update)
        self.client.on_tool_execution_start(self._emit)
        self.client.on_tool_execution_update(self._emit)
        self.client.on_tool_stream_update(self._emit)
        self.client.on_tool_execution_end(self._emit)
        self.client.on_ui_request(self._on_ui)
        try:
            await asyncio.to_thread(self.client.start)
            models = await asyncio.to_thread(self.client.get_available_models)
            if not any(m.provider == 'openai-codex' and m.id == 'gpt-6-luna' for m in models):
                raise EngineError('OMP gpt-6-luna is unavailable')
            await asyncio.to_thread(self.client.set_model, 'openai-codex', 'gpt-6-luna')
            state = await asyncio.to_thread(self.client.get_state)
            if (state.model.provider, state.model.id) != ('openai-codex', 'gpt-6-luna'):
                raise EngineError('OMP selected an unexpected model')
            if not state.session_file or not Path(state.session_file).resolve().is_relative_to(sessions):
                raise EngineError('OMP selected storage outside Capri')
            write_json(pointer, {'path': state.session_file})
        except Exception:
            await self.close()
            raise EngineError('OMP startup/model/isolation check failed') from None

    def _on_update(self, event):
        update = event.assistant_message_event
        if event.message.get('role') != 'assistant':
            return
        if update.get('type') == 'text_delta' and isinstance(update.get('delta'), str):
            self._emit(update['delta'])
        elif update.get('type') in ('thinking_start', 'thinking_delta', 'thinking_end'):
            self._emit(event)

    def _emit(self, item):
        # Snapshot the turn's queue: a delayed SDK callback must never land in
        # a later turn's queue. No Telegram work runs on the SDK reader thread.
        queue, loop = self._queue, self._loop
        if queue is not None:
            loop.call_soon_threadsafe(queue.put_nowait, item)

    def _on_ui(self, request):
        if request.method == 'cancel':
            self._emit(request)
        elif (self._queue is not None and request.method == 'select'
                and (request.title or '').startswith('Allow tool: ')
                and 'Deny' in (request.options or ())
                and any(value in (request.options or ()) for value in ('Approve', 'Approve Once'))):
            self._emit(request)
        elif not request.is_passive():
            # Only native approval selects are bridged. Other interactive
            # dialogs, including startup requests without a turn, fail closed.
            self.client.cancel_ui_request(request.id)

    async def answer_approval(self, request_id: str, value: str) -> bool:
        request = self._pending_ui.get(request_id)
        if request is None or value not in (request.options or ()) or not self._active:
            return False
        del self._pending_ui[request_id]
        client = self.client
        async def reply():
            try:
                await asyncio.to_thread(client.send_ui_value, request_id, value)
            except Exception:
                await asyncio.to_thread(client.abort)
                raise EngineError('Не вдалося підтвердити рішення OMP.') from None
        await complete_cleanup(reply())
        return True

    async def stream(self, text: str) -> AsyncIterator[str | RpcAgentEvent | ExtensionUiRequest]:
        async with self._lock:
            if self.client is None or self._failed:
                raise EngineError('OMP is not running; restart Capri')
            self._loop = asyncio.get_running_loop()
            queue = self._queue = asyncio.Queue()
            async def submit():
                try:
                    self._active = True
                    turn = await asyncio.to_thread(self.client.prompt_and_wait,
                        'Capri input JSON:\n' + json.dumps({'text': text}, ensure_ascii=False), timeout=180)
                    if (turn.result is not None and turn.result.status == 'aborted'
                            and self._aborting):
                        return
                    if turn.result is None or turn.result.status != 'completed':
                        raise EngineError('OMP did not complete the response')
                except Exception:
                    self._failed = True
                    self.safe = False
                    self.safe = await asyncio.to_thread(stop_child, self.client)
                    queue.put_nowait(EngineError('OMP response failed or process exited; restart Capri'))
                finally:
                    self._active = False
                    queue.put_nowait(None)
            task = asyncio.create_task(submit())
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    if isinstance(item, Exception):
                        raise item
                    if isinstance(item, ExtensionUiRequest):
                        if item.method == 'cancel':
                            self._pending_ui.pop(item.target_id, None)
                        else:
                            self._pending_ui[item.id] = item
                    yield item
                await task
            finally:
                self._queue = None
                self._pending_ui.clear()
                if not task.done():
                    async def cleanup():
                        try:
                            self._aborting = True
                            await asyncio.to_thread(self.client.abort)
                        finally:
                            try:
                                await task
                            finally:
                                self._aborting = False
                    await complete_cleanup(cleanup())

    async def steer(self, text: str) -> SteerResult:
        """Use the SDK's concurrent command path, never the prompt lifecycle lock.

        NOT_ACTIVE and UNSUPPORTED mean not submitted: keep the input FIFO.
        Ambiguous failures are raised; blindly resubmitting could duplicate input.
        """
        async with self._steer_lock:
            method = getattr(self.client, 'steer', None)
            if not self._active or self._failed:
                return SteerResult.NOT_ACTIVE
            if not callable(method):
                return SteerResult.UNSUPPORTED
            try:
                await asyncio.to_thread(method,
                    'Capri input JSON:\n' + json.dumps({'text': text}, ensure_ascii=False))
            except Exception as exc:
                from omp_rpc import RpcError
                if isinstance(exc, RpcError) and ('unknown command' in str(exc).lower()
                        or 'not supported' in str(exc).lower()):
                    return SteerResult.UNSUPPORTED
                raise EngineError('OMP steering acknowledgement failed; input delivery is uncertain') from None
            return SteerResult.ACCEPTED

    async def permission(self, mode: str | None = None) -> str:
        """Use OMP's config CLI; its schema and persistent store own the policy."""
        if mode is not None and mode not in APPROVAL_MODES:
            raise ValueError('Unknown OMP approval mode')
        if self._lock.locked():
            raise EngineError('Спершу дочекайся завершення відповіді або надішли /stop.')

        def configure():
            work = self.data / 'work'
            work.mkdir(parents=True, exist_ok=True)
            (self.data / 'agent').mkdir(parents=True, exist_ok=True)
            env = {**os.environ, **omp_environment(self.data), 'NO_COLOR': '1'}

            def command(action, value=None):
                args = [str(self.executable), 'config', action, 'tools.approvalMode']
                if value is not None:
                    args.append(value)
                result = subprocess.run([*args, '--json'], cwd=work, env=env,
                    capture_output=True, text=True, encoding='utf-8', check=True,
                    timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                response = json.loads(result.stdout)
                if (not isinstance(response, dict) or response.get('key') != 'tools.approvalMode'
                        or response.get('value') not in APPROVAL_MODES or response.get('overriddenBy')):
                    raise ValueError('OMP did not confirm the approval setting')
                return response['value']

            try:
                if mode is not None:
                    if command('set', mode) != mode:
                        raise ValueError('OMP saved an unexpected mode')
                current = command('get')
                if mode is not None and current != mode:
                    raise ValueError('OMP effective mode differs from the saved mode')
                return current
            except (OSError, subprocess.SubprocessError, ValueError):
                raise EngineError('Не вдалося підтвердити режим OMP. Перевір його через /permission.') from None

        # subprocess.run reaps timed-out config processes. Cancellation joins
        # this short worker instead of abandoning a possibly completed save.
        return await complete_cleanup(asyncio.to_thread(configure))

    async def close(self):
        if self.client is not None:
            self.safe = False
            async def cleanup():
                self.safe = await asyncio.to_thread(stop_child, self.client)
            await complete_cleanup(cleanup())
