"""Owner-only Telegram controls for OMP's native approval setting."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest

from .config import APPROVAL_MODES
from .engine import EngineError


async def show_permission(bot, chat_id, runtime, mode=None, *, message_id=None):
    if mode is not None and mode not in APPROVAL_MODES:
        await bot.send_message(chat_id=chat_id,
            text='Використай /permission або /permission ' + '|'.join(APPROVAL_MODES), parse_mode=None)
        return
    try:
        current = await runtime.permission(mode)
    except EngineError as error:
        await bot.send_message(chat_id=chat_id, text=str(error), parse_mode=None)
        return
    buttons = [InlineKeyboardButton(text=('• ' if value == current else '') + value,
        callback_data='permission:' + value) for value in APPROVAL_MODES]
    menu = InlineKeyboardMarkup(inline_keyboard=[buttons[:2], buttons[2:]])
    text = (f'Режим OMP: {current}\n\n'
        'yolo — без звичайних підтверджень\n'
        'write — питати перед командами\n'
        'always-ask — питати перед змінами й командами\n'
        'always-ask-cached — питати й запам’ятовувати дозволи\n\n'
        'Вибір зберігається між перезапусками.\n'
        'Запити підтвердження з’являються окремо з кнопками Once / Session / Deny.\n'
        'Session доступна лише коли OMP пропонує дозвіл на сесію.')
    if message_id is None:
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=menu, parse_mode=None)
    else:
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                                        text=text, reply_markup=menu, parse_mode=None)
        except TelegramBadRequest as error:
            if 'message is not modified' not in str(error).lower():
                raise


async def handle_permission_callback(query, bot, runtime, pairing):
    message = query.message
    if (pairing.owner_id is None or query.from_user.id != pairing.owner_id
            or message is None or message.chat.type != 'private'
            or message.chat.id != pairing.owner_id):
        await bot.answer_callback_query(callback_query_id=query.id, text='Лише для власника у приватному чаті.')
        return
    prefix, _, mode = (query.data or '').partition(':')
    if prefix != 'permission' or mode not in APPROVAL_MODES:
        await bot.answer_callback_query(callback_query_id=query.id, text='Невідомий режим OMP.')
        return
    await bot.answer_callback_query(callback_query_id=query.id)
    await show_permission(bot, message.chat.id, runtime, mode, message_id=message.message_id)
