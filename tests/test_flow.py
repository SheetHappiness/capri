import asyncio
from types import SimpleNamespace as NS

from capri.app import handle_text
from capri.config import Pairing


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
                self.steers.append(text); return True
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
            async def steer(self, text): return False
        engine = Engine(); bot = Bot(); flow = InboundFlow(bot, engine, debounce=0.01)
        flow.submit(1, 'first'); await asyncio.sleep(0)
        flow.submit(1, 'second'); flow.submit(1, 'third')
        await asyncio.sleep(0.02)
        engine.finish.set(); await flow.wait()
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
                return True
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
                self.steers.append(text); await self.ack.wait(); return True
        e=Engine(); flow=InboundFlow(Bot(), e, debounce=0.005)
        flow.submit(1,'first'); await asyncio.sleep(0)
        flow.submit(1,'second'); await asyncio.sleep(0.015)
        flow.submit(1,'third'); e.finish.set(); await asyncio.sleep(0.01)
        assert e.prompts == ['first']
        e.ack.set(); await flow.wait()
        assert e.prompts == ['first','third'] and e.steers == ['second']
    asyncio.run(run())
