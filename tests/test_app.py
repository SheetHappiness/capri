import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from capri.config import Pairing
from capri.app import handle_text


def test_app_routes_owner_approval_callbacks_outside_stream_and_closes(tmp_path, monkeypatch):
    import capri.app as app
    from capri.config import write_json
    from capri.engine import ShellApproval
    from test_approval import Bot as DialogBot, query, wait_sent
    write_json(tmp_path/'owner.json', {'owner_id': 7})
    instances = []; guests = []
    class Owner:
        def __init__(self, executable, data, **kw):
            self.approve = kw.get('approve'); self.client = None; self.safe = True
            self.closed = False; instances.append(self)
        async def start(self): pass
        async def close(self): self.closed = True
    class Guest:
        def __init__(self, *args, **kw): guests.append(kw); self.safe = True
    class Bot(DialogBot):
        def __init__(self, token):
            super().__init__(); self.session = NS(close=AsyncMock())
        async def get_me(self): return NS(username='capri', supports_guest_queries=False)
    bot = Bot('not-a-token')
    monkeypatch.setattr(app, 'Bot', lambda token: bot)
    monkeypatch.setattr(app, 'Engine', Owner)
    monkeypatch.setattr(app, 'GuestEngine', Guest)
    pending = []
    async def poll(dp, passed_bot, **kw):
        assert 'callback_query' in kw['allowed_updates']
        assert callable(instances[0].approve)
        r = ShellApproval('native', 'printf test', tmp_path, 'native', asyncio.get_running_loop().time()+60)
        task = asyncio.create_task(instances[0].approve(r))
        await wait_sent(bot)
        handlers = dp.sub_routers[0].callback_query.handlers
        assert len(handlers) == 1
        await asyncio.wait_for(handlers[0].callback(query(bot)), 1)
        assert await task is True
        # A dialog outstanding when polling ends must be revoked in finally.
        pending.append(asyncio.create_task(instances[0].approve(r)))
        while len(bot.sent) < 2: await asyncio.sleep(0)
    monkeypatch.setattr(app.Dispatcher, 'start_polling', poll)
    async def run():
        await app.run('not-a-token', tmp_path/'omp.exe', tmp_path)
        assert await pending[0] is False
        assert instances[0].closed
        assert guests == [{}]
        bot.session.close.assert_awaited_once()
    asyncio.run(run())

def test_stop_revokes_dialog_before_guest_handoff_and_resume(tmp_path, monkeypatch):
    import capri.app as app
    from capri.engine import Engine
    from capri.guest_engine import GuestEngine
    from capri.approval import ApprovalBridge
    from test_engine_approval import ApprovalSDK
    from test_guest_engine import GuestSDK
    from test_approval import Bot, query, wait_sent

    async def consume(bot, chat_id, stream, **kw):
        async for _ in stream: pass
    monkeypatch.setattr(app, 'deliver', consume)
    async def run():
        bot = Bot(); bridge = ApprovalBridge(bot, lambda: 7)
        engine = Engine(tmp_path/'omp.exe', tmp_path, sdk_factory=ApprovalSDK, approve=bridge.request)
        await engine.start()
        runtime = app.OmpRuntime(engine, GuestEngine(tmp_path/'omp.exe', tmp_path, sdk_factory=GuestSDK))
        flow = app.InboundFlow(bot, runtime)
        try:
            flow.submit(7, 'test')
            await wait_sent(bot)
            stale = query(bot)
            await asyncio.wait_for(flow.stop(), 2)
            assert not any(value.startswith('Approve') for _, value in engine.client.responses)
            directory = tmp_path/'guest/sessions/7'/('a'*12)
            _ = [p async for p in runtime.stream_guest(directory, text='hi', reference_text=None)]
            assert not runtime.owner_ready and engine.client is None
            await bridge.handle_callback(stale)
            flow.submit(7, 'next')
            while len(bot.sent) < 2: await asyncio.sleep(.001)
            await bridge.handle_callback(stale)
            assert not flow.worker.done()
            await bridge.handle_callback(query(bot, mid=2))
            await asyncio.wait_for(flow.wait(), 2)
            assert engine.client.responses == [('ui-1', 'Approve')]
        finally:
            await bridge.close(); await flow.stop(); await engine.close()
    asyncio.run(run())


def test_repeated_shutdown_cancellation_still_closes_owner(tmp_path, monkeypatch):
    import capri.app as app
    async def run():
        polling = asyncio.Event(); cleaning = asyncio.Event(); release = asyncio.Event()
        owner = NS(start=AsyncMock(), close=AsyncMock(), client=None)
        bot = NS(get_me=AsyncMock(return_value=NS(username='capri', supports_guest_queries=False)),
                 session=NS(close=AsyncMock()))
        async def bridge_close(): cleaning.set(); await release.wait()
        bridge = NS(request=AsyncMock(), notice=AsyncMock(), close=bridge_close)
        async def poll(*args, **kw): polling.set(); await asyncio.Event().wait()
        monkeypatch.setattr(app, 'Engine', lambda *a, **kw: owner)
        monkeypatch.setattr(app, 'Bot', lambda *a: bot)
        monkeypatch.setattr(app, 'ApprovalBridge', lambda *a: bridge)
        monkeypatch.setattr(app.Dispatcher, 'start_polling', poll)
        task = asyncio.create_task(app.run('test', tmp_path/'omp.exe', tmp_path))
        await polling.wait(); task.cancel(); await cleaning.wait()
        task.cancel(); release.set()
        import pytest
        with pytest.raises(asyncio.CancelledError): await task
        owner.close.assert_awaited_once()
        bot.session.close.assert_awaited_once()
    asyncio.run(run())


def test_owner_pairing_gate_and_group_rejection(tmp_path):
    async def run():
        pairing=Pairing(tmp_path/'owner.json'); bot=NS(send_message=AsyncMock())
        engine=NS(stream=lambda _: (_ for _ in ()))
        lock=asyncio.Lock()
        def msg(user,text,kind='private'):
            return NS(chat=NS(id=user,type=kind),from_user=NS(id=user),text=text)
        await handle_text(msg(5,'/start '+pairing.nonce,'group'),bot,engine,pairing,lock)
        assert pairing.owner_id is None
        await handle_text(msg(5,'hi'),bot,engine,pairing,lock)
        assert pairing.owner_id is None
        await handle_text(msg(7,'/start '+pairing.nonce),bot,engine,pairing,lock)
        assert pairing.owner_id==7
        bot.send_message.reset_mock()
        await handle_text(msg(5,'private question'),bot,engine,pairing,lock)
        bot.send_message.assert_not_called()
    asyncio.run(run())
