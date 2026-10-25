import asyncio
import pytest
from aiogram.methods import AnswerGuestQuery, EditMessageText
from capri.guest_engine import GuestEvent as E
from test_guest import setup
from test_guest_probe import message


def test_interim_replaced_by_final_and_no_fixed_placeholder(tmp_path):
    async def run():
        bot,runtime,store,service=setup(tmp_path)
        service.interval=0.01; service.startup_delay=1
        async def stream(*a,**kw):
            try:
                yield E('start'); yield E('text','Checking<bu'); yield E('text','bble>sources')
                yield E('message','Checking<bubble>sources'); yield E('tool_start')
                await asyncio.sleep(0.025)
                yield E('tool_end'); yield E('start'); yield E('text','Found issue')
                yield E('message','Found issue'); yield E('tool_start')
                await asyncio.sleep(0.025)
                yield E('tool_end'); yield E('start'); yield E('text','Partial final')
                yield E('message','Complete final<bubble>answer')
                yield E('final','Complete final<bubble>answer')
            finally: runtime.closed=True
        runtime.stream_guest=stream
        try:
            await service.handle(message())
            answers=[c for c in bot.calls if isinstance(c,AnswerGuestQuery)]
            edits=[c for c in bot.calls if isinstance(c,EditMessageText)]
            assert len(answers)==1
            first=answers[0].result.input_message_content.message_text
            assert 'Checking' in first and 'Думаю' not in first
            assert any('Checking' in c.text and 'Found issue' in c.text for c in edits)
            assert edits[-1].text=='Complete final\n\nanswer'
            assert all('<bubble>' not in c.text for c in edits)
            assert runtime.closed and not service.busy
        finally: await bot.session.close()
    asyncio.run(run())


def test_silent_tools_animate_without_cancelling_read_and_final_is_paced(tmp_path):
    async def run():
        bot,runtime,store,service=setup(tmp_path)
        service.interval=0.02; service.startup_delay=0.01
        cancelled=[]; stamps=[]; animated=asyncio.Event()
        # Record outbound start times at the real service transport boundary.
        async def answer(**kw):
            stamps.append(asyncio.get_running_loop().time())
            from types import SimpleNamespace
            bot.calls.append(AnswerGuestQuery(**kw)); return SimpleNamespace(inline_message_id='inline-1')
        async def edit(**kw):
            stamps.append(asyncio.get_running_loop().time()); bot.calls.append(EditMessageText(**kw))
            if len(stamps)>=4: animated.set()
        bot.answer_guest_query=answer; bot.edit_message_text=edit
        async def stream(*a,**kw):
            try:
                yield E('tool_start')
                await asyncio.wait_for(animated.wait(),1)
                yield E('tool_end'); yield E('final','Done')
            except asyncio.CancelledError: cancelled.append(True); raise
            finally: runtime.closed=True
        runtime.stream_guest=stream
        try:
            await service.handle(message())
            assert bot.calls[0].result.input_message_content.message_text=='·'
            texts=[c.text for c in bot.calls if isinstance(c,EditMessageText)]
            assert texts[:3]==['··','···','··']
            assert texts[-1]=='Done' and not cancelled and runtime.closed
            assert all(b-a>=0.018 for a,b in zip(stamps,stamps[1:]))
            count=len(bot.calls); await asyncio.sleep(0.04); assert len(bot.calls)==count
        finally: await bot.session.close()
    asyncio.run(run())


@pytest.mark.parametrize('failure',['error','timeout','cancel','answer_failure'])
def test_pending_read_and_timer_closed_on_failure(tmp_path,failure):
    async def run():
        bot,runtime,store,service=setup(tmp_path)
        service.interval=0.01; service.startup_delay=0.005
        entered=asyncio.Event(); release=asyncio.Event()
        async def stream(*a,**kw):
            try:
                entered.set()
                if failure=='error': raise RuntimeError('PRIVATE')
                await release.wait()
                yield E('final','Done')
            finally: runtime.closed=True
        runtime.stream_guest=stream
        if failure=='timeout': service.timeout=0.025
        if failure=='answer_failure': bot.fail_answer=True
        try:
            task=asyncio.create_task(service.handle(message()))
            await entered.wait()
            if failure=='cancel':
                await asyncio.sleep(0.015); task.cancel()
                with pytest.raises(asyncio.CancelledError): await task
            else: await task
            assert runtime.closed and not service.busy
            answers=[c for c in bot.calls if isinstance(c,AnswerGuestQuery)]
            assert len(answers)==1
            if failure=='answer_failure': assert len(bot.calls)==1
            assert 'PRIVATE' not in str(bot.calls)
            count=len(bot.calls); await asyncio.sleep(0.025); assert len(bot.calls)==count
        finally: release.set(); await bot.session.close()
    asyncio.run(run())


def test_long_progress_keeps_animated_suffix_inside_telegram_budget():
    from capri.guest_progress import ProgressView
    view=ProgressView(); view.accept(E('text','🙂'*3000))
    first=view.render(); second=view.render()
    assert len(first.encode('utf-16-le'))//2<=4096
    assert first.endswith(' ·') and second.endswith(' ··')
    assert 'скорочено' in first


def test_silent_placeholder_is_replaced_by_public_text(tmp_path):
    async def run():
        bot,runtime,store,service=setup(tmp_path)
        service.interval=0.01; service.startup_delay=0.005
        published=asyncio.Event(); original=bot.answer_guest_query
        async def answer(**kw):
            sent=await original(**kw); published.set(); return sent
        bot.answer_guest_query=answer
        async def stream(*a,**kw):
            await published.wait()
            yield E('start'); yield E('text','Real commentary'); yield E('message','Real commentary')
            yield E('tool_start')
            await asyncio.sleep(0.03)
            yield E('tool_end'); yield E('final','Final only')
        runtime.stream_guest=stream
        try:
            await service.handle(message())
            assert bot.calls[0].result.input_message_content.message_text=='·'
            texts=[c.text for c in bot.calls if isinstance(c,EditMessageText)]
            assert any(t.startswith('Real commentary ') for t in texts)
            assert texts[-1]=='Final only'
        finally: await bot.session.close()
    asyncio.run(run())


def test_final_does_not_wait_for_stream_teardown(tmp_path):
    async def run():
        bot,runtime,store,service=setup(tmp_path)
        final_sent=asyncio.Event(); original=bot.edit_message_text
        async def edit(**kw):
            result=await original(**kw)
            if kw['text']=='Completed answer': final_sent.set()
            return result
        bot.edit_message_text=edit
        async def stream(*a,**kw):
            try:
                yield E('text','Interim'); yield E('tool_start')
                yield E('final','Completed answer')
                # Teardown is allowed to wait, but must not hold final delivery.
                await asyncio.wait_for(final_sent.wait(),0.1)
                raise RuntimeError('child teardown failed')
            finally: runtime.closed=True
        runtime.stream_guest=stream
        try:
            await service.handle(message())
            assert final_sent.is_set() and runtime.closed
            assert bot.calls[-1].text=='Completed answer'
        finally: await bot.session.close()
    asyncio.run(run())


def test_final_retries_flood_wait_on_same_inline_message(tmp_path):
    from aiogram.exceptions import TelegramRetryAfter
    async def run():
        bot,runtime,store,service=setup(tmp_path)
        attempts=[]; original=bot.edit_message_text
        async def edit(**kw):
            attempts.append(kw)
            if len(attempts)==1:
                raise TelegramRetryAfter(method=EditMessageText(**kw),message='Flood',retry_after=0)
            return await original(**kw)
        bot.edit_message_text=edit
        try:
            await service.handle(message())
            assert len(attempts)==2
            assert all(c['inline_message_id']=='inline-1' and c['text']=='Hello\n\nworld' for c in attempts)
            assert len([c for c in bot.calls if isinstance(c,AnswerGuestQuery)])==1
        finally: await bot.session.close()
    asyncio.run(run())


def test_guest_consumes_tokens_while_answer_transport_waits(tmp_path):
    async def run():
        bot,runtime,store,service=setup(tmp_path)
        service.interval=0.01; service.startup_delay=1
        more_tokens=asyncio.Event(); preview_seen=asyncio.Event()
        original_answer=bot.answer_guest_query; original_edit=bot.edit_message_text
        async def answer(**kw):
            # Telegram can be slow. It must not hold the model reader.
            await asyncio.wait_for(more_tokens.wait(),0.15)
            return await original_answer(**kw)
        async def edit(**kw):
            sent=await original_edit(**kw)
            if 'First second' in kw['text']: preview_seen.set()
            return sent
        bot.answer_guest_query=answer; bot.edit_message_text=edit
        async def stream(*a,**kw):
            try:
                yield E('start'); yield E('text','First ')
                yield E('text','second')
                more_tokens.set()
                # The preview must be delivered before the model completes.
                await asyncio.wait_for(preview_seen.wait(),0.3)
                yield E('text',' third'); yield E('final','First second third')
            finally: runtime.closed=True
        runtime.stream_guest=stream
        try:
            await service.handle(message())
            assert more_tokens.is_set(), 'Telegram answer blocked token consumption'
            assert preview_seen.is_set(), 'no growing text preview before final'
            assert bot.calls[-1].text=='First second third' and runtime.closed
            assert len([c for c in bot.calls if isinstance(c,AnswerGuestQuery)])==1
        finally: await bot.session.close()
    asyncio.run(run())


def test_old_progress_cannot_hide_streaming_answer():
    from capri.guest_progress import ProgressView
    view=ProgressView()
    view.accept(E('text','Old commentary '*600)); view.accept(E('tool_start'))
    view.accept(E('start')); view.accept(E('text','New answer is streaming'))
    rendered=view.render()
    assert 'New answer is streaming' in rendered
    assert len(rendered.encode('utf-16-le'))//2<=4096
