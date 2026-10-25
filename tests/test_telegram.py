import asyncio

from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendMessageDraft

from capri.telegram import deliver


def test_boundary_preferences_and_all_committed_has_no_empty_final():
    from capri.bubbles import BubbleComposer
    for text, expected in [
        ('A sentence. More words here tail', 'A sentence. '),
        ('words words words words words', 'words words '),
        ('a paragraph\n\nrest', 'a paragraph\n\n'),
    ]:
        composer=BubbleComposer(min_chars=5,soft_max=10)
        composer.append(text)
        assert text[:composer.boundary()] == expected
    async def run():
        bot=Bot()
        text='Paragraph here. ' * 12 + '\n\n'
        async def stream(): yield text
        await deliver(bot,1,stream(),draft_id=1)
        assert [m['text'] for m in bot.messages] == [text]
    asyncio.run(run())


def test_cancel_during_durable_send_closes_source():
    async def run():
        entered=asyncio.Event(); closed=asyncio.Event()
        class SlowBot(Bot):
            async def send_message(self, **kwargs):
                entered.set(); await asyncio.Event().wait()
        async def stream():
            try: yield 'Привіт<bubble>'
            finally: closed.set()
        source=stream()
        task=asyncio.create_task(deliver(SlowBot(),1,source,draft_id=1))
        await entered.wait(); task.cancel()
        try: await task
        except asyncio.CancelledError: pass
        assert closed.is_set()
    asyncio.run(run())


def test_early_bubbles_keep_only_suffix_in_draft_and_never_duplicate_final():
    async def run():
        bot = Bot()
        first = 'First paragraph. ' * 60 + '\n\n'
        second = 'Second paragraph. ' * 60 + '\n\n'
        async def stream():
            yield first + 'Tail'
            await asyncio.sleep(0.01)
            assert [m['text'] for m in bot.messages] == [first]
            assert bot.drafts[-1][1]['text'] == 'Tail'
            yield second + 'Last.'
            await asyncio.sleep(0.01)
            assert len(bot.messages) == 2
        await deliver(bot, 1, stream(), draft_id=7, interval=0.001)
        assert ''.join(m['text'] for m in bot.messages) == first + 'Tail' + second + 'Last.'
        assert bot.messages[-1]['text'] == 'Last.'
    asyncio.run(run())


def test_fenced_code_waits_for_close_and_short_answer_stays_single():
    async def run():
        bot = Bot()
        code = '```python\n' + 'print(1)\n\n' * 100
        async def stream():
            yield code
            await asyncio.sleep(0.01)
            assert not bot.messages
            yield '```\n\nTail'
            await asyncio.sleep(0.01)
            assert bot.messages[0]['text'] == code + '```\n\n'
        await deliver(bot, 1, stream(), draft_id=1)
        assert bot.messages[-1]['text'] == 'Tail'
        bot = Bot()
        async def short(): yield 'Yes. That works.\n\nFine.'
        await deliver(bot, 1, short(), draft_id=1)
        assert len(bot.messages) == 1
    asyncio.run(run())


class Bot:
    def __init__(self):
        self.drafts = []
        self.messages = []
        self.retry = False

    async def send_message_draft(self, **kwargs):
        self.drafts.append((asyncio.get_running_loop().time(), kwargs))
        if self.retry:
            self.retry = False
            raise TelegramRetryAfter(
                method=SendMessageDraft(chat_id=1, draft_id=1, text='x'),
                message='slow down', retry_after=0.04,
            )

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)


def test_draft_is_visible_before_completion_and_bursts_are_coalesced():
    async def run():
        bot = Bot()
        async def stream():
            yield 'hello'
            await asyncio.sleep(0.01)
            assert bot.drafts and not bot.messages
            for part in [' ', 'w', 'o', 'r', 'l', 'd']:
                yield part
            await asyncio.sleep(0.05)
            assert bot.drafts[-1][1]['text'] == 'hello world'
            assert not bot.messages
        await deliver(bot, 42, stream(), draft_id=7, interval=0.03)
        assert len(bot.drafts) == 2
        assert bot.messages == [{'chat_id': 42, 'text': 'hello world', 'parse_mode': None}]
        assert all(x[1]['draft_id'] == 7 for x in bot.drafts)
    asyncio.run(run())


def test_engine_failure_sends_one_safe_error_without_exception_details():
    async def run():
        bot = Bot()
        async def stream():
            yield 'partial'
            raise RuntimeError('secret token internal tool args')
        await deliver(bot, 1, stream(), draft_id=1, interval=0.01)
        assert len(bot.messages) == 1
        text = bot.messages[0]['text']
        assert 'secret' not in text and 'internal' not in text
        assert 'помил' in text.lower()
    asyncio.run(run())


def test_utf16_limit_keeps_one_message_and_marks_truncation():
    async def run():
        bot = Bot()
        async def stream():
            yield '😀' * 3000
        await deliver(bot, 1, stream(), draft_id=1)
        assert len(bot.messages) == 1
        text = bot.messages[0]['text']
        assert len(text.encode('utf-16-le')) // 2 <= 4096
        assert 'скорочено' in text
        assert text.startswith('😀')
    asyncio.run(run())


def test_retry_after_does_not_block_consumption_or_retry_each_token():
    async def run():
        bot = Bot()
        bot.retry = True
        consumed = []
        async def stream():
            yield 'A'
            await asyncio.sleep(0.005)
            for part in 'BCDE':
                consumed.append(part)
                yield part
            assert consumed == list('BCDE')
            await asyncio.sleep(0.06)
        await deliver(bot, 1, stream(), draft_id=1, interval=0.01)
        assert len(bot.drafts) == 2
        assert bot.drafts[1][0] - bot.drafts[0][0] >= 0.04
        assert bot.drafts[-1][1]['text'] == 'ABCDE'
        assert bot.messages[0]['text'] == 'ABCDE'
    asyncio.run(run())


def test_cancellation_does_not_persist_partial_answer():
    async def run():
        bot = Bot()
        async def stream():
            yield 'partial'
            await asyncio.sleep(10)
        task = asyncio.create_task(deliver(bot, 1, stream(), draft_id=1))
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError('cancellation swallowed')
        assert not bot.messages
    asyncio.run(run())


def test_final_delivery_is_not_retried_on_ambiguous_error():
    async def run():
        class FailingBot(Bot):
            async def send_message(self, **kwargs):
                self.messages.append(kwargs)
                raise TimeoutError('delivery unknown')
        bot = FailingBot()
        async def stream():
            yield 'answer'
        try:
            await deliver(bot, 1, stream(), draft_id=1)
        except TimeoutError:
            pass
        else:
            raise AssertionError('unknown final delivery must propagate')
        assert len(bot.messages) == 1
    asyncio.run(run())


def test_three_short_explicit_bubbles():
    async def run():
        bot = Bot()
        async def stream():
            yield 'Привіт<bubble>'
            assert [m['text'] for m in bot.messages] == ['Привіт']
            yield 'Як справи?<bubble>'
            assert [m['text'] for m in bot.messages] == ['Привіт', 'Як справи?']
            yield 'Ауууу'
        await deliver(bot, 1, stream(), draft_id=1)
        assert [m['text'] for m in bot.messages] == ['Привіт', 'Як справи?', 'Ауууу']
    asyncio.run(run())


def test_marker_never_enters_draft():
    async def run():
        bot = Bot()
        async def stream():
            for part in ['Привіт<', 'b', 'u', 'b', 'b', 'l', 'e', '>Як справи?<bu']:
                yield part
                await asyncio.sleep(0.003)
        await deliver(bot, 1, stream(), draft_id=1, interval=0.001)
        assert [m['text'] for m in bot.messages] == ['Привіт', 'Як справи?']
        assert all('<' not in draft['text'] for _, draft in bot.drafts)
        assert len({draft['draft_id'] for _, draft in bot.drafts}) == 2
    asyncio.run(run())


def test_short_paragraphs_without_marker():
    async def run():
        bot = Bot()
        text = 'A short paragraph. ' * 10 + '\n\nAnother thought.'
        async def stream():
            yield text
            assert not bot.messages
        await deliver(bot, 1, stream(), draft_id=1)
        assert [m['text'] for m in bot.messages] == [text]
    asyncio.run(run())


def test_repeated_and_trailing_markers():
    async def run():
        for text, expected in [('<bubble>Привіт<bubble><bubble>', ['Привіт']),
                               ('<bubble><bubble>', ['Модель не повернула текстової відповіді.'])]:
            bot = Bot()
            async def stream(): yield text
            await deliver(bot, 1, stream(), draft_id=1)
            assert [m['text'] for m in bot.messages] == expected
    asyncio.run(run())


def test_explicit_plus_size_fallback():
    async def run():
        bot = Bot()
        long_text = 'Long sentence. ' * 360 + '\n\nTail.'
        async def stream():
            yield 'Hi<bubble>' + long_text
            assert len(bot.messages) >= 3
        await deliver(bot, 1, stream(), draft_id=1)
        assert ''.join(m['text'] for m in bot.messages) == 'Hi' + long_text
        assert all(len(m['text'].encode('utf-16-le')) // 2 <= 4096 for m in bot.messages)
    asyncio.run(run())


def test_code_literal_round_trip():
    async def run():
        bot = Bot()
        code = '```text\n<bubble>\n```\n'
        async def stream():
            for char in code + '<bubble>Tail':
                yield char
        await deliver(bot, 1, stream(), draft_id=1)
        assert [m['text'] for m in bot.messages] == [code, 'Tail']
    asyncio.run(run())


def test_explicit_oversize_is_fitted_and_retry_after_only_retries_preview():
    async def run():
        bot = Bot()
        bot.retry = True
        async def stream():
            yield 'Hi'
            await asyncio.sleep(0.06)
            yield '<bubble>' + '😀' * 3000 + '<bubble>'
        await deliver(bot, 1, stream(), draft_id=1, interval=0.001)
        assert len(bot.drafts) == 2
        assert len(bot.messages) == 2
        assert bot.messages[0]['text'] == 'Hi'
        assert 'скорочено' in bot.messages[1]['text']
        assert len(bot.messages[1]['text'].encode('utf-16-le')) // 2 <= 4096
    asyncio.run(run())


def test_uncertain_explicit_commit_stops_source_without_retrying_text():
    async def run():
        closed = asyncio.Event()
        class UncertainBot(Bot):
            async def send_message(self, **kwargs):
                self.messages.append(kwargs)
                if kwargs['text'] == 'Hi':
                    raise TimeoutError('unknown outcome')
        bot = UncertainBot()
        async def stream():
            try:
                yield 'Hi<bubble>Never send this'
                raise AssertionError('source must stop after uncertain commit')
            finally:
                closed.set()
        await deliver(bot, 1, stream(), draft_id=1)
        assert closed.is_set()
        assert bot.messages[0]['text'] == 'Hi'
        assert len(bot.messages) == 2
        assert 'помил' in bot.messages[1]['text'].lower()
        assert all('Never' not in m['text'] for m in bot.messages)
    asyncio.run(run())


def test_whitespace_between_markers_is_not_an_empty_telegram_message():
    async def run():
        for text, expected in [
            (' <bubble>Hi<bubble>\n <bubble>\n', ['Hi']),
            ('\n <bubble>\t', ['Модель не повернула текстової відповіді.']),
        ]:
            bot = Bot()
            async def stream(): yield text
            await deliver(bot, 1, stream(), draft_id=1)
            assert [m['text'] for m in bot.messages] == expected
    asyncio.run(run())


def test_cancel_after_commit_preserves_only_committed_bubble():
    async def run():
        bot = Bot()
        waiting = asyncio.Event()
        closed = asyncio.Event()
        async def stream():
            try:
                yield 'Hi<bubble>Unfinished'
                waiting.set()
                await asyncio.Event().wait()
            finally:
                closed.set()
        task = asyncio.create_task(deliver(bot, 1, stream(), draft_id=1))
        await asyncio.wait_for(waiting.wait(), 1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert closed.is_set()
        assert [m['text'] for m in bot.messages] == ['Hi']
    asyncio.run(run())
