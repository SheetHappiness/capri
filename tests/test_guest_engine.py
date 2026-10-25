import asyncio
import json
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from capri.guest_engine import GuestEngine
from capri.engine import EngineError
from test_engine import SDK


class GuestSDK(SDK):
    instances = []
    wrong = None

    def __init__(self, **kw):
        super().__init__(**kw); self.instances.append(self)

    def on_message_start(self, cb): self.start_cb=cb
    def on_message_end(self, cb): self.end_cb=cb
    def on_tool_execution_start(self, cb): self.tool_cb=cb
    def on_tool_execution_end(self, cb): self.tool_end_cb=cb

    def open_session(self, directory):
        self.directory = Path(directory)
        path = self.directory/'guest.jsonl'
        self.resumed = path.exists()
        return NS(resumed=self.resumed)

    def get_state(self):
        s = super().get_state()
        s.session_file = str(self.directory/'guest.jsonl')
        if self.wrong == 'model': s.model.id = 'other'
        if self.wrong == 'tools': s.dump_tools += (NS(name='bash'),)
        if self.wrong == 'path': s.session_file = str(self.directory.parent/'escaped.jsonl')
        return s

    def get_available_models(self):
        return (NS(provider='openai-codex', id='gpt-6-luna'),)

    def set_model(self, *args): pass

    def prompt_and_wait(self, message, **kw):
        if self.wrong == 'prompt': raise RuntimeError('secret')
        (self.directory/'guest.jsonl').write_text(message)
        self.start_cb(NS(message={'role':'assistant'}))
        turn = super().prompt_and_wait(message, **kw)
        msg={'role':'assistant','content':[{'type':'text','text':'Hello owner'}],'stopReason':'stop'}
        self.end_cb(NS(message=msg))
        turn.assistant_message=msg; turn.assistant_text='Hello owner'
        return turn


@pytest.mark.parametrize('outcome',[False,None,'raise'])
def test_guest_unconfirmed_stop_blocks_next_child(tmp_path,outcome):
    class Unsafe(GuestSDK):
        def stop(self):
            if outcome=='raise': raise OSError('PRIVATE')
            return outcome
    async def run():
        e=GuestEngine(tmp_path/'omp.exe',tmp_path,sdk_factory=Unsafe)
        directory=tmp_path/'guest/sessions/1'/('f'*12)
        for _ in range(2):
            with pytest.raises(EngineError):
                _=[x async for x in e.stream(directory,text='hi',reference_text=None)]
        assert not e.safe
    asyncio.run(run())


def test_guest_resume_isolation_and_public_text(tmp_path):
    async def run():
        owner = tmp_path/'session.json'; owner.write_text('private pointer')
        transcript = tmp_path/'agent/sessions/owner.jsonl'
        transcript.parent.mkdir(parents=True); transcript.write_text('private transcript')
        before = [(p.read_bytes(),p.stat().st_mtime_ns) for p in (owner,transcript)]
        engine = GuestEngine(tmp_path/'omp.exe',tmp_path,sdk_factory=GuestSDK)
        for thread, resumed in [('a'*12,False),('a'*12,True),('b'*12,False)]:
            directory = tmp_path/'guest/sessions/17'/thread
            parts = [x async for x in engine.stream(directory,text='hello',reference_text='quoted secret')]
            assert [(x.kind,x.text) for x in parts] == [('start',''),('text','Hello '),('text','owner'),('message','Hello owner'),('final','Hello owner')]
            sdk = GuestSDK.instances[-1]
            assert sdk.resumed is resumed and sdk.stopped
            assert '--resume' not in sdk.kw['extra_args'] and not sdk.kw.get('no_session')
            assert sdk.kw['session_dir'] == directory.resolve()
            assert sdk.kw['tools'] == ('web_search',)
            assert sdk.kw['no_ui'] is True
            payload = json.loads(sdk.messages[0].split('\n',1)[1])
            assert payload == {'text':'hello','reference':{'text':'quoted secret'}}
        assert before == [(p.read_bytes(),p.stat().st_mtime_ns) for p in (owner,transcript)]
    asyncio.run(run())


@pytest.mark.parametrize('wrong',['model','tools','path','prompt'])
def test_guest_fails_closed_and_stops(tmp_path,wrong):
    class Wrong(GuestSDK): pass
    Wrong.wrong=wrong
    async def run():
        engine=GuestEngine(tmp_path/'omp.exe',tmp_path,sdk_factory=Wrong)
        with pytest.raises(EngineError) as exc:
            _=[x async for x in engine.stream(tmp_path/'guest/sessions/1'/('c'*12),text='hi',reference_text=None)]
        assert 'secret' not in str(exc.value)
        assert GuestSDK.instances[-1].stopped
    asyncio.run(run())


def test_cancel_joins_sync_prompt_and_stops(tmp_path):
    import threading
    class Blocked(GuestSDK):
        def __init__(self,**kw):
            super().__init__(**kw); self.ready=threading.Event(); self.done=threading.Event()
        def prompt_and_wait(self,*args,**kw):
            self.ready.set(); self.done.wait(3); raise RuntimeError('stopped')
        def stop(self): self.done.set(); return super().stop()
    async def run():
        engine=GuestEngine(tmp_path/'omp.exe',tmp_path,sdk_factory=Blocked)
        async def consume():
            return [x async for x in engine.stream(tmp_path/'guest/sessions/1'/('c'*12),text='hi',reference_text=None)]
        task=asyncio.create_task(consume())
        while not GuestSDK.instances or not isinstance(GuestSDK.instances[-1],Blocked): await asyncio.sleep(0)
        sdk=GuestSDK.instances[-1]
        assert await asyncio.to_thread(sdk.ready.wait,2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert sdk.stopped and sdk.done.is_set()
    asyncio.run(run())


def test_reject_owner_or_unvalidated_directory_before_child(tmp_path):
    async def run():
        engine=GuestEngine(tmp_path/'omp.exe',tmp_path,sdk_factory=lambda **kw: pytest.fail('spawn'))
        for directory in [tmp_path/'agent/sessions',tmp_path/'guest/sessions/../escape']:
            with pytest.raises(EngineError):
                _=[x async for x in engine.stream(directory,text='hi',reference_text=None)]
    asyncio.run(run())


def test_early_close_never_calls_stop_concurrently(tmp_path):
    import threading
    import time
    class SlowStop(GuestSDK):
        stopping=threading.Lock()
        overlap=False
        def stop(self):
            if not self.stopping.acquire(blocking=False):
                self.overlap=True
                return False
            try:
                time.sleep(0.02)
                return super().stop()
            finally: self.stopping.release()
    async def run():
        engine=GuestEngine(tmp_path/'omp.exe',tmp_path,sdk_factory=SlowStop)
        stream=engine.stream(tmp_path/'guest/sessions/1'/('c'*12),text='hi',reference_text=None)
        assert (await anext(stream)).kind=='start'
        await stream.aclose()
        assert not GuestSDK.instances[-1].overlap
    asyncio.run(run())


def test_native_lifecycle_keeps_final_separate_from_interim(tmp_path):
    class Lifecycle(GuestSDK):
        def on_message_start(self, cb): self.start_cb=cb
        def on_message_end(self, cb): self.end_cb=cb
        def on_tool_execution_start(self, cb): self.tool_cb=cb
        def on_tool_execution_end(self, cb): self.tool_end_cb=cb
        def prompt_and_wait(self,*a,**kw):
            for text,tool in [('Checking',True),('Found issue',True),('Final answer',False)]:
                self.start_cb(NS(message={'role':'assistant'}))
                self.callback(NS(message={'role':'assistant'},assistant_message_event={'type':'thinking_delta','delta':'PRIVATE'}))
                self.callback(NS(message={'role':'assistant'},assistant_message_event={'type':'text_delta','delta':text}))
                msg={'role':'assistant','content':[{'type':'text','text':text}], 'stopReason':'toolUse' if tool else 'stop'}
                self.end_cb(NS(message=msg))
                if tool:
                    self.tool_cb(NS(tool_name='web_search',args={'PRIVATE':'SECRET'}))
                    self.tool_end_cb(NS(tool_name='web_search',result={'SECRET':'PRIVATE'}))
            return NS(result=NS(status='completed'),assistant_message=msg,assistant_text='Final answer')
    async def run():
        e=GuestEngine(tmp_path/'omp.exe',tmp_path,sdk_factory=Lifecycle)
        parts=[x async for x in e.stream(tmp_path/'guest/sessions/1'/('d'*12),text='hi',reference_text=None)]
        assert [(x.kind,x.text) for x in parts]==[
            ('start',''),('text','Checking'),('message','Checking'),('tool_start',''),('tool_end',''),
            ('start',''),('text','Found issue'),('message','Found issue'),('tool_start',''),('tool_end',''),
            ('start',''),('text','Final answer'),('message','Final answer'),('final','Final answer')]
    asyncio.run(run())


@pytest.mark.parametrize('reason,want',[('length','Partial answer'),('toolUse','')])
def test_completed_length_keeps_text_but_tool_tail_is_not_final(tmp_path,reason,want):
    class Ending(GuestSDK):
        def prompt_and_wait(self,*a,**kw):
            msg={'role':'assistant','content':[{'type':'text','text':'Partial answer'}],'stopReason':reason}
            return NS(result=NS(status='completed'),assistant_message=msg,assistant_text='Partial answer')
    async def run():
        engine=GuestEngine(tmp_path/'omp.exe',tmp_path,sdk_factory=Ending)
        parts=[x async for x in engine.stream(tmp_path/'guest/sessions/1'/('e'*12),text='hi',reference_text=None)]
        assert [(e.kind,e.text) for e in parts]==[('final',want)]
    asyncio.run(run())



def test_repeated_cancel_still_joins_guest_worker(tmp_path):
    import threading
    class Blocked(GuestSDK):
        def __init__(self,**kw):
            super().__init__(**kw)
            self.ready=threading.Event(); self.stopping=threading.Event()
            self.release=threading.Event(); self.done=threading.Event()
        def prompt_and_wait(self,*a,**kw):
            self.ready.set(); self.done.wait(3); raise RuntimeError('stopped')
        def stop(self):
            self.stopping.set(); self.release.wait(3); self.done.set()
            return super().stop()
    async def run():
        e=GuestEngine(tmp_path/'omp.exe',tmp_path,sdk_factory=Blocked)
        async def consume():
            return [x async for x in e.stream(tmp_path/'guest/sessions/1'/('f'*12),text='hi',reference_text=None)]
        task=asyncio.create_task(consume())
        while not GuestSDK.instances or not isinstance(GuestSDK.instances[-1],Blocked): await asyncio.sleep(0)
        sdk=GuestSDK.instances[-1]
        assert await asyncio.to_thread(sdk.ready.wait,1)
        task.cancel()
        assert await asyncio.to_thread(sdk.stopping.wait,1)
        task.cancel(); await asyncio.sleep(0.01)
        try: assert not task.done(), 'cancellation abandoned live child cleanup'
        finally: sdk.release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert sdk.done.is_set() and sdk.stopped
    asyncio.run(run())
