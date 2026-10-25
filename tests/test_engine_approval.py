import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from capri.engine import Engine
from test_engine import SDK


class ApprovalSDK(SDK):
    command = 'printf approval-test'
    cwd = None
    title = None
    options = ('Approve', 'Approve bash for this session', 'Deny')
    method = 'select'
    duplicate_call = False
    duplicate_ui = False
    cancel_request = False

    def __init__(self, **kw):
        super().__init__(**kw)
        self.answer = threading.Event()
        self.requested = threading.Event()
        self.responses = []
        self.listener_returned = threading.Event()

    def on_ui_request(self, cb): self.ui = cb
    def on_tool_execution_end(self, cb): self.tool_end = cb

    def send_ui_value(self, request_id, value):
        self.responses.append((request_id, value)); self.answer.set()

    def cancel_ui_request(self, request_id, **kw):
        self.responses.append((request_id, 'cancel')); self.answer.set()

    def prompt_and_wait(self, message, **kw):
        args = {'command': self.command, 'cwd': self.cwd}
        self.callback(NS(message={'role': 'assistant'}, assistant_message_event={
            'type': 'toolcall_end', 'toolCall': {'id': 'call-1', 'name': 'bash', 'arguments': args}}))
        if self.duplicate_call:
            self.callback(NS(message={'role': 'assistant'}, assistant_message_event={
                'type': 'toolcall_end', 'toolCall': {'id': 'call-2', 'name': 'bash',
                    'arguments': {**args, 'cwd': 'elsewhere'}}}))
        request = NS(id='ui-1', method=self.method,
            title=self.title or 'Allow tool: bash\nCommand: ' + self.command,
            options=self.options)
        self.ui(request)
        if self.duplicate_ui: self.ui(request)
        self.listener_returned.set(); self.requested.set()
        if self.cancel_request:
            self.ui(NS(id='ui-1', method='cancel'))
            return NS(result=NS(status='completed'))
        assert self.answer.wait(3), 'approval response was never delivered'
        return NS(result=NS(status='completed'))

    def abort(self): self.answer.set()
    def stop(self): self.answer.set(); return super().stop()


@pytest.mark.parametrize('decision,options,want', [
    (True, ('Approve', 'Approve bash for this session', 'Deny'), 'Approve'),
    (True, ('Approve Once', 'Always Approve', 'Deny'), 'Approve Once'),
    (False, ('Approve', 'Deny'), 'Deny'),
])
def test_native_once_only_and_exact_command_context(tmp_path, decision, options, want):
    class Native(ApprovalSDK): pass
    Native.options = options
    Native.cwd = 'folder'
    seen = []
    async def approve(request):
        seen.append(request)
        return decision
    async def run():
        engine = Engine(tmp_path/'omp.exe', tmp_path, sdk_factory=Native, approve=approve)
        await engine.start()
        try:
            assert engine.client.kw['no_ui'] is False
            assert [p async for p in engine.stream('test')] == []
            assert engine.client.responses == [('ui-1', want)]
            assert len(seen) == 1
            assert seen[0].command == 'printf approval-test'
            assert seen[0].cwd == (tmp_path/'work/folder').resolve()
            assert 0 < seen[0].deadline - asyncio.get_running_loop().time() <= 60
        finally: await engine.close()
    asyncio.run(run())


@pytest.mark.parametrize('bad', ['unknown', 'truncated', 'ambiguous', 'method', 'grants', 'cwd'])
def test_unverifiable_native_dialog_never_approves(tmp_path, bad):
    class Native(ApprovalSDK): pass
    if bad == 'unknown': Native.title = 'Allow tool: write\nCommand: printf approval-test'
    if bad == 'truncated': Native.command = 'x' * 2001
    if bad == 'ambiguous': Native.duplicate_call = True
    if bad == 'method': Native.method = 'confirm'
    if bad == 'grants': Native.options = ('Approve bash for this session', 'Deny')
    if bad == 'cwd': Native.cwd = 'skill://untrusted'
    seen = []
    async def approve(request): seen.append(request); return True
    async def run():
        e = Engine(tmp_path/'omp.exe', tmp_path, sdk_factory=Native, approve=approve)
        await e.start()
        try:
            _ = [p async for p in e.stream('test')]
            assert not seen
            assert e.client.responses == [('ui-1', 'cancel')]
        finally: await e.close()
    asyncio.run(run())


@pytest.mark.parametrize('finish', ['cancel', 'close', 'native_cancel'])
def test_pending_approval_revoked_before_cleanup_and_late_click(tmp_path, finish):
    class Native(ApprovalSDK): pass
    Native.cancel_request = finish == 'native_cancel'
    async def run():
        entered = asyncio.Event(); revoked = asyncio.Event()
        async def approve(request):
            entered.set()
            try: await asyncio.Event().wait()
            finally: revoked.set()
        e = Engine(tmp_path/'omp.exe', tmp_path, sdk_factory=Native, approve=approve)
        await e.start()
        async def consume(): return [p async for p in e.stream('test')]
        turn = asyncio.create_task(consume())
        if finish == 'native_cancel':
            await asyncio.wait_for(turn, 2)
        else:
            await asyncio.wait_for(entered.wait(), 2)
            assert await asyncio.to_thread(e.client.listener_returned.wait, .5)
            if finish == 'close': await e.close()
            else: turn.cancel()
            try: await asyncio.wait_for(turn, 2)
            except (asyncio.CancelledError, Exception): pass
            assert revoked.is_set()
        assert not any(value.startswith('Approve') for _, value in e.client.responses)
        await e.close()
    asyncio.run(run())


def test_duplicate_native_request_only_answers_once(tmp_path):
    class Native(ApprovalSDK): duplicate_ui = True
    async def approve(request): await asyncio.sleep(0); return True
    async def run():
        e = Engine(tmp_path/'omp.exe', tmp_path, sdk_factory=Native, approve=approve)
        await e.start()
        try:
            _ = [p async for p in e.stream('test')]
            assert e.client.responses == [('ui-1', 'Approve')]
        finally: await e.close()
    asyncio.run(run())


@pytest.mark.parametrize('style', ['forward_absolute', 'drive_relative', 'ads'])
def test_windows_cwd_semantics_are_not_misrepresented(tmp_path, style):
    class Native(ApprovalSDK): pass
    Native.cwd = str(tmp_path).replace('\\', '/') if style == 'forward_absolute' else (
        'C:relative' if style == 'drive_relative' else 'folder:stream')
    seen = []
    async def approve(request): seen.append(request); return True
    async def run():
        e = Engine(tmp_path/'omp.exe', tmp_path, sdk_factory=Native, approve=approve)
        await e.start()
        try:
            _ = [p async for p in e.stream('test')]
            assert bool(seen) is (style == 'forward_absolute')
            if seen: assert seen[0].cwd == tmp_path.resolve()
        finally: await e.close()
    asyncio.run(run())


def test_uncertain_sdk_approval_write_does_not_complete_or_retry(tmp_path):
    class Broken(ApprovalSDK):
        def send_ui_value(self, request_id, value):
            super().send_ui_value(request_id, value)
            raise OSError('uncertain write')
    async def approve(request): return True
    async def run():
        from capri.engine import EngineError
        e = Engine(tmp_path/'omp.exe', tmp_path, sdk_factory=Broken, approve=approve)
        await e.start()
        with pytest.raises(EngineError):
            _ = [p async for p in e.stream('test')]
        assert e.client.responses == [('ui-1', 'Approve')]
        assert e.client.stopped
        with pytest.raises(EngineError):
            _ = [p async for p in e.stream('again')]
        await e.close()
    asyncio.run(run())


def test_callback_suppressing_cancellation_cannot_send_late_allow(tmp_path):
    async def run():
        entered = asyncio.Event()
        async def approve(request):
            entered.set()
            try: await asyncio.Event().wait()
            except asyncio.CancelledError: return True
        e = Engine(tmp_path/'omp.exe', tmp_path, sdk_factory=ApprovalSDK, approve=approve)
        await e.start()
        async def consume(): return [p async for p in e.stream('test')]
        task = asyncio.create_task(consume())
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert not any(value.startswith('Approve') for _, value in e.client.responses)
        await e.close()
    asyncio.run(run())


def test_callback_errors_fail_closed(tmp_path):
    async def run():
        async def approve(request): raise OSError('private error')
        e = Engine(tmp_path/'omp.exe', tmp_path, sdk_factory=ApprovalSDK, approve=approve)
        await e.start()
        try:
            _ = [p async for p in e.stream('test')]
            assert e.client.responses == [('ui-1', 'cancel')]
        finally: await e.close()
    asyncio.run(run())


def test_approval_timeout_is_bounded_by_run_deadline(tmp_path):
    async def run():
        class Expiring(ApprovalSDK):
            def prompt_and_wait(self, message, **kw):
                e._loop.call_soon_threadsafe(setattr, e, '_run_deadline', e._loop.time() + .03)
                return super().prompt_and_wait(message, **kw)
        async def approve(request): await asyncio.Event().wait()
        e = Engine(tmp_path/'omp.exe', tmp_path, sdk_factory=Expiring, approve=approve)
        await e.start()
        try:
            _ = [p async for p in e.stream('test')]
            assert e.client.responses == [('ui-1', 'cancel')]
        finally: await e.close()
    asyncio.run(run())


def test_multiple_native_requests_and_default_work_directory(tmp_path):
    class Multiple(ApprovalSDK):
        def prompt_and_wait(self, message, **kw):
            for index in range(2):
                self.answer.clear()
                self.callback(NS(message={'role': 'assistant'}, assistant_message_event={
                    'type': 'toolcall_end', 'toolCall': {'id': f'call-{index}', 'name': 'bash',
                        'arguments': {'command': f'printf {index}', 'cwd': None}}}))
                self.ui(NS(id=f'ui-{index}', method='select', options=('Approve', 'Deny'),
                    title=f'Allow tool: bash\nCommand: printf {index}'))
                assert self.answer.wait(2)
                self.tool_end(NS(tool_call_id=f'call-{index}'))
            return NS(result=NS(status='completed'))
    async def run():
        seen = []
        async def approve(request): seen.append(request); return len(seen) == 1
        e = Engine(tmp_path/'omp.exe', tmp_path, sdk_factory=Multiple, approve=approve)
        await e.start()
        try:
            _ = [p async for p in e.stream('test')]
            assert e.client.responses == [('ui-0', 'Approve'), ('ui-1', 'Deny')]
            assert all(r.cwd == (tmp_path/'work').resolve() for r in seen)
        finally: await e.close()
    asyncio.run(run())


def test_close_and_failed_prompt_serialize_child_teardown(tmp_path):
    import time
    class SlowStop(ApprovalSDK):
        stopping = threading.Lock()
        overlap = False
        def prompt_and_wait(self, *args, **kw):
            super().prompt_and_wait(*args, **kw)
            return NS(result=NS(status='aborted'))
        def stop(self):
            if not self.stopping.acquire(blocking=False):
                self.overlap = True
                return False
            try:
                time.sleep(.05)
                return super().stop()
            finally: self.stopping.release()
    async def run():
        entered = asyncio.Event()
        async def approve(request): entered.set(); await asyncio.Event().wait()
        e = Engine(tmp_path/'omp.exe', tmp_path, sdk_factory=SlowStop, approve=approve)
        await e.start()
        async def consume(): return [p async for p in e.stream('test')]
        task = asyncio.create_task(consume())
        await entered.wait()
        await e.close()
        await asyncio.gather(task, return_exceptions=True)
        assert not e.client.overlap
    asyncio.run(run())


def test_unverifiable_call_has_owner_notice_but_no_dialog(tmp_path):
    class Native(ApprovalSDK): duplicate_call = True
    async def run():
        seen = []; notices = []
        async def approve(request): seen.append(request); return True
        async def notice(text): notices.append(text)
        e = Engine(tmp_path/'omp.exe', tmp_path, sdk_factory=Native,
                   approve=approve, approval_notice=notice)
        await e.start()
        try:
            _ = [p async for p in e.stream('test')]
            assert not seen and len(notices) == 1
            assert 'відхилено' in notices[0]
        finally: await e.close()
    asyncio.run(run())


def test_repeated_cancel_still_aborts_and_joins_prompt_worker(tmp_path):
    class Native(ApprovalSDK):
        def __init__(self, **kw):
            super().__init__(**kw); self.release_worker = threading.Event()
            self.finished = threading.Event(); self.aborted = False
        def prompt_and_wait(self, *args, **kw):
            try:
                result = super().prompt_and_wait(*args, **kw)
                self.release_worker.wait(3)
                return result
            finally: self.finished.set()
        def abort(self): self.aborted = True; self.release_worker.set()
    async def run():
        entered = asyncio.Event(); cleaning = asyncio.Event(); release_cleanup = asyncio.Event()
        async def approve(request):
            entered.set()
            try: await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release_cleanup.wait()
        e = Engine(tmp_path/'omp.exe', tmp_path, sdk_factory=Native, approve=approve)
        await e.start()
        async def consume(): return [p async for p in e.stream('test')]
        task = asyncio.create_task(consume())
        await entered.wait(); task.cancel(); await cleaning.wait()
        task.cancel(); release_cleanup.set()
        try:
            with pytest.raises(asyncio.CancelledError): await asyncio.wait_for(task, 2)
            assert e.client.aborted and e.client.finished.is_set()
        finally:
            e.client.release_worker.set()
            await e.close()
    asyncio.run(run())


def test_default_engine_stays_headless(tmp_path):
    async def run():
        e = Engine(tmp_path/'omp.exe', tmp_path, sdk_factory=SDK)
        await e.start()
        assert e.client.kw['no_ui'] is True
        await e.close()
    asyncio.run(run())
