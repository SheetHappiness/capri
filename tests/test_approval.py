import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import threading

import pytest
from omp_rpc import ExtensionUiRequest

from capri.engine import Engine
from test_engine import SDK


def request(id='native-1', options=('Approve', 'Approve bash for this session', 'Deny')):
    return ExtensionUiRequest(id=id, method='select', title='Allow tool: bash\nCommand: echo hello', options=options)


def test_sdk_approval_reply_is_native_once_only_and_abort_clears_pending(tmp_path):
    class Waiting(SDK):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.ready = threading.Event()
            self.replies = []
            self.aborted = False
        def on_ui_request(self, cb): self.ui = cb
        def send_ui_value(self, id, value): self.replies.append((id, value)); self.ready.set()
        def cancel_ui_request(self, id): self.replies.append((id, None)); self.ready.set()
        def prompt_and_wait(self, *args, **kw):
            self.ui(request())
            assert self.ready.wait(2)
            return NS(result=NS(status='aborted' if self.aborted else 'completed'))
        def abort(self): self.aborted = True; self.ready.set()
    async def run():
        engine = Engine(tmp_path/'omp.exe', tmp_path, sdk_factory=Waiting)
        await engine.start()
        try:
            assert engine.client.kw['no_ui'] is False
            stream = engine.stream('echo')
            item = await anext(stream)
            assert item.id == 'native-1'
            assert await engine.answer_approval(item.id, 'Approve') is True
            assert await engine.answer_approval(item.id, 'Approve') is False
            assert [part async for part in stream] == []
            assert engine.client.replies == [('native-1', 'Approve')]
            assert await engine.answer_approval(item.id, 'Deny') is False
            engine.client.ready.clear()
            stream = engine.stream('again')
            await anext(stream)
            engine.request_abort()
            assert await engine.answer_approval('native-1', 'Approve') is False
            await stream.aclose()
            assert engine.client.aborted
            assert await engine.answer_approval('native-1', 'Approve') is False
            engine.client.ready.clear()
            engine.client.aborted = False
            stream = engine.stream('new turn')
            await anext(stream)
            assert await engine.answer_approval('native-1', 'Approve') is True
            assert [part async for part in stream] == []
        finally:
            await engine.close()
    asyncio.run(run())


class Bot:
    def __init__(self):
        self.messages = []
        self.edits = []
        self.answer_callback_query = AsyncMock()
    async def send_message(self, **kw):
        self.messages.append(kw)
        return NS(message_id=len(self.messages))
    async def edit_message_reply_markup(self, **kw): self.edits.append(kw)


def test_approval_card_row_native_response_owner_binding_and_duplicate_click():
    from capri.approval import ApprovalUI
    async def run():
        bot = Bot()
        respond = AsyncMock(return_value=True)
        ui = ApprovalUI(bot, lambda: 7, respond)
        await ui.show(7, request())
        card = bot.messages[0]
        row, = card['reply_markup'].inline_keyboard
        assert [button.text for button in row] == ['Once', 'Session', 'Deny']
        assert 'Command: echo hello' in card['text'] and card['parse_mode'] is None
        assert 'Approve bash for this session' in card['text']
        def query(user=7, chat=7, message_id=1):
            return NS(id='q', data=row[1].callback_data, from_user=NS(id=user),
                message=NS(chat=NS(id=chat, type='private'), message_id=message_id))
        for click in (query(user=8), query(chat=8), query(message_id=2)):
            await ui.handle(click)
        respond.assert_not_called()
        await ui.handle(query())
        respond.assert_awaited_once_with('native-1', 'Approve bash for this session')
        await ui.handle(query())
        assert respond.await_count == 1 and bot.edits[-1]['reply_markup'] is None
        await ui.finish()
    asyncio.run(run())


@pytest.mark.parametrize('options,expected', [
    (('Approve', 'Deny'), ['Once', 'Deny']),
    (('Approve Directory: C:/notes', 'Approve File', 'Always Approve File', 'Approve Once', 'Deny'),
     ['Once', 'Session', 'Deny']),
])
def test_only_native_choices_are_shown(options, expected):
    from capri.approval import ApprovalUI
    async def run():
        bot = Bot(); respond = AsyncMock(return_value=True)
        ui = ApprovalUI(bot, lambda: 7, respond)
        await ui.show(7, request(options=options))
        row = bot.messages[0]['reply_markup'].inline_keyboard[0]
        assert [button.text for button in row] == expected
        if 'Session' in expected:
            assert 'Session: Approve File' in bot.messages[0]['text']
        await ui.finish()
    asyncio.run(run())


def test_failed_or_oversized_card_declines_without_retry_and_finish_invalidates():
    from capri.approval import ApprovalUI
    async def run():
        bot = Bot(); respond = AsyncMock(return_value=True)
        ui = ApprovalUI(bot, lambda: 7, respond)
        huge = ExtensionUiRequest(id='huge', method='select', title='Allow tool: bash\n'+'😀'*3000,
                                  options=('Approve', 'Deny'))
        await ui.show(7, huge)
        respond.assert_awaited_once_with('huge', 'Deny')
        assert not bot.messages
        bot.send_message = AsyncMock(side_effect=TimeoutError('uncertain'))
        await ui.show(7, request())
        assert bot.send_message.await_count == 1
        assert respond.await_args.args == ('native-1', 'Deny')
        bot = Bot(); ui = ApprovalUI(bot, lambda: 7, respond)
        await ui.show(7, request())
        row = bot.messages[0]['reply_markup'].inline_keyboard[0]
        await ui.finish()
        count = respond.await_count
        query = NS(id='late', data=row[0].callback_data, from_user=NS(id=7),
                   message=NS(chat=NS(id=7, type='private'), message_id=1))
        await ui.handle(query)
        assert respond.await_count == count
    asyncio.run(run())


@pytest.mark.parametrize('cancel', [False, True])
def test_native_approval_crosses_runtime_without_locking_and_closes_card(tmp_path, cancel):
    from capri.approval import ApprovalUI
    from capri.app import InboundFlow, OmpRuntime

    class Waiting(SDK):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.release = threading.Event()
            self.responses = []
            self.aborted = False
        def send_ui_value(self, id, value):
            self.responses.append((id, value)); self.release.set()
        def prompt_and_wait(self, message, **kw):
            self.ui_callback(request())
            assert self.release.wait(2)
            if self.aborted:
                return NS(result=NS(status='aborted'))
            return super().prompt_and_wait(message, **kw)
        def abort(self): self.aborted = True; self.release.set()

    async def run():
        engine = Engine(tmp_path/'omp.exe', tmp_path, sdk_factory=Waiting)
        await engine.start()
        runtime = OmpRuntime(engine, NS(safe=True))
        shown = asyncio.Event()
        class DeliveryBot(Bot):
            async def send_message(self, **kw):
                message = await super().send_message(**kw)
                if 'reply_markup' in kw: shown.set()
                return message
            async def send_message_draft(self, **kw): pass
        bot = DeliveryBot()
        ui = ApprovalUI(bot, lambda: 7, runtime.answer_approval)
        flow = InboundFlow(bot, runtime, approvals=ui)
        try:
            flow.submit(7, 'echo')
            await asyncio.wait_for(shown.wait(), 1)
            assert runtime.lock.locked()
            row = bot.messages[0]['reply_markup'].inline_keyboard[0]
            if cancel:
                await asyncio.wait_for(flow.stop(), 1)
            query = NS(id='q', data=row[0].callback_data, from_user=NS(id=7),
                message=NS(chat=NS(id=7, type='private'), message_id=1))
            await asyncio.wait_for(ui.handle(query), 1)
            if cancel:
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(flow.wait(), 1)
            else:
                await asyncio.wait_for(flow.wait(), 1)
            if cancel:
                assert engine.client.responses == [] and engine.client.aborted
                assert len(bot.messages) == 1
            else:
                assert engine.client.responses == [('native-1', 'Approve')]
                assert bot.messages[-1]['text'] == 'Hello owner'
            assert not ui.pending and not runtime.lock.locked()
            assert bot.edits[-1]['reply_markup'] is None
        finally:
            engine.client.release.set()
            await flow.stop()
            await engine.close()
    asyncio.run(run())


def test_stop_rejects_approval_before_stream_cleanup_and_abort_finish(tmp_path):
    from capri.approval import ApprovalUI
    from capri.app import InboundFlow, OmpRuntime

    class Waiting(SDK):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.release = threading.Event()
            self.abort_entered = threading.Event()
            self.finish_abort = threading.Event()
            self.responses = []
        def send_ui_value(self, id, value):
            self.responses.append((id, value))
        def prompt_and_wait(self, *args, **kw):
            self.ui_callback(request())
            assert self.release.wait(5)
            return NS(result=NS(status='aborted'))
        def abort(self):
            self.abort_entered.set()
            assert self.finish_abort.wait(5)
            self.release.set()

    async def run():
        engine = Engine(tmp_path/'omp.exe', tmp_path, sdk_factory=Waiting)
        await engine.start()
        receiving = asyncio.Event()
        cancelled = asyncio.Event()
        cleanup = asyncio.Event()
        class SlowCleanupRuntime(OmpRuntime):
            async def stream(self, text):
                source = super().stream(text)
                try:
                    async for part in source:
                        yield part
                        receiving.set()
                        try:
                            await asyncio.Event().wait()
                        except asyncio.CancelledError:
                            cancelled.set()
                            await cleanup.wait()
                            raise
                finally:
                    await source.aclose()
        runtime = SlowCleanupRuntime(engine, NS(safe=True))
        bot = Bot()
        ui = ApprovalUI(bot, lambda: 7, runtime.answer_approval)
        flow = InboundFlow(bot, runtime, approvals=ui)
        stop = None
        try:
            flow.submit(7, 'echo')
            await asyncio.wait_for(receiving.wait(), 1)
            row = bot.messages[0]['reply_markup'].inline_keyboard[0]
            stop = asyncio.create_task(flow.stop())
            await asyncio.wait_for(cancelled.wait(), 1)
            assert engine._active and not stop.done()
            assert not engine.client.abort_entered.is_set()
            query = NS(id='racing', data=row[0].callback_data, from_user=NS(id=7),
                message=NS(chat=NS(id=7, type='private'), message_id=1))
            await asyncio.wait_for(ui.handle(query), 1)
            assert engine.client.responses == []
            cleanup.set()
            assert await asyncio.to_thread(engine.client.abort_entered.wait, 1)
            assert not stop.done() and engine.client.responses == []
        finally:
            cleanup.set()
            engine.client.finish_abort.set()
            engine.client.release.set()
            if stop is not None:
                await asyncio.wait_for(stop, 2)
            await flow.stop()
            await engine.close()
        assert not ui.pending and not runtime.lock.locked()
    asyncio.run(run())


def test_failed_source_teardown_still_invalidates_approval_cards():
    from capri.approval import ApprovalUI
    from capri.telegram import deliver
    async def run():
        shown = asyncio.Event()
        class DeliveryBot(Bot):
            async def send_message(self, **kw):
                message = await super().send_message(**kw)
                shown.set()
                return message
            async def send_message_draft(self, **kw): pass
        class Source:
            sent = False
            def __aiter__(self): return self
            async def __anext__(self):
                if not self.sent:
                    self.sent = True
                    return request()
                await asyncio.Event().wait()
            async def aclose(self): raise RuntimeError('abort acknowledgement failed')
        bot = DeliveryBot(); ui = ApprovalUI(bot, lambda: 7, AsyncMock(return_value=False))
        task = asyncio.create_task(deliver(bot, 7, Source(), draft_id=1, approvals=ui))
        await asyncio.wait_for(shown.wait(), 1)
        task.cancel()
        with pytest.raises(RuntimeError, match='abort acknowledgement'):
            await task
        assert not ui.pending
        assert bot.edits[-1]['reply_markup'] is None
    asyncio.run(run())
