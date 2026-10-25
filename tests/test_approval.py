import asyncio
from types import SimpleNamespace as NS

import pytest
from capri.engine import ShellApproval


class Bot:
    def __init__(self):
        self.sent = []; self.edits = []; self.fail_send = False; self.fail_edit = False
    async def send_message(self, **kw):
        self.sent.append(kw)
        if self.fail_send: raise OSError('uncertain delivery')
        return NS(message_id=len(self.sent), chat=NS(id=kw['chat_id'], type='private'))
    async def edit_message_reply_markup(self, **kw):
        self.edits.append(kw)
        if self.fail_edit: raise OSError('cannot edit')


def request(tmp_path, seconds=60, command='printf test'):
    return ShellApproval('sdk-id-not-for-telegram', command, tmp_path, 'native prompt',
                         asyncio.get_running_loop().time() + seconds)


def query(bot, choice=0, user=7, chat=7, kind='private', mid=1, data=None):
    if data is None:
        data = bot.sent[-1]['reply_markup'].inline_keyboard[0][choice].callback_data
    async def answer(**kw): pass
    return NS(data=data, from_user=NS(id=user), answer=answer,
              message=NS(message_id=mid, chat=NS(id=chat, type=kind)))


async def wait_sent(bot):
    for _ in range(100):
        if bot.sent: return
        await asyncio.sleep(.001)
    raise AssertionError('approval message not sent')


@pytest.mark.parametrize('choice,want', [(0, True), (1, False)])
def test_one_call_private_buttons_and_plain_exact_display(tmp_path, choice, want):
    from capri.approval import ApprovalBridge
    async def run():
        bot = Bot(); bridge = ApprovalBridge(bot, lambda: 7)
        task = asyncio.create_task(bridge.request(request(tmp_path, command='echo <hello>')))
        await wait_sent(bot)
        sent = bot.sent[0]
        assert sent['chat_id'] == 7
        assert 'echo <hello>' in sent['text'] and str(tmp_path) in sent['text']
        assert sent.get('parse_mode') is None
        buttons = sent['reply_markup'].inline_keyboard[0]
        assert [b.text for b in buttons] == ['Дозволити один раз', 'Відхилити']
        assert all(len(b.callback_data.encode()) <= 64 for b in buttons)
        assert all('sdk-id' not in b.callback_data and 'echo' not in b.callback_data for b in buttons)
        await bridge.handle_callback(query(bot, choice))
        assert await task is want
        await bridge.handle_callback(query(bot, 1 - choice))
        assert bot.edits
        await bridge.close()
    asyncio.run(run())


@pytest.mark.parametrize('bad', ['user', 'chat', 'group', 'message', 'missing', 'malformed', 'unknown', 'owner_changed'])
def test_unauthorized_callbacks_cannot_consume_request(tmp_path, bad):
    from capri.approval import ApprovalBridge
    async def run():
        bot = Bot(); owner = [7]; bridge = ApprovalBridge(bot, lambda: owner[0])
        task = asyncio.create_task(bridge.request(request(tmp_path)))
        await wait_sent(bot)
        q = query(bot)
        if bad == 'user': q.from_user.id = 8
        if bad == 'chat': q.message.chat.id = 8
        if bad == 'group': q.message.chat.type = 'group'
        if bad == 'message': q.message.message_id = 55
        if bad == 'missing': q.message = None
        if bad == 'malformed': q.data += ':extra'
        if bad == 'unknown': q.data = 'capri-approval:unknown:yes'
        if bad == 'owner_changed': owner[0] = 8
        await bridge.handle_callback(q)
        assert not task.done()
        owner[0] = 7
        await bridge.handle_callback(query(bot))
        assert await task is True
        await bridge.close()
    asyncio.run(run())


@pytest.mark.parametrize('failure', ['timeout', 'cancel', 'close', 'send', 'edit', 'ack'])
def test_failure_cleanup_stale_clicks_and_no_retry(tmp_path, failure):
    from capri.approval import ApprovalBridge
    async def run():
        bot = Bot(); bridge = ApprovalBridge(bot, lambda: 7)
        bot.fail_send = failure == 'send'; bot.fail_edit = failure == 'edit'
        task = asyncio.create_task(bridge.request(request(tmp_path, seconds=.03 if failure == 'timeout' else 60)))
        await wait_sent(bot)
        old = query(bot)
        if failure == 'cancel':
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
        elif failure == 'close':
            await bridge.close(); assert await task is False
        elif failure in ('timeout', 'send'):
            assert await task is False
        else:
            if failure == 'ack':
                async def broken(**kw): raise OSError('ack failed')
                old.answer = broken
            await bridge.handle_callback(old)
            assert await task is True
        await bridge.handle_callback(old)
        assert len(bot.sent) == 1
        await bridge.close()
        assert await bridge.request(request(tmp_path)) is False
    asyncio.run(run())


@pytest.mark.parametrize('command', ['x' * 5000, 'echo a\x00b', 'echo a\u202eb'])
def test_unrenderable_commands_deny_without_sending(tmp_path, command):
    from capri.approval import ApprovalBridge
    async def run():
        bot = Bot(); bridge = ApprovalBridge(bot, lambda: 7)
        assert await bridge.request(request(tmp_path, command=command)) is False
        assert not bot.sent
        await bridge.close()
    asyncio.run(run())


def test_rejection_notice_is_private_plain_and_has_no_buttons():
    from capri.approval import ApprovalBridge
    async def run():
        bot = Bot(); bridge = ApprovalBridge(bot, lambda: 7)
        await bridge.notice('Запит відхилено.')
        assert bot.sent == [{'chat_id': 7, 'text': 'Запит відхилено.', 'parse_mode': None}]
        await bridge.close()
        await bridge.notice('Не надсилати')
        assert len(bot.sent) == 1
    asyncio.run(run())


def test_simultaneous_opposite_clicks_are_single_use(tmp_path):
    from capri.approval import ApprovalBridge
    async def run():
        bot = Bot(); bridge = ApprovalBridge(bot, lambda: 7)
        task = asyncio.create_task(bridge.request(request(tmp_path)))
        await wait_sent(bot)
        await asyncio.gather(bridge.handle_callback(query(bot, 1)), bridge.handle_callback(query(bot, 0)))
        assert await task is False
        await bridge.close()
    asyncio.run(run())
