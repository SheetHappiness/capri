import asyncio
from types import SimpleNamespace as NS

from capri.app import handle_text
from capri.config import Pairing
from capri.engine import SteerResult


def test_owner_burst_is_debounced_fifo_without_busy_or_restart(tmp_path):
    async def run():
        from capri.app import InboundFlow
        from test_telegram import Bot
        class Engine:
            def __init__(self):
                self.started = asyncio.Event(); self.finish = asyncio.Event()
                self.prompts = []; self.steers = []
            async def stream(self, text):
                self.prompts.append(text); self.started.set()
                yield 'Working'
                await self.finish.wait()
                yield ' done'
            async def steer(self, text):
                self.steers.append(text); return SteerResult.ACCEPTED
        engine = Engine(); bot = Bot(); flow = InboundFlow(bot, engine, debounce=0.03)
        pairing = Pairing(tmp_path / 'owner.json')
        pairing.accept(7, '/start ' + pairing.nonce)
        def msg(text, user=7):
            return NS(chat=NS(id=user, type='private'), from_user=NS(id=user), text=text)
        await handle_text(msg('first'), bot, engine, pairing, flow)
        await engine.started.wait()
        await handle_text(msg('ignored', 8), bot, engine, pairing, flow)
        await handle_text(msg('second'), bot, engine, pairing, flow)
        await asyncio.sleep(0.01)
        await handle_text(msg('third'), bot, engine, pairing, flow)
        assert engine.steers == []
        await asyncio.sleep(0.045)
        assert engine.steers == ['second\n\nthird']
        assert engine.prompts == ['first'] and not bot.messages
        engine.finish.set(); await flow.wait()
        assert len(bot.messages) == 1
    asyncio.run(run())


def test_unavailable_steer_falls_back_to_fifo_prompts():
    async def run():
        from capri.app import InboundFlow
        from test_telegram import Bot
        class Engine:
            def __init__(self): self.prompts = []; self.finish = asyncio.Event()
            async def stream(self, text):
                self.prompts.append(text)
                if text == 'first': await self.finish.wait()
                yield text
            async def steer(self, text): return SteerResult.UNSUPPORTED
        engine = Engine(); bot = Bot(); flow = InboundFlow(bot, engine, debounce=0.01)
        flow.submit(1, 'first'); await asyncio.sleep(0)
        flow.submit(1, 'second'); flow.submit(1, 'third')
        await asyncio.sleep(0.02)
        engine.finish.set(); await flow.wait()
        assert not flow.steer_available
        assert engine.prompts == ['first', 'second', 'third']
        assert [m['text'] for m in bot.messages] == ['first', 'second', 'third']
    asyncio.run(run())


def test_slow_steer_ack_and_new_burst_do_not_duplicate_or_drop_input():
    async def run():
        from capri.app import InboundFlow
        from test_telegram import Bot
        class Engine:
            def __init__(self):
                self.finish = asyncio.Event(); self.ack = asyncio.Event()
                self.submitted = []; self.prompts = []
            async def stream(self, text):
                self.prompts.append(text)
                await self.finish.wait()
                yield 'Done'
            async def steer(self, text):
                self.submitted.append(text)
                await self.ack.wait()
                return SteerResult.ACCEPTED
        e=Engine(); flow=InboundFlow(Bot(), e, debounce=0.005)
        flow.submit(1, 'first'); await asyncio.sleep(0)
        flow.submit(1, 'second'); await asyncio.sleep(0.015)
        flow.submit(1, 'third'); await asyncio.sleep(0.015)
        e.ack.set(); await asyncio.sleep(0.015)
        e.finish.set(); await flow.wait()
        assert e.submitted == ['second', 'third']
        assert e.prompts == ['first']
    asyncio.run(run())


def test_input_at_turn_end_waits_for_ack_before_fifo_fallback():
    async def run():
        from capri.app import InboundFlow
        from test_telegram import Bot
        class Engine:
            def __init__(self):
                self.finish=asyncio.Event(); self.ack=asyncio.Event()
                self.prompts=[]; self.steers=[]
            async def stream(self, text):
                self.prompts.append(text)
                if text == 'first': await self.finish.wait()
                yield text
            async def steer(self, text):
                self.steers.append(text); await self.ack.wait(); return SteerResult.ACCEPTED
        e=Engine(); flow=InboundFlow(Bot(), e, debounce=0.005)
        flow.submit(1,'first'); await asyncio.sleep(0)
        flow.submit(1,'second'); await asyncio.sleep(0.015)
        flow.submit(1,'third'); e.finish.set(); await asyncio.sleep(0.01)
        assert e.prompts == ['first']
        e.ack.set(); await flow.wait()
        assert e.prompts == ['first','third'] and e.steers == ['second']
    asyncio.run(run())


def test_turn_end_during_delivery_preserves_fifo_and_future_steering(tmp_path):
    import threading
    from capri.app import InboundFlow
    from capri.engine import Engine
    from test_engine import SDK
    from test_telegram import Bot

    class ActiveSDK(SDK):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.active = threading.Event()
            self.finish = threading.Event()
            self.steers = []

        def prompt_and_wait(self, message, **kw):
            if 'second' in message:
                self.active.set()
                assert self.finish.wait(2)
            return super().prompt_and_wait(message, **kw)

        def steer(self, message):
            self.steers.append(message)
            self.finish.set()

    class DeliveryBot(Bot):
        def __init__(self):
            super().__init__()
            self.delivering = asyncio.Event()
            self.release = asyncio.Event()

        async def send_message(self, **kw):
            if not self.messages:
                self.delivering.set()
                await self.release.wait()
            return await super().send_message(**kw)

    async def run():
        engine = Engine(tmp_path / 'omp.exe', tmp_path, sdk_factory=ActiveSDK)
        await engine.start()
        bot = DeliveryBot()
        flow = InboundFlow(bot, engine, debounce=0)
        attempted = asyncio.Event()
        steer = engine.steer

        async def observe(text):
            result = await steer(text)
            attempted.set()
            return result

        engine.steer = observe
        try:
            flow.submit(1, 'first')
            await asyncio.wait_for(bot.delivering.wait(), 1)
            assert flow.responding and not engine._active
            flow.submit(1, 'second')
            flow.submit(1, 'third')
            await asyncio.wait_for(attempted.wait(), 1)
            assert flow.steer_available
            assert list(flow.pending) == [(1, 'second'), (1, 'third')]
            bot.release.set()
            assert await asyncio.to_thread(engine.client.active.wait, 1)
            attempted.clear()
            flow.submit(1, 'fourth')
            await asyncio.wait_for(attempted.wait(), 1)
            await asyncio.wait_for(flow.wait(), 1)
            import json
            assert len(engine.client.messages) == 2
            assert 'second' in engine.client.messages[1]
            assert [json.loads(message.split('\n', 1)[1])['text']
                    for message in engine.client.steers] == ['third\n\nfourth']
        finally:
            bot.release.set()
            engine.client.finish.set()
            await flow.stop()
            await engine.close()

    asyncio.run(run())


def test_stop_cancels_blocked_steer_and_drops_pending_input(tmp_path):
    import threading
    from capri.app import InboundFlow
    from capri.engine import Engine
    from test_engine import SDK
    from test_telegram import Bot

    class BlockedSDK(SDK):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.active = threading.Event()
            self.steering = threading.Event()
            self.ack = threading.Event()
            self.aborted = threading.Event()
            self.steer_done = threading.Event()

        def prompt_and_wait(self, message, **kw):
            if not self.messages:
                self.messages.append(message)
                self.active.set()
                assert self.aborted.wait(2)
                return NS(result=NS(status='aborted'))
            return super().prompt_and_wait(message, **kw)

        def steer(self, message):
            self.steering.set()
            try:
                assert self.ack.wait(2)
            finally:
                self.steer_done.set()

        def abort(self):
            self.aborted.set()

    async def run():
        engine = Engine(tmp_path / 'omp.exe', tmp_path, sdk_factory=BlockedSDK)
        await engine.start()
        bot = Bot()
        flow = InboundFlow(bot, engine, debounce=0)
        try:
            flow.submit(1, 'first')
            assert await asyncio.to_thread(engine.client.active.wait, 1)
            flow.submit(1, 'clarification')
            assert await asyncio.to_thread(engine.client.steering.wait, 1)
            burst = flow.burst
            flow.submit(1, 'queued clarification')
            stop_task = asyncio.create_task(flow.stop())
            done, _ = await asyncio.wait({stop_task}, timeout=0.5)
            assert stop_task in done, '/stop waited for the blocked steer ACK'
            await stop_task
            assert engine.client.aborted.is_set()
            assert not engine.client.ack.is_set()
            assert burst.done() and flow.worker.done()
            assert not flow.pending and not flow.responding and not flow.submitting
            assert not engine._failed and not engine.client.stopped
            engine.client.ack.set()
            assert await asyncio.to_thread(engine.client.steer_done.wait, 1)
            flow.submit(1, 'fresh')
            await asyncio.wait_for(flow.wait(), 1)
            assert len(engine.client.messages) == 2
            assert 'fresh' in engine.client.messages[1]
            assert [m['text'] for m in bot.messages] == ['Hello owner']
        finally:
            engine.client.ack.set()
            engine.client.aborted.set()
            await flow.stop()
            await engine.close()

    asyncio.run(run())
