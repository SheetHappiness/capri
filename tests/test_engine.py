import asyncio
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from capri.engine import Engine, EngineError, SteerResult


@pytest.mark.parametrize('activity', ['model', 'tool'])
def test_steer_during_active_run_does_not_wait_for_prompt_lock(tmp_path, activity):
    import threading
    class ActiveSDK(SDK):
        def __init__(self, **kw):
            super().__init__(**kw); self.ready=threading.Event(); self.finish=threading.Event(); self.steers=[]
        def prompt_and_wait(self, message, **kw):
            kind = 'text_delta' if activity == 'model' else 'toolcall_delta'
            self.callback(NS(message={'role':'assistant'},
                assistant_message_event={'type':kind,'delta':'Working. '}))
            self.ready.set()
            assert self.finish.wait(2)
            return super().prompt_and_wait(message, **kw)
        def steer(self, message):
            self.steers.append(message); self.finish.set()
    async def run():
        e=Engine(tmp_path/'omp.exe',tmp_path,sdk_factory=ActiveSDK); await e.start()
        async def consume(): return [part async for part in e.stream(activity)]
        task=asyncio.create_task(consume())
        await asyncio.to_thread(e.client.ready.wait, 1)
        assert await asyncio.wait_for(e.steer('clarification'), 1) is SteerResult.ACCEPTED
        assert await task == (['Working. '] if activity == 'model' else []) + ['Hello ', 'owner']
        assert len(e.client.messages)==1 and 'clarification' in e.client.steers[0]
        await e.close()
    asyncio.run(run())


def test_missing_sdk_steer_is_safe(tmp_path):
    async def run():
        e=Engine(tmp_path/'omp.exe',tmp_path,sdk_factory=SDK); await e.start()
        e._active = True
        assert await e.steer('later') is SteerResult.UNSUPPORTED
        e._active = False
        assert not e.client.messages and not e.client.stopped
        await e.close()
    asyncio.run(run())


def test_explicit_abort_keeps_session_usable(tmp_path):
    import threading
    class AbortSDK(SDK):
        def __init__(self, **kw):
            super().__init__(**kw); self.ready=threading.Event(); self.done=threading.Event()
        def prompt_and_wait(self, message, **kw):
            if not self.messages:
                self.messages.append(message); self.ready.set(); self.done.wait(2)
                return NS(result=NS(status='aborted'))
            return super().prompt_and_wait(message, **kw)
        def abort(self): self.done.set()
    async def run():
        e=Engine(tmp_path/'omp.exe',tmp_path,sdk_factory=AbortSDK); await e.start()
        async def consume(): return [x async for x in e.stream('first')]
        task=asyncio.create_task(consume()); await asyncio.to_thread(e.client.ready.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert [x async for x in e.stream('second')] == ['Hello ', 'owner']
        assert not e.client.stopped
        await e.close()
    asyncio.run(run())

class SDK:
    def __init__(self, **kw):
        self.kw=kw; self.stopped=False; self.messages=[]; self.fail=False
    def start(self): return self
    def on_message_update(self, callback): self.callback=callback
    def get_state(self):
        return NS(model=NS(provider='openai-codex',id='gpt-6-luna'),dump_tools=(NS(name='web_search'),),session_file=str(Path(self.kw['session_dir'])/'owner.jsonl'))
    def set_model(self, provider, model_id): return self.get_state().model
    def get_available_models(self): return (self.get_state().model,)
    def prompt_and_wait(self, message, **kw):
        self.messages.append(message)
        if self.fail: raise RuntimeError('private secret SDK stderr')
        for kind,delta in [('thinking_delta','private thought'),('text_delta','Hello '),('toolcall_delta','private args'),('text_delta','owner')]:
            self.callback(NS(message={'role':'assistant'},assistant_message_event={'type':kind,'delta':delta}))
        return NS(result=NS(status='completed',error=None))
    def abort(self): pass
    def stop(self): self.stopped=True; return True


def test_owner_unconfirmed_close_blocks_restart(tmp_path):
    class Unsafe(SDK):
        def stop(self): return False
    async def run():
        e=Engine(tmp_path/'omp.exe',tmp_path,sdk_factory=Unsafe)
        await e.start()
        await e.close()
        with pytest.raises(EngineError): await e.start()
    asyncio.run(run())

def test_public_stream_and_literal_input(tmp_path):
    async def run():
        e=Engine(tmp_path/'omp.exe',tmp_path,sdk_factory=SDK)
        await e.start()
        assert [x async for x in e.stream('/login dangerous')]==['Hello ','owner']
        assert e.client.messages[0].startswith('Capri input JSON:\n')
        assert '/login dangerous' in e.client.messages[0]
        await e.close(); assert e.client.stopped
    asyncio.run(run())

def test_private_errors_not_exposed(tmp_path):
    async def run():
        e=Engine(tmp_path/'omp.exe',tmp_path,sdk_factory=SDK); await e.start(); e.client.fail=True
        with pytest.raises(EngineError,match='OMP') as err:
            _=[x async for x in e.stream('hi')]
        assert 'secret' not in str(err.value)
        await e.close()
    asyncio.run(run())

def test_no_silent_fallback_or_extra_tools(tmp_path):
    class Wrong(SDK):
        def get_state(self):
            s=super().get_state(); s.model.id='other'; return s
    class Unsafe(SDK):
        def get_state(self):
            s=super().get_state(); s.dump_tools+=(NS(name='bash'),); return s
    async def run(factory):
        e=Engine(tmp_path/'omp.exe',tmp_path,sdk_factory=factory)
        with pytest.raises(EngineError): await e.start()
        assert e.client.stopped
    for f in (Wrong,Unsafe): asyncio.run(run(f))

def test_session_pointer_reused(tmp_path):
    async def run():
        e=Engine(tmp_path/'omp.exe',tmp_path,sdk_factory=SDK); await e.start()
        session=Path(e.client.get_state().session_file); session.touch(); await e.close()
        e2=Engine(tmp_path/'omp.exe',tmp_path,sdk_factory=SDK); await e2.start()
        assert '--resume' in e2.client.kw['extra_args']
        assert str(session) in e2.client.kw['extra_args']; await e2.close()
    asyncio.run(run())

def test_failed_turn_stops_process_before_next_request(tmp_path):
    async def run():
        e=Engine(tmp_path/'omp.exe',tmp_path,sdk_factory=SDK)
        await e.start(); e.client.fail=True
        with pytest.raises(EngineError):
            _=[part async for part in e.stream('first')]
        assert e.client.stopped
        e.client.fail=False
        with pytest.raises(EngineError):
            _=[part async for part in e.stream('second')]
        assert len(e.client.messages)==1
    asyncio.run(run())

def test_profile_environment_cannot_override_private_storage(tmp_path):
    async def run():
        e=Engine(tmp_path/'omp.exe',tmp_path,sdk_factory=SDK); await e.start()
        assert e.client.kw['env']['OMP_PROFILE']==''
        assert e.client.kw['env']['PI_PROFILE']==''
        await e.close()
    asyncio.run(run())


def test_start_appends_conversation_prompt_on_resume(tmp_path):
    async def run():
        e = Engine(tmp_path/'omp.exe', tmp_path, sdk_factory=SDK)
        await e.start()
        # Verify the SDK boundary, including persistence and capability isolation.
        assert e.client.kw.get('append_system_prompt')
        from capri.prompt import CAPRI_CONVERSATION_PROMPT
        assert e.client.kw['append_system_prompt'] == CAPRI_CONVERSATION_PROMPT
        session = Path(e.client.get_state().session_file)
        session.touch()
        await e.close()
        resumed = Engine(tmp_path/'omp.exe', tmp_path, sdk_factory=SDK)
        await resumed.start()
        kw = resumed.client.kw
        assert kw['append_system_prompt'] == CAPRI_CONVERSATION_PROMPT
        assert kw['extra_args'] == ['--no-extensions', '--no-lsp', '--no-pty', '--resume', str(session)]
        assert (kw['provider'], kw['model'], kw['thinking']) == ('openai-codex', 'gpt-6-luna', 'low')
        assert kw['tools'] == ('web_search',)
        assert all(kw[key] for key in ('no_skills', 'no_rules', 'no_title', 'no_ui'))
        assert 'system_prompt' not in kw
        await resumed.close()
    asyncio.run(run())


def test_steer_result_distinguishes_inactive_from_unsupported(tmp_path):
    async def run():
        from capri.engine import SteerResult
        e = Engine(tmp_path / 'omp.exe', tmp_path, sdk_factory=SDK)
        await e.start()
        try:
            assert await e.steer('inactive') is SteerResult.NOT_ACTIVE
            e._active = True
            assert await e.steer('unsupported') is SteerResult.UNSUPPORTED
        finally:
            e._active = False
            await e.close()
    asyncio.run(run())


def test_steer_explicit_unsupported_and_uncertain_ack(tmp_path):
    from omp_rpc import RpcError

    class SteeringSDK(SDK):
        error = None

        def steer(self, message):
            raise self.error

    async def run():
        from capri.engine import SteerResult
        e = Engine(tmp_path / 'omp.exe', tmp_path, sdk_factory=SteeringSDK)
        await e.start()
        e._active = True
        try:
            for message in ('unknown command: steer', 'steer not supported'):
                e.client.error = RpcError(message)
                assert await e.steer('input') is SteerResult.UNSUPPORTED
            e.client.error = RuntimeError('lost ACK')
            with pytest.raises(EngineError, match='uncertain'):
                await e.steer('input')
        finally:
            e._active = False
            await e.close()
    asyncio.run(run())
