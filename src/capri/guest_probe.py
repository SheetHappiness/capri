"""Temporary Telegram-only guest transport probe; no agent/session access."""
import logging
import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal

from aiogram import Bot, Dispatcher, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineQueryResultArticle, InputTextMessageContent, Message
from .config import Pairing


log = logging.getLogger(__name__)


class GuestProbe:
    def __init__(self, bot: Bot, owner_id: int, *,
                 phase: Literal['answer', 'edit'] = 'answer',
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep):
        self.bot = bot
        self.owner_id = owner_id
        self.phase = phase
        self.sleep = sleep
        self.seen: set[str] = set()

    async def handle(self, message: Message) -> None:
        sender = message.from_user
        if not message.guest_query_id:
            log.info('guest_probe: missing_query')
            return
        if (self.owner_id is None or sender is None or sender.is_bot
                or message.sender_chat is not None or sender.id != self.owner_id):
            log.info('guest_probe: unauthorized sender_present=%s sender_is_bot=%s sender_chat=%s',
                     sender is not None, sender.is_bot if sender else None,
                     message.sender_chat is not None)
            return
        if message.guest_query_id in self.seen:
            log.info('guest_probe: duplicate')
            return
        self.seen.add(message.guest_query_id)  # Reserve before awaiting the API ACK.
        log.info('guest_probe: authorized')
        result = InlineQueryResultArticle(id='capri-guest-probe', title='Capri',
            input_message_content=InputTextMessageContent(
                message_text='Думаю…' if self.phase == 'edit' else 'Guest OK', parse_mode=None))
        try:
            sent = await self.bot.answer_guest_query(guest_query_id=message.guest_query_id, result=result)
        except TelegramAPIError:
            # An uncertain ACK is never retried or routed through an ordinary chat.
            log.warning('guest_probe: answer_failed')
            return
        log.info('guest_probe: answer_ack')
        if self.phase == 'answer':
            return
        inline_id = getattr(sent, 'inline_message_id', None)
        if not isinstance(inline_id, str) or not inline_id:
            log.warning('guest_probe: missing_inline_id')
            return
        await self.sleep(2.0)
        try:
            await self.bot.edit_message_text(inline_message_id=inline_id,
                text='Guest OK final', parse_mode=None)
        except TelegramAPIError:
            log.warning('guest_probe: edit_failed')
        else:
            log.info('guest_probe: edit_ack')


async def run_guest_probe(token: str, data: Path, *,
                          phase: Literal['answer', 'edit'] = 'answer') -> None:
    owner_file = data / 'owner.json'
    try:
        if not owner_file.is_file():
            raise ValueError
        owner_id = Pairing(owner_file).owner_id
        if type(owner_id) is not int or owner_id <= 0:
            raise ValueError
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        print('guest_probe: owner pairing unavailable', flush=True)
        return

    bot = Bot(token)
    try:
        me = await bot.get_me()
        capability = getattr(me, 'supports_guest_queries', None)
        log.info('guest_probe: @%s supports_guest_queries=%r', me.username, capability)
        if capability is not True:
            log.warning('guest_probe: enable Guest Mode in @BotFather Bot Settings')
            return
        probe = GuestProbe(bot, owner_id, phase=phase)
        router = Router()
        router.guest_message.register(probe.handle)
        dp = Dispatcher()
        dp.include_router(router)
        updates = dp.resolve_used_update_types()
        log.info('guest_probe: allowed_updates=%s', updates)
        await dp.start_polling(bot, allowed_updates=updates, close_bot_session=False)
    except TelegramAPIError:
        log.warning('guest_probe: startup_or_polling_failed')
    finally:
        await bot.session.close()
