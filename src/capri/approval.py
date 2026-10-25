"""Single-use Owner Telegram dialogs; native OMP remains the policy authority."""
import asyncio
from dataclasses import dataclass
import secrets
import unicodedata
from collections.abc import Callable
from contextlib import suppress

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InaccessibleMessage

from .engine import ShellApproval
from .teardown import complete_cleanup

PREFIX = 'capri-approval:'


@dataclass
class _Pending:
    owner: int
    deadline: float
    future: asyncio.Future
    message_id: int | None = None


def _readable(text: str) -> bool:
    return all(char in '\n\t' or not unicodedata.category(char).startswith('C')
               for char in text)


class ApprovalBridge:
    def __init__(self, bot, owner_id: Callable[[], int | None]):
        self.bot = bot
        self.owner_id = owner_id
        self._pending = {}
        self._requests = set()
        self._closed = False

    async def request(self, request: ShellApproval) -> bool:
        owner = self.owner_id()
        loop = asyncio.get_running_loop()
        deadline = min(request.deadline, loop.time() + 60)
        text = ('OMP просить дозвіл виконати shell-команду один раз.\n'
                'Це дозвіл на виконання, не гарантія безпечності команди.\n\n'
                f'Робоча директорія: {request.cwd}\n\n'
                f'Команда:\n{request.command}\n\n'
                'Без відповіді протягом 60 секунд — відмова.')
        if (self._closed or owner is None or deadline <= loop.time()
                or not _readable(text) or len(text.encode('utf-16-le')) // 2 > 4096):
            return False
        token = secrets.token_urlsafe(18)
        pending = _Pending(owner, deadline, loop.create_future())
        self._pending[token] = pending
        task = asyncio.current_task()
        self._requests.add(task)
        markup = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text='Дозволити один раз', callback_data=PREFIX + token + ':yes'),
            InlineKeyboardButton(text='Відхилити', callback_data=PREFIX + token + ':no'),
        ]])
        try:
            async with asyncio.timeout_at(deadline):
                message = await self.bot.send_message(chat_id=owner, text=text,
                    parse_mode=None, reply_markup=markup)
                pending.message_id = message.message_id
                return await pending.future
        except asyncio.CancelledError:
            if self._closed:
                return False
            raise
        except Exception:
            # An uncertain send is not retried. Any remotely delivered button expires.
            return False
        finally:
            self._pending.pop(token, None)
            if not pending.future.done():
                pending.future.cancel()
            async def clean():
                if pending.message_id is not None:
                    with suppress(Exception):
                        await asyncio.wait_for(self.bot.edit_message_reply_markup(
                            chat_id=owner, message_id=pending.message_id, reply_markup=None), 3)
            try:
                await complete_cleanup(clean())
            finally:
                self._requests.discard(task)

    async def handle_callback(self, query) -> None:
        data = getattr(query, 'data', None)
        parts = data.split(':') if isinstance(data, str) else []
        pending = self._pending.get(parts[1]) if len(parts) == 3 and parts[0] == PREFIX[:-1] else None
        message = getattr(query, 'message', None)
        sender = getattr(query, 'from_user', None)
        chat = getattr(message, 'chat', None)
        valid = (pending is not None and not self._closed
                 and parts[2] in {'yes', 'no'}
                 and sender is not None and sender.id == pending.owner == self.owner_id()
                 and message is not None and not isinstance(message, InaccessibleMessage)
                 and getattr(chat, 'type', None) == 'private' and chat.id == pending.owner
                 and pending.message_id is not None
                 and getattr(message, 'message_id', None) == pending.message_id
                 and asyncio.get_running_loop().time() < pending.deadline
                 and not pending.future.done())
        if valid:
            # Single-use before ANY network await. Ack/edit failures cannot resurrect it.
            self._pending.pop(parts[1], None)
            pending.future.set_result(parts[2] == 'yes')
        with suppress(Exception):
            await asyncio.wait_for(query.answer(
                text='Рішення прийнято.' if valid else 'Запит недоступний або вже завершений.'), 3)

    async def notice(self, text: str) -> None:
        owner = self.owner_id()
        if not self._closed and owner is not None:
            with suppress(Exception):
                await asyncio.wait_for(self.bot.send_message(
                    chat_id=owner, text=text, parse_mode=None), 3)

    async def close(self) -> None:
        self._closed = True
        pending = list(self._pending.values())
        self._pending.clear()
        for item in pending:
            if not item.future.done():
                item.future.set_result(False)
        tasks = list(self._requests)
        # Cancel sends as well as future waits, so shutdown cannot strand a dialog.
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            async def join():
                await asyncio.gather(*tasks, return_exceptions=True)
            await complete_cleanup(join())
