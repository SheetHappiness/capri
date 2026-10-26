"""Translate native OMP approval choices into owner-only Telegram buttons."""
import asyncio
from dataclasses import dataclass
import secrets

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .engine import EngineError
from .teardown import complete_cleanup


def _choices(request):
    options = request.options or ()
    once = 'Approve Once' if 'Approve Once' in options else 'Approve'
    if request.method != 'select' or not (request.title or '').startswith('Allow tool: '):
        return {}
    if once not in options or 'Deny' not in options:
        return {}
    choices = {'once': once}
    session = next((value for value in options
        if value.startswith('Approve ') and value.endswith(' for this session')), None)
    if session is None and once == 'Approve Once':
        # Cached-mode grants refer to exact targets when available. Persistent
        # Always choices are never selected or synthesized by this view.
        session = next((value for value in ('Approve File', 'Approve') if value in options), None)
        if session is None:
            session = next((value for value in options if value.startswith('Approve Directory: ')), None)
    if session is not None:
        choices['session'] = session
    choices['deny'] = 'Deny'
    return choices


@dataclass
class _Card:
    request_id: str
    chat_id: int
    choices: dict[str, str]
    message_id: int | None = None


class ApprovalUI:
    def __init__(self, bot, owner_id, respond):
        self.bot, self.owner_id, self.respond = bot, owner_id, respond
        self.pending: dict[str, _Card] = {}

    async def _dismiss(self, card):
        if card.message_id is None:
            return
        try:
            await asyncio.wait_for(self.bot.edit_message_reply_markup(chat_id=card.chat_id,
                message_id=card.message_id, reply_markup=None), 2)
        except Exception:
            pass  # The local token is already invalid, even if stale buttons remain visible.

    async def show(self, chat_id, request):
        if request.method == 'cancel':
            for token, card in list(self.pending.items()):
                if card.request_id == request.target_id:
                    self.pending.pop(token, None)
                    await self._dismiss(card)
            return
        choices = _choices(request)
        text = request.title or ''
        if 'session' in choices:
            text += '\n\nSession: ' + choices['session']
        if (chat_id != self.owner_id() or not choices
                or len(text.encode('utf-16-le')) // 2 > 4096):
            await self.respond(request.id, 'Deny')
            return
        token = secrets.token_hex(12)
        card = self.pending[token] = _Card(request.id, chat_id, choices)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=action.title(), callback_data=f'approval:{token}:{action}')
            for action in choices]])
        try:
            message = await asyncio.wait_for(self.bot.send_message(chat_id=chat_id, text=text,
                parse_mode=None, reply_markup=keyboard), 5)
            card.message_id = message.message_id
        except asyncio.CancelledError:
            self.pending.pop(token, None)
            raise
        except Exception:
            self.pending.pop(token, None)
            await self.respond(request.id, 'Deny')

    async def handle(self, query):
        parts = (query.data or '').split(':')
        card = self.pending.get(parts[1]) if len(parts) == 3 else None
        message = query.message
        if (card is None or parts[0] != 'approval' or parts[2] not in card.choices
                or query.from_user.id != self.owner_id() or message is None
                or message.chat.type != 'private' or message.chat.id != card.chat_id
                or message.message_id != card.message_id):
            await self.bot.answer_callback_query(callback_query_id=query.id, text='Запит недоступний.')
            return
        self.pending.pop(parts[1])
        async def decide():
            try:
                accepted = await self.respond(card.request_id, card.choices[parts[2]])
                status = parts[2].title() if accepted else 'Запит уже завершено.'
            except EngineError:
                status = 'Не вдалося підтвердити рішення OMP.'
            finally:
                await self._dismiss(card)
            await self.bot.answer_callback_query(callback_query_id=query.id, text=status)
        await complete_cleanup(decide())

    async def finish(self):
        cards = list(self.pending.values())
        self.pending.clear()
        await asyncio.gather(*(self._dismiss(card) for card in cards))
