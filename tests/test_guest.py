import asyncio
from types import SimpleNamespace as NS
import pytest
from aiogram import Bot
from aiogram.methods import AnswerGuestQuery, EditMessageText
from aiogram.exceptions import TelegramNetworkError
from aiogram.types import SentGuestMessage
from capri.guest import GuestService
from capri.guest_engine import GuestEvent
from capri.guest_threads import GuestThreadStore
from test_guest_probe import message


class Transport(Bot):
    def __init__(self):
        super().__init__('123:TEST'); self.calls=[]; self.fail_answer=False; self.fail_edit=False
    async def __call__(self,method,**kw):
        assert isinstance(method,(AnswerGuestQuery,EditMessageText)), 'no ordinary messages'
        self.calls.append(method)
        if ((isinstance(method,AnswerGuestQuery) and self.fail_answer)
                or (isinstance(method,EditMessageText) and self.fail_edit)):
            raise TelegramNetworkError(method=method,message='PRIVATE SECRET')
        return SentGuestMessage(inline_message_id='inline-1') if isinstance(method,AnswerGuestQuery) else True


class Runtime:
    def __init__(self):
        self.calls=[]; self.parts=['Hello<bu','bble>world']; self.wait=None; self.entered=asyncio.Event(); self.closed=False
    async def stream_guest(self,directory,**kw):
        self.calls.append((directory,kw)); self.entered.set()
        try:
            if self.wait: await self.wait.wait()
            yield GuestEvent('start')
            for part in self.parts: yield GuestEvent('text',part)
            yield GuestEvent('final',''.join(self.parts))
        finally: self.closed=True


def setup(tmp_path):
    bot=Transport(); runtime=Runtime(); store=GuestThreadStore(tmp_path)
    service=GuestService(bot,lambda:7,'Capriompbot',store,runtime,interval=0.001, startup_delay=1)
    return bot,runtime,store,service


def test_owner_delivery_context_strip_and_dedupe(tmp_path):
    async def run():
        bot,runtime,store,service=setup(tmp_path)
        try:
            msg=message(text='@CAPRIOMPBOT hello',reply_to_message=message(text='quoted DATA',guest_query_id=None))
            await service.handle(msg); await service.handle(msg)
            assert len(runtime.calls)==1
            assert runtime.calls[0][1]=={'text':'hello','reference_text':'quoted DATA'}
            assert len([c for c in bot.calls if isinstance(c,AnswerGuestQuery)])==1
            edits=[c for c in bot.calls if isinstance(c,EditMessageText)]
            assert edits[-1].text=='Hello\n\nworld'
            assert all(c.inline_message_id=='inline-1' and c.chat_id is None for c in edits)
            assert store.current(7) is not None and runtime.closed
        finally: await bot.session.close()
    asyncio.run(run())


@pytest.mark.parametrize('changes',[
    {'from_user':None},{'from_user':{'id':8,'is_bot':False,'first_name':'Other'}},
    {'from_user':{'id':7,'is_bot':True,'first_name':'Bot'}},
    {'sender_chat':{'id':7,'type':'channel','title':'Anon'}},{'guest_query_id':None}])
def test_rejected_queries_do_not_touch_store_or_runtime(tmp_path,changes):
    async def run():
        bot,runtime,store,service=setup(tmp_path)
        try:
            await service.handle(message(**changes))
            assert not runtime.calls and not bot.calls and store.current(7) is None
            assert not store.path.exists()
        finally: await bot.session.close()
    asyncio.run(run())


def test_local_commands_scoped_and_never_call_luna(tmp_path):
    async def run():
        bot,runtime,store,service=setup(tmp_path)
        async def command(n,text,chat=7):
            await service.handle(message(text='@Capriompbot '+text,guest_query_id=str(n),chat={'id':chat,'type':'private'}))
            return bot.calls[-1].result.input_message_content.message_text
        try:
            assert 'Немає' in await command(1,'/status')
            await command(2,'/newthread Laptop'); first=store.current(7)
            await command(3,'/new Camera'); second=store.current(7)
            assert first.id!=second.id
            listing=await command(4,'/threads')
            assert listing.index(second.id)<listing.index(first.id)
            assert first.id not in await command(5,'/threads',8)
            await command(6,'/resume '+first.id[:8]); assert store.current(7).id==first.id
            await command(7,'/title ThinkPad'); assert store.current(7).title=='ThinkPad'
            assert 'ThinkPad' in await command(8,'/status')
            assert first.id in await command(9,'/resume')
            assert not runtime.calls
        finally: await bot.session.close()
    asyncio.run(run())


def test_busy_rejects_second_turn_and_mutations_but_lists(tmp_path):
    async def run():
        bot,runtime,store,service=setup(tmp_path); runtime.wait=asyncio.Event()
        task=asyncio.create_task(service.handle(message()))
        try:
            await runtime.entered.wait(); first=store.current(7)
            for i,text in enumerate(['hello','/newthread','/resume foo','/title foo','/threads','/status'],2):
                await service.handle(message(text=text,guest_query_id=str(i)))
            assert len(runtime.calls)==1 and store.current(7)==first
            assert len([c for c in bot.calls if isinstance(c,AnswerGuestQuery)])==6
        finally:
            runtime.wait.set(); await task; await bot.session.close()
    asyncio.run(run())


@pytest.mark.parametrize('kind',['huge','empty','error','timeout','answer_failure','edit_failure','cancel'])
def test_delivery_limits_errors_cleanup(tmp_path,kind):
    async def run():
        bot,runtime,store,service=setup(tmp_path)
        if kind=='huge': runtime.parts=['🙂'*3000+'<bubble>']
        if kind=='empty': runtime.parts=[]
        if kind=='answer_failure': bot.fail_answer=True
        if kind=='edit_failure': bot.fail_edit=True
        if kind=='error':
            async def fail(*a,**kw):
                raise RuntimeError('PRIVATE SECRET')
                yield
            runtime.stream_guest=fail
        if kind in ('cancel','timeout'): runtime.wait=asyncio.Event()
        if kind=='timeout': service.timeout=0.01
        try:
            if kind=='cancel':
                task=asyncio.create_task(service.handle(message()))
                await runtime.entered.wait(); task.cancel()
                with pytest.raises(asyncio.CancelledError): await task
                assert runtime.closed
            else: await service.handle(message())
            assert not service.busy
            answers=[c for c in bot.calls if isinstance(c,AnswerGuestQuery)]
            if kind=='cancel': assert len(answers)<=1  # cancellation can race the first dot
            else: assert len(answers)==1
            edits=[c for c in bot.calls if isinstance(c,EditMessageText)]
            if kind=='answer_failure': assert not edits and runtime.closed
            elif kind!='cancel':
                final=edits[-1].text if edits else answers[-1].result.input_message_content.message_text
                assert len(final.encode('utf-16-le'))//2<=4096 and 'PRIVATE' not in final
                if kind=='huge': assert 'скорочено' in final
                if kind in ('error','timeout'): assert 'помилка' in final
        finally: await bot.session.close()
    asyncio.run(run())


@pytest.mark.parametrize('reference,want',[
    (message(text=None,caption='caption DATA'),'caption DATA'),
    (message(text=None,caption=None),None),(None,None)])
def test_caption_and_unsupported_reference(tmp_path,reference,want):
    async def run():
        bot,runtime,store,service=setup(tmp_path)
        try:
            await service.handle(message(reply_to_message=reference))
            assert runtime.calls[0][1]['reference_text']==want
        finally: await bot.session.close()
    asyncio.run(run())


def test_unexpected_answer_failure_is_never_retried(tmp_path):
    async def run():
        bot,runtime,store,service=setup(tmp_path)
        attempts=[]
        async def uncertain(**kw):
            attempts.append(kw); raise RuntimeError('unknown transport outcome')
        bot.answer_guest_query=uncertain
        try:
            await service.handle(message())
            assert len(attempts)==1 and runtime.closed and not service.busy
        finally: await bot.session.close()
    asyncio.run(run())
