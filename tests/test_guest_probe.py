import asyncio
import logging
import json
from datetime import datetime, timezone

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.methods import AnswerGuestQuery
from aiogram.types import Message, SentGuestMessage
from aiogram.types import Update, User
from aiogram.methods import GetMe
from aiogram.methods import EditMessageText
from aiogram import Dispatcher

from capri.guest_probe import GuestProbe


def message(**changes):
    fields = dict(message_id=1, date=datetime.now(timezone.utc),
                  chat={'id': 7, 'type': 'private'},
                  from_user={'id': 7, 'is_bot': False, 'first_name': 'Owner'},
                  text='Тест @Capriompbot', guest_query_id='q1')
    fields.update(changes)
    return Message(**fields)


class RecordingBot(Bot):
    def __init__(self):
        super().__init__('123:TEST')
        self.calls = []
        self.failure = None
        self.entered = asyncio.Event()
        self.release = None

    async def __call__(self, method, **kwargs):
        assert isinstance(method, AnswerGuestQuery), 'ordinary send forbidden'
        self.calls.append(method)
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.failure:
            raise self.failure(method=method, message='PRIVATE SECRET')
        return SentGuestMessage(inline_message_id='guest-inline')


def test_owner_gets_one_guest_result_without_message_bot_binding():
    async def run():
        bot = RecordingBot()
        try:
            await GuestProbe(bot, 7).handle(message())
            assert len(bot.calls) == 1
            result = bot.calls[0]
            assert result.guest_query_id == 'q1'
            assert result.result.input_message_content.message_text == 'Guest OK'
            assert result.result.input_message_content.parse_mode is None
        finally:
            await bot.session.close()
    asyncio.run(run())


@pytest.mark.parametrize('changes,owner_id', [
    ({'from_user': {'id': 8, 'is_bot': False, 'first_name': 'Other'}}, 7),
    ({'from_user': None}, 7),
    ({'from_user': {'id': 1087968824, 'is_bot': True, 'first_name': 'Service'}}, 7),
    ({'sender_chat': {'id': 7, 'type': 'channel', 'title': 'Channel'}}, 7),
    ({'guest_query_id': None}, 7),
    ({}, None),
    ({'from_user': {'id': 8, 'is_bot': False, 'first_name': 'Other'},
      'guest_bot_caller_user': {'id': 7, 'is_bot': False, 'first_name': 'Owner'}}, 7),
])
def test_rejected_identity_never_sends(changes, owner_id, caplog):
    caplog.set_level(logging.INFO)
    async def run():
        bot = RecordingBot()
        try:
            await GuestProbe(bot, owner_id).handle(message(**changes))
            assert bot.calls == []
        finally:
            await bot.session.close()
    asyncio.run(run())
    assert 'Тест' not in caplog.text
    assert 'q1' not in caplog.text


def test_duplicate_inflight_has_one_attempt():
    async def run():
        bot = RecordingBot()
        bot.release = asyncio.Event()
        probe = GuestProbe(bot, 7)
        task = asyncio.create_task(probe.handle(message()))
        try:
            await asyncio.wait_for(bot.entered.wait(), 1)
            await probe.handle(message())
            bot.release.set()
            await task
            assert len(bot.calls) == 1
        finally:
            bot.release.set()
            await task
            await bot.session.close()
    asyncio.run(run())


@pytest.mark.parametrize('failure', [TelegramBadRequest, TelegramNetworkError])
def test_answer_failure_no_retry_or_raw_error(failure, caplog):
    caplog.set_level(logging.INFO)
    async def run():
        bot = RecordingBot()
        bot.failure = failure
        probe = GuestProbe(bot, 7)
        try:
            await probe.handle(message())
            await probe.handle(message())
            assert len(bot.calls) == 1
        finally:
            await bot.session.close()
    asyncio.run(run())
    assert 'answer_failed' in caplog.text
    assert 'PRIVATE SECRET' not in caplog.text


@pytest.mark.parametrize('contents', [None, '', '{broken', '{}', '[]',
    '{"owner_id": null}', '{"owner_id": true}', '{"owner_id": "7"}',
    '{"owner_id": 0}', '{"owner_id": -7}'])
def test_pairing_unavailable_refuses_before_bot(tmp_path, monkeypatch, capsys, contents):
    import capri.guest_probe as probe
    if contents is not None:
        (tmp_path/'owner.json').write_text(contents, encoding='utf-8')
    def forbidden(*args, **kwargs):
        raise AssertionError('no Bot or API before valid pairing')
    monkeypatch.setattr(probe, 'Bot', forbidden)
    asyncio.run(probe.run_guest_probe('123:TEST', tmp_path))
    assert capsys.readouterr().out.strip() == 'guest_probe: owner pairing unavailable'
    if contents is None:
        assert not (tmp_path/'owner.json').exists()
    else:
        assert (tmp_path/'owner.json').read_text(encoding='utf-8') == contents


@pytest.mark.parametrize('capability,stop', [(True, None), (False, None),
    (None, None), (True, 'get_me'), (True, 'poll')])
def test_probe_lifecycle_no_omp_or_session_mutation(tmp_path, monkeypatch, caplog, capability, stop):
    import capri.guest_probe as probe
    from capri.engine import Engine
    caplog.set_level(logging.INFO)
    (tmp_path/'owner.json').write_text(json.dumps({'owner_id': 7}), encoding='utf-8')
    for name in ['session.json', 'owner.jsonl']:
        (tmp_path/name).write_text('owner data', encoding='utf-8')
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()}
    bots, polls = [], []
    class FakeBot(RecordingBot):
        def __init__(self, token):
            super().__init__()
            from unittest.mock import AsyncMock
            self.session.close = AsyncMock(wraps=self.session.close)
            bots.append(self)
        async def __call__(self, method, **kwargs):
            if isinstance(method, GetMe):
                if stop == 'get_me':
                    raise TelegramNetworkError(method=method, message='PRIVATE SECRET')
                return User(id=123, is_bot=True, first_name='Capri', username='Capriompbot',
                            supports_guest_queries=capability)
            return await super().__call__(method, **kwargs)
    class FakeDispatcher(Dispatcher):
        async def start_polling(self, bot, **kwargs):
            polls.append(kwargs)
            assert self.resolve_used_update_types() == ['guest_message']
            assert kwargs == {'allowed_updates': ['guest_message'], 'close_bot_session': False}
            if stop == 'poll':
                raise asyncio.CancelledError
            await self.feed_update(bot, Update(update_id=1, guest_message=message()))
    def forbidden(*args, **kwargs):
        raise AssertionError('probe must never construct/start Engine')
    monkeypatch.setattr(Engine, '__init__', forbidden)
    monkeypatch.setattr(Engine, 'start', forbidden)
    monkeypatch.setattr(probe, 'Bot', FakeBot)
    monkeypatch.setattr(probe, 'Dispatcher', FakeDispatcher)
    if stop == 'poll':
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(probe.run_guest_probe('123:TEST', tmp_path))
    else:
        asyncio.run(probe.run_guest_probe('123:TEST', tmp_path))
    assert len(bots) == 1
    bots[0].session.close.assert_awaited_once()
    assert len(polls) == int(capability is True and stop != 'get_me')
    assert len(bots[0].calls) == int(capability is True and stop is None)
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()} == before
    assert 'PRIVATE SECRET' not in caplog.text
    if capability is not True:
        assert 'BotFather' in caplog.text


class EditingBot(RecordingBot):
    def __init__(self):
        super().__init__()
        self.edits = []
        self.inline_id = 'guest-inline'
        self.edit_failure = None

    async def __call__(self, method, **kwargs):
        if isinstance(method, EditMessageText):
            self.edits.append(method)
            if self.edit_failure:
                raise self.edit_failure(method=method, message='PRIVATE SECRET')
            return True
        await super().__call__(method, **kwargs)
        # Deliberately permit malformed response for the missing-ID boundary test.
        from types import SimpleNamespace
        return SimpleNamespace(inline_message_id=self.inline_id)


def test_edit_phase_answers_then_edits_the_same_inline_message():
    async def run():
        bot = EditingBot()
        delays = []
        async def sleep(seconds):
            assert len(bot.calls) == 1 and bot.edits == []
            delays.append(seconds)
        try:
            await GuestProbe(bot, 7, phase='edit', sleep=sleep).handle(message())
            assert len(bot.calls) == 1
            assert bot.calls[0].result.input_message_content.message_text == 'Думаю…'
            assert delays == [2.0]
            assert len(bot.edits) == 1
            edit = bot.edits[0]
            assert edit.inline_message_id == 'guest-inline'
            assert edit.chat_id is None and edit.message_id is None
            assert edit.text == 'Guest OK final' and edit.parse_mode is None
        finally:
            await bot.session.close()
    asyncio.run(run())


def test_answer_phase_never_sleeps_or_edits():
    async def run():
        bot = EditingBot()
        async def forbidden(_):
            raise AssertionError('answer phase must not sleep')
        try:
            await GuestProbe(bot, 7, phase='answer', sleep=forbidden).handle(message())
            assert bot.calls[0].result.input_message_content.message_text == 'Guest OK'
            assert len(bot.calls) == 1 and bot.edits == []
        finally:
            await bot.session.close()
    asyncio.run(run())


@pytest.mark.parametrize('failure', ['answer', 'missing_id', 'edit_api', 'edit_network'])
def test_edit_boundary_failure_never_replies_again(failure, caplog):
    caplog.set_level(logging.INFO)
    async def run():
        bot = EditingBot()
        delays = []
        if failure == 'answer':
            bot.failure = TelegramBadRequest
        elif failure == 'missing_id':
            bot.inline_id = None
        else:
            bot.edit_failure = TelegramBadRequest if failure == 'edit_api' else TelegramNetworkError
        async def sleep(seconds):
            delays.append(seconds)
        probe = GuestProbe(bot, 7, phase='edit', sleep=sleep)
        try:
            await probe.handle(message())
            await probe.handle(message())
            assert len(bot.calls) == 1
            expected_edits = int(failure.startswith('edit_'))
            assert len(bot.edits) == expected_edits
            assert delays == ([2.0] if expected_edits else [])
        finally:
            await bot.session.close()
    asyncio.run(run())
    assert 'PRIVATE SECRET' not in caplog.text
    assert ('answer_failed' if failure == 'answer' else
            'missing_inline_id' if failure == 'missing_id' else 'edit_failed') in caplog.text


def test_cancel_demonstration_delay_closes_probe_session(tmp_path, monkeypatch):
    import capri.guest_probe as probe
    (tmp_path/'owner.json').write_text('{"owner_id": 7}', encoding='utf-8')
    async def run():
        from unittest.mock import AsyncMock
        bot = EditingBot()
        bot.session.close = AsyncMock(wraps=bot.session.close)
        waiting = asyncio.Event()
        async def sleep(_):
            waiting.set()
            await asyncio.Event().wait()
        class TestProbe(GuestProbe):
            def __init__(self, bot, owner_id, *, phase):
                super().__init__(bot, owner_id, phase=phase, sleep=sleep)
        class FakeDispatcher(Dispatcher):
            async def start_polling(self, bot, **kwargs):
                await self.feed_update(bot, Update(update_id=1, guest_message=message()))
        original_call = bot.__class__.__call__
        class LiveFake(EditingBot):
            async def __call__(self, method, **kwargs):
                if isinstance(method, GetMe):
                    return User(id=123, is_bot=True, first_name='Capri', supports_guest_queries=True)
                return await original_call(self, method, **kwargs)
        bot.__class__ = LiveFake
        monkeypatch.setattr(probe, 'Bot', lambda token: bot)
        monkeypatch.setattr(probe, 'Dispatcher', FakeDispatcher)
        monkeypatch.setattr(probe, 'GuestProbe', TestProbe)
        existing = asyncio.all_tasks()
        task = asyncio.create_task(probe.run_guest_probe('123:TEST', tmp_path, phase='edit'))
        await asyncio.wait_for(waiting.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert bot.edits == [] and len(bot.calls) == 1
        bot.session.close.assert_awaited_once()
        assert not (asyncio.all_tasks() - existing)
    asyncio.run(run())
