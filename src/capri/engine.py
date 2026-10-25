"""Async adaptation of the official synchronous SDK; OMP owns the transcript."""
import asyncio
import json
from pathlib import Path
from enum import Enum, auto
from omp_rpc import RpcClient
from .config import OMP_CONFIG, write_json
from .prompt import CAPRI_CONVERSATION_PROMPT


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
        self._lock = asyncio.Lock()
        self._queue = None
        self._loop = None
        self._failed = False
        self._active = False
        self._aborting = False
        self._steer_lock = asyncio.Lock()

    async def start(self):
        agent = self.data / 'agent'
        work = self.data / 'work'
        sessions = agent / 'sessions'
        for path in (agent, work, sessions):
            path.mkdir(parents=True, exist_ok=True)
        write_json(agent / 'config.yml', OMP_CONFIG)
        args = ['--no-extensions', '--no-lsp', '--no-pty']
        pointer = self.data / 'session.json'
        if pointer.exists():
            session = Path(json.loads(pointer.read_text(encoding='utf-8'))['path']).resolve()
            if not session.is_relative_to(sessions):
                raise EngineError('OMP session path is outside Capri storage')
            if session.exists():
                args += ['--resume', str(session)]
        self.client = self.sdk_factory(executable=str(self.executable), cwd=work,
            env={'PI_CODING_AGENT_DIR': str(agent), 'OMP_PROFILE': '', 'PI_PROFILE': '',
                 'PI_CONFIG_DIR': '.capri-omp'}, session_dir=sessions,
            provider='openai-codex', model='gpt-6-luna', thinking='low',
            tools=('web_search',), no_skills=True, no_rules=True, no_title=True,
            no_ui=True, extra_args=args, append_system_prompt=CAPRI_CONVERSATION_PROMPT)
        self.client.on_message_update(self._on_update)
        try:
            await asyncio.to_thread(self.client.start)
            models = await asyncio.to_thread(self.client.get_available_models)
            if not any(m.provider == 'openai-codex' and m.id == 'gpt-6-luna' for m in models):
                raise EngineError('OMP gpt-6-luna is unavailable')
            await asyncio.to_thread(self.client.set_model, 'openai-codex', 'gpt-6-luna')
            state = await asyncio.to_thread(self.client.get_state)
            if (state.model.provider, state.model.id) != ('openai-codex', 'gpt-6-luna'):
                raise EngineError('OMP selected an unexpected model')
            if {t.name for t in state.dump_tools} != {'web_search'}:
                raise EngineError('OMP effective tools differ from the verified web-only set')
            if not state.session_file or not Path(state.session_file).resolve().is_relative_to(sessions):
                raise EngineError('OMP selected storage outside Capri')
            write_json(pointer, {'path': state.session_file})
        except Exception:
            await self.close()
            raise EngineError('OMP startup/model/isolation check failed') from None

    def _on_update(self, event):
        update = event.assistant_message_event
        if (event.message.get('role') == 'assistant' and update.get('type') == 'text_delta'
                and isinstance(update.get('delta'), str) and self._queue is not None):
            self._loop.call_soon_threadsafe(self._queue.put_nowait, update['delta'])

    async def stream(self, text: str):
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
                    await asyncio.to_thread(self.client.stop)
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
                    yield item
                await task
            finally:
                self._queue = None
                if not task.done():
                    try:
                        self._aborting = True
                        await asyncio.to_thread(self.client.abort)
                    finally:
                        await task
                        self._aborting = False

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

    async def close(self):
        if self.client is not None:
            await asyncio.to_thread(self.client.stop)
