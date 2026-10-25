import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from capri.app import OmpRuntime, run
from capri.engine import EngineError, SteerResult
from capri.config import write_json


def test_serial_child_lifetimes_lazy_owner_resume_and_busy_wait():
    async def scenario():
        events=[]; finish=asyncio.Event(); entered=asyncio.Event()
        class Owner:
            def __init__(self): self.client=NS(stop=lambda: events.append('owner_stop') or True)
            async def start(self): events.append('owner_start')
            async def stream(self,text):
                events.append('owner_turn'); entered.set(); await finish.wait(); yield text
            async def steer(self,text): return SteerResult.ACCEPTED
        class Guest:
            safe=True
            async def stream(self,*a,**kw): events.append('guest_turn'); yield 'guest'
        owner=Owner(); runtime=OmpRuntime(owner,Guest())
        async def dm(): return [x async for x in runtime.stream('dm')]
        async def guest(): return [x async for x in runtime.stream_guest('thread',text='guest',reference_text=None)]
        dm_task=asyncio.create_task(dm()); await entered.wait()
        guest_task=asyncio.create_task(guest()); await asyncio.sleep(0)
        assert events==['owner_turn']
        finish.set(); assert await dm_task==['dm']; assert await guest_task==['guest']
        assert events==['owner_turn','owner_stop','guest_turn']
        assert await runtime.steer('late') is SteerResult.NOT_ACTIVE
        assert await dm()==['dm']
        assert events[-2:]==['owner_start','owner_turn']
    asyncio.run(scenario())


@pytest.mark.parametrize('result',[False,None,1,'yes'])
def test_unconfirmed_child_teardown_blocks_shared_runtime(result):
    async def scenario():
        owner=NS(client=NS(stop=lambda:result),start=AsyncMock())
        guest=NS(safe=True,stream=lambda *a,**kw: pytest.fail('guest must not spawn'))
        runtime=OmpRuntime(owner,guest)
        with pytest.raises(EngineError):
            _=[x async for x in runtime.stream_guest('thread',text='hi',reference_text=None)]
        with pytest.raises(EngineError): _=[x async for x in runtime.stream('hi')]
        owner.start.assert_not_called()
    asyncio.run(scenario())


@pytest.mark.parametrize('cancellations',[1,2])
def test_cancel_during_owner_stop_joins_teardown_before_unlock(cancellations):
    import threading
    async def scenario():
        entered=threading.Event(); release=threading.Event(); stopped=threading.Event()
        def stop(): entered.set(); release.wait(2); stopped.set(); return True
        owner=NS(client=NS(stop=stop),start=AsyncMock())
        guest=NS(safe=True,stream=lambda *a,**kw: pytest.fail('cancelled guest must not spawn'))
        runtime=OmpRuntime(owner,guest)
        async def consume(): return [x async for x in runtime.stream_guest('thread',text='hi',reference_text=None)]
        task=asyncio.create_task(consume())
        assert await asyncio.to_thread(entered.wait,1)
        try:
            for _ in range(cancellations):
                task.cancel(); await asyncio.sleep(0.01)
            assert runtime.lock.locked()
        finally: release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert stopped.is_set() and not runtime.owner_ready
    asyncio.run(scenario())


@pytest.mark.parametrize('cancellations',[1,2])
def test_cancel_lazy_owner_start_joins_and_stops_before_unlock(cancellations):
    import threading
    async def scenario():
        entered=threading.Event(); release=threading.Event(); stopped=[]
        def start(): entered.set(); release.wait(2)
        class Owner:
            client=None
            async def start(self):
                self.client=NS(stop=lambda:stopped.append(True) or True)
                await asyncio.to_thread(start)
        runtime=OmpRuntime(Owner(),NS(safe=True))
        runtime.owner_ready=False
        async def consume(): return [x async for x in runtime.stream('dm')]
        task=asyncio.create_task(consume())
        assert await asyncio.to_thread(entered.wait,1)
        try:
            for _ in range(cancellations):
                task.cancel(); await asyncio.sleep(0.01)
            assert runtime.lock.locked()
        finally: release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert stopped==[True] and runtime.owner.client is None and not runtime.owner_ready
    asyncio.run(scenario())


@pytest.mark.parametrize('capability',[True,False,None])
def test_normal_poller_integration_and_disabled_guest_survives(tmp_path,monkeypatch,capability):
    import capri.app as app
    from aiogram import Dispatcher
    from test_guest import Transport
    from test_guest_probe import message
    from aiogram.types import Update
    async def scenario():
        write_json(tmp_path/'owner.json',{'owner_id':7})
        bot=Transport()
        async def get_me(): return NS(username='Capriompbot',supports_guest_queries=capability)
        bot.get_me=get_me
        class Owner:
            def __init__(self,*a): self.client=NS(stop=lambda:True)
            async def start(self): pass
            async def close(self): pass
        engine=Owner()
        monkeypatch.setattr(app,'Engine',lambda *a, **kw:engine)
        monkeypatch.setattr(app,'Bot',lambda *a:bot)
        poll_calls=[]
        async def polling(self,actual_bot,**kw):
            poll_calls.append(kw)
            assert set(kw['allowed_updates'])=={'message','guest_message','callback_query'}
            assert actual_bot is bot
            await self.feed_update(bot,Update(update_id=1,guest_message=message(text='/status')))
        monkeypatch.setattr(Dispatcher,'start_polling',polling)
        await run('123:TEST',tmp_path/'omp.exe',tmp_path)
        assert len(poll_calls)==1
        assert bool(bot.calls) is (capability is True)
        await bot.session.close()
    asyncio.run(scenario())


def test_malformed_guest_store_does_not_stop_dm_startup(tmp_path,monkeypatch):
    import capri.app as app
    from aiogram import Dispatcher
    async def scenario():
        write_json(tmp_path/'owner.json',{'owner_id':7})
        path=tmp_path/'guest/threads.json'; path.parent.mkdir(); path.write_text('{')
        owner=NS(start=AsyncMock(),close=AsyncMock())
        bot=NS(get_me=AsyncMock(return_value=NS(username='Capriompbot',supports_guest_queries=True)),
               session=NS(close=AsyncMock()))
        polling=AsyncMock()
        monkeypatch.setattr(app,'Engine',lambda *a, **kw:owner)
        monkeypatch.setattr(app,'Bot',lambda *a:bot)
        monkeypatch.setattr(Dispatcher,'start_polling',polling)
        await run('123:TEST',tmp_path/'omp.exe',tmp_path)
        owner.start.assert_awaited_once(); polling.assert_awaited_once()
    asyncio.run(scenario())
