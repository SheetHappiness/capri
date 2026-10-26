import asyncio
from types import SimpleNamespace as NS

import pytest
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendMessage
from omp_rpc import ToolExecutionStartEvent, ToolExecutionUpdateEvent, ToolExecutionEndEvent

from capri.telegram import deliver
from test_activity import thought, result


class Bot:
    def __init__(self):
        self.activity = []
        self.edits = []
        self.answers = []
        self.drafts = []

    async def send_message(self, **kw):
        if kw['text'].startswith(('Checking', 'First', 'thinking')):
            self.activity.append((asyncio.get_running_loop().time(), kw))
        else:
            self.answers.append(kw['text'])
        return NS(message_id=73)

    async def edit_message_text(self, **kw):
        self.edits.append((asyncio.get_running_loop().time(), kw))

    async def send_message_draft(self, **kw):
        self.drafts.append(kw['text'])


def test_one_live_activity_coalesces_bursts_and_stays_separate_from_bubbles():
    async def run():
        bot = Bot()
        async def stream():
            yield thought('Checking files')
            await asyncio.sleep(0.005)
            assert len(bot.activity) == 1 and not bot.answers
            yield ToolExecutionStartEvent(tool_call_id='b', tool_name='bash', args={'command': 'pytest'})
            for number in range(100):
                yield ToolExecutionUpdateEvent(tool_call_id='b', tool_name='bash', partial_result=result(str(number)))
            yield ToolExecutionEndEvent(tool_call_id='b', tool_name='bash', result=result('12 passed'), is_error=False)
            yield 'ага, знайшла<bubble>проблема була в ...'
        await deliver(bot, 42, stream(), draft_id=7, interval=0.03)
        assert bot.answers == ['ага, знайшла', 'проблема була в ...']
        assert len(bot.activity) == 1 and 1 <= len(bot.edits) <= 2
        assert '12 passed' in bot.edits[-1][1]['text']
        assert bot.edits[-1][1]['text'].endswith('✓ done')
        calls = bot.activity + bot.edits
        assert all(second[0] - first[0] >= 0.028 for first, second in zip(calls, calls[1:]))
        assert all(kw['message_id'] == 73 and kw['chat_id'] == 42 and kw['parse_mode'] is None
                   for _, kw in bot.edits)
        assert all('Checking' not in text and 'pytest' not in text for text in bot.drafts + bot.answers)
    asyncio.run(run())


@pytest.mark.parametrize('fail_on', ['send', 'edit'])
def test_activity_retry_after_coalesces_and_paces_final(fail_on):
    async def run():
        attempts = []
        class Limited(Bot):
            async def request(self, kind, kw):
                if kind == fail_on:
                    attempts.append(asyncio.get_running_loop().time())
                    if len(attempts) == 1:
                        raise TelegramRetryAfter(method=SendMessage(chat_id=1, text='x'),
                                                 message='slow', retry_after=0.04)
            async def send_message(self, **kw):
                if kw['text'].startswith(('Checking', 'First', 'thinking')):
                    await self.request('send', kw)
                return await super().send_message(**kw)
            async def edit_message_text(self, **kw):
                await self.request('edit', kw)
                await super().edit_message_text(**kw)
        bot = Limited()
        async def stream():
            yield thought('First')
            await asyncio.sleep(0.005)
            for _ in range(100):
                yield thought('.')
            yield 'answer'
        await deliver(bot, 1, stream(), draft_id=1, interval=0.01)
        assert len(bot.activity) == 1 and bot.answers == ['answer']
        assert len(attempts) == 2 and attempts[1] - attempts[0] >= 0.039
        latest = (bot.edits or bot.activity)[-1][1]['text']
        assert 'First' + '.' * 100 in latest and latest.endswith('✓ done')
    asyncio.run(run())


def test_uncertain_activity_send_is_not_retried_and_does_not_lose_answer():
    async def run():
        class Failing(Bot):
            async def send_message(self, **kw):
                response = await super().send_message(**kw)
                if kw['text'].startswith(('Checking', 'First', 'thinking')):
                    raise TimeoutError('private transport error')
                return response
        bot = Failing()
        async def stream():
            yield thought('thinking')
            await asyncio.sleep(0.005)
            yield thought(' more')
            yield 'answer'
        await deliver(bot, 1, stream(), draft_id=1, interval=0.001)
        assert len(bot.activity) == 1 and not bot.edits and bot.answers == ['answer']
    asyncio.run(run())


@pytest.mark.parametrize('phase', ['send', 'throttle'])
def test_cancellation_joins_activity_sender_and_closes_source(phase):
    async def run():
        entered = asyncio.Event()
        closed = asyncio.Event()
        request_closed = asyncio.Event()
        before = asyncio.all_tasks()
        class Slow(Bot):
            async def send_message(self, **kw):
                response = await super().send_message(**kw)
                if kw['text'].startswith(('Checking', 'First', 'thinking')) and phase == 'send':
                    entered.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        request_closed.set()
                return response
        bot = Slow()
        async def stream():
            try:
                yield thought('thinking')
                await asyncio.sleep(0.005)
                yield thought(' more')
                if phase == 'throttle':
                    entered.set()
                await asyncio.Event().wait()
            finally:
                closed.set()
        task = asyncio.create_task(deliver(bot, 1, stream(), draft_id=1, interval=0.04))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed.is_set()
        if phase == 'send':
            assert request_closed.is_set()
        assert not bot.answers and not bot.edits
        assert not (asyncio.all_tasks() - before)
    asyncio.run(run())


def test_stream_failure_finishes_activity_without_exposing_error_details():
    async def run():
        bot = Bot()
        async def stream():
            yield thought('Checking')
            await asyncio.sleep(0.005)
            raise RuntimeError('private exception')
        await deliver(bot, 1, stream(), draft_id=1, interval=0.001)
        assert bot.edits[-1][1]['text'].endswith('✗ failed')
        assert len(bot.answers) == 1 and 'помил' in bot.answers[0]
        assert 'private' not in str(bot.activity + bot.edits + bot.answers)
    asyncio.run(run())


def test_long_activity_retry_does_not_hold_the_completed_answer(monkeypatch):
    import capri.telegram as telegram
    monkeypatch.setattr(telegram, '_ACTIVITY_FINISH_TIMEOUT', 0.04)
    async def run():
        class Limited(Bot):
            async def send_message(self, **kw):
                if kw['text'].startswith(('Checking', 'First', 'thinking')):
                    raise TelegramRetryAfter(method=SendMessage(chat_id=1, text='x'),
                                             message='slow', retry_after=60)
                return await super().send_message(**kw)
        bot = Limited()
        async def stream():
            yield thought('Checking')
            await asyncio.sleep(0.005)
            yield 'answer'
        await asyncio.wait_for(deliver(bot, 1, stream(), draft_id=1, interval=0.01), 0.3)
        assert bot.answers == ['answer']
    asyncio.run(run())
