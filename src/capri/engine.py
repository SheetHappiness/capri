"""Async adaptation of the official synchronous SDK; OMP owns the transcript."""
import asyncio
import json
from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from pathlib import Path
from enum import Enum, auto
from omp_rpc import RpcClient
from .config import OMP_CONFIG, write_json
from .prompt import CAPRI_CONVERSATION_PROMPT
from .teardown import complete_cleanup, stop_child


OWNER_TOOLS = ('web_search', 'read', 'write', 'edit', 'glob', 'find', 'bash')


@dataclass(frozen=True)
class ShellApproval:
    request_id: str
    command: str
    cwd: Path
    prompt: str
    deadline: float


class SteerResult(Enum):
    ACCEPTED = auto()
    NOT_ACTIVE = auto()
    UNSUPPORTED = auto()


class EngineError(RuntimeError):
    pass


class Engine:
    def __init__(self, executable: Path, data: Path, *, sdk_factory=RpcClient,
                 approve: Callable[[ShellApproval], Awaitable[bool]] | None = None,
                 approval_notice: Callable[[str], Awaitable[None]] | None = None):
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
        self._stop_lock = asyncio.Lock()
        self.approve = approve
        self.approval_notice = approval_notice
        self._run = None
        self._run_deadline = 0.0
        self._calls = {}
        self._ui_tasks = {}
        self._ui_seen = set()
        self._ui_cancelled = set()

    async def start(self):
        if not self.safe:
            raise EngineError('OMP teardown unconfirmed; restart Capri')
        self._loop = asyncio.get_running_loop()
        await self._clear_approvals()
        self._ui_seen.clear()
        self._ui_cancelled.clear()
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
            tools=OWNER_TOOLS, no_skills=True, no_rules=True, no_title=True,
            no_ui=self.approve is None, extra_args=args, append_system_prompt=CAPRI_CONVERSATION_PROMPT)
        client = self.client
        client.on_message_update(lambda event: self._on_client_update(client, event))
        if self.approve is not None:
            client.on_ui_request(lambda request: self._loop.call_soon_threadsafe(
                self._on_ui, client, self._run, request))
            client.on_tool_execution_end(lambda event: self._loop.call_soon_threadsafe(
                self._forget_call, client, self._run, event.tool_call_id))
        try:
            await asyncio.to_thread(self.client.start)
            models = await asyncio.to_thread(self.client.get_available_models)
            if not any(m.provider == 'openai-codex' and m.id == 'gpt-6-luna' for m in models):
                raise EngineError('OMP gpt-6-luna is unavailable')
            await asyncio.to_thread(self.client.set_model, 'openai-codex', 'gpt-6-luna')
            state = await asyncio.to_thread(self.client.get_state)
            if (state.model.provider, state.model.id) != ('openai-codex', 'gpt-6-luna'):
                raise EngineError('OMP selected an unexpected model')
            if {t.name for t in state.dump_tools} != set(OWNER_TOOLS):
                raise EngineError('OMP effective tools differ from the verified owner set')
            if not state.session_file or not Path(state.session_file).resolve().is_relative_to(sessions):
                raise EngineError('OMP selected storage outside Capri')
            write_json(pointer, {'path': state.session_file})
        except Exception:
            await self.close()
            raise EngineError('OMP startup/model/isolation check failed') from None

    def _on_client_update(self, client, event):
        if client is not self.client:
            return
        update = event.assistant_message_event
        if update.get('type') == 'toolcall_end' and self.approve is not None:
            self._loop.call_soon_threadsafe(self._record_call, client, self._run,
                                           update.get('toolCall'))
        self._on_update(event)

    def _record_call(self, client, run, call):
        if (client is self.client and run is not None and run is self._run
                and isinstance(call, dict) and call.get('name') == 'bash'
                and isinstance(call.get('id'), str)):
            self._calls[call['id']] = call.get('arguments', {})

    def _forget_call(self, client, run, call_id):
        if client is self.client and run is self._run:
            self._calls.pop(call_id, None)

    def _on_ui(self, client, run, request):
        if request.method == 'cancel':
            self._ui_cancelled.add((id(client), request.id))
            task = self._ui_tasks.get((id(client), request.id))
            if task is not None:
                task.cancel()
            return
        # Passive requests do not take a response and must never perform host actions.
        if request.method in {'notify', 'setStatus', 'setWidget', 'setTitle',
                              'set_editor_text', 'open_url'}:
            return
        key = (id(client), request.id)
        if key in self._ui_seen:
            return
        self._ui_seen.add(key)
        if key in self._ui_cancelled:
            return
        task = asyncio.create_task(self._answer_ui(client, run, request))
        self._ui_tasks[key] = task

    async def _answer_ui(self, client, run, request):
        key = (id(client), request.id)
        replied = False
        explain = False
        try:
            if client is not self.client or run is None or run is not self._run:
                return
            explain = True
            options = getattr(request, 'options', ()) or ()
            label = 'Approve' if 'Approve' in options else 'Approve Once'
            title = getattr(request, 'title', '') or ''
            # Pinned native prompt can include a reason before Command, but nothing
            # except the exact command after it. Commands beyond 2000 UTF-16 units
            # are truncated upstream, so they cannot be approved here.
            lines = title.split('\n')
            if (request.method != 'select' or not lines or lines[0] != 'Allow tool: bash'
                    or label not in options or 'Deny' not in options):
                return
            candidates = []
            for call_id, args in self._calls.items():
                if not isinstance(args, dict):
                    continue
                command = args.get('command')
                if not isinstance(command, str) or not command or len(command.encode('utf-16-le')) // 2 > 2000:
                    continue
                prefix, separator, rendered = title.partition('\nCommand: ')
                if (separator and rendered == command and
                        all(line.startswith('Reason: ') for line in prefix.split('\n')[1:])):
                    candidates.append((call_id, command, args.get('cwd')))
            if len(candidates) != 1:
                return
            call_id, command, cwd = candidates[0]
            self._calls.pop(call_id, None)
            if cwd is not None:
                if not isinstance(cwd, str) or cwd.startswith('~') or '://' in cwd:
                    return
                path = Path(cwd)
                # Drive-relative paths and alternate streams have different native
                # semantics; do not present a guessed effective directory.
                rest = cwd[len(path.drive):]
                if ':' in rest or (path.drive and not path.is_absolute()):
                    return
            work = self.data / 'work'
            directory = (work / cwd).resolve() if cwd else work
            deadline = min(self._run_deadline, self._loop.time() + 60)
            approval = ShellApproval(request.id, command, directory, title, deadline)
            decision = await asyncio.wait_for(self.approve(approval),
                                              max(0, deadline - self._loop.time()))
            if (client is self.client and run is self._run and key not in self._ui_cancelled
                    and self._loop.time() < deadline):
                # No await between the final lifetime check and the single SDK write.
                replied = True
                client.send_ui_value(request.id, label if decision is True else 'Deny')
        except asyncio.CancelledError:
            explain = False
            raise
        except Exception:
            if replied:
                # The approval write may have reached OMP: never retry or silently
                # treat an uncertain response as a successful turn.
                self._failed = True
        finally:
            if not replied and key not in self._ui_cancelled:
                try:
                    if explain and self.approval_notice is not None and run is self._run:
                        try:
                            await asyncio.wait_for(self.approval_notice(
                                'Shell-виклик відхилено: не вдалося безпечно звірити команду '
                                'або отримати підтвердження. Спробуй коротшу команду з явною директорією.'), 3)
                        except Exception:
                            pass
                finally:
                    try:
                        client.cancel_ui_request(request.id)
                    except Exception:
                        pass

    async def _clear_approvals(self):
        tasks = list(self._ui_tasks.values())
        self._ui_tasks.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            async def join():
                await asyncio.gather(*tasks, return_exceptions=True)
            await complete_cleanup(join())
        self._calls.clear()

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
                    self._run = object()
                    self._run_deadline = self._loop.time() + 180
                    turn = await asyncio.to_thread(self.client.prompt_and_wait,
                        'Capri input JSON:\n' + json.dumps({'text': text}, ensure_ascii=False), timeout=180)
                    if self._failed:
                        raise EngineError('OMP approval response was uncertain')
                    if (turn.result is not None and turn.result.status == 'aborted'
                            and self._aborting):
                        return
                    if turn.result is None or turn.result.status != 'completed':
                        raise EngineError('OMP did not complete the response')
                except Exception:
                    self._failed = True
                    await complete_cleanup(self._stop_client(self.client))
                    queue.put_nowait(EngineError('OMP response failed or process exited; restart Capri'))
                finally:
                    self._active = False
                    self._run = None
                    await self._clear_approvals()
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
                self._run = None
                async def cleanup():
                    await self._clear_approvals()
                    if not task.done():
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

    async def _stop_client(self, client):
        async with self._stop_lock:
            self.safe = False
            self.safe = await asyncio.to_thread(stop_child, client)

    async def close(self):
        self._run = None
        async def cleanup():
            await self._clear_approvals()
            if self.client is not None:
                await self._stop_client(self.client)
        await complete_cleanup(cleanup())
