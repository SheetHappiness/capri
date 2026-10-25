"""One explicitly paired owner's private text messages."""
import asyncio
from pathlib import Path
import secrets
from collections import deque
from contextlib import suppress
from aiogram import Bot, Dispatcher, F, Router
from .config import Pairing
from .engine import Engine
from .telegram import deliver


class InboundFlow:
    """One owner, one response consumer, FIFO overflow and a short steer debounce."""
    def __init__(self, bot, engine, *, debounce=0.5):
        self.bot = bot
        self.engine = engine
        self.debounce = debounce
        self.pending = deque()
        self.worker = None
        self.burst = None
        self.responding = False
        self.steer_available = True
        self.last_input = 0.0
        self.submitting = False

    def submit(self, chat_id, text):
        self.pending.append((chat_id, text))
        self.last_input = asyncio.get_running_loop().time()
        if self.worker is None or self.worker.done():
            self.worker = asyncio.create_task(self._drain())
        elif self.responding and self.steer_available:
            if self.burst is None or self.burst.done():
                self.burst = asyncio.create_task(self._steer_after_pause())

    async def _steer_after_pause(self):
        while self.responding and self.pending and self.steer_available:
            delay = self.last_input + self.debounce - asyncio.get_running_loop().time()
            if delay > 0:
                await asyncio.sleep(delay)
                continue
            batch = list(self.pending)
            self.submitting = True
            try:
                accepted = await self.engine.steer('\n\n'.join(text for _, text in batch))
            except Exception:
                # An uncertain ACK must not be retried as a new prompt.
                for _ in batch:
                    self.pending.popleft()
                self.steer_available = False
                await self.bot.send_message(chat_id=batch[0][0],
                    text='Не вдалося підтвердити доставку уточнення. Перевір відповідь і за потреби надішли його знову.')
                return
            finally:
                self.submitting = False
            if accepted:
                for _ in batch:
                    self.pending.popleft()
            else:
                self.steer_available = False

    async def _drain(self):
        while self.pending:
            chat_id, text = self.pending.popleft()
            self.responding = True
            try:
                await deliver(self.bot, chat_id, self.engine.stream(text),
                    draft_id=secrets.randbelow(2**31-1)+1)
            finally:
                self.responding = False
            if self.burst is not None:
                await self.burst
                self.burst = None

    async def wait(self):
        if self.worker is not None:
            await self.worker

    async def stop(self):
        if self.burst is not None:
            if not self.submitting:
                self.burst.cancel()
            with suppress(asyncio.CancelledError):
                await self.burst
            self.burst = None
        self.pending.clear()
        if self.worker is not None and not self.worker.done():
            self.worker.cancel()
            with suppress(asyncio.CancelledError):
                await self.worker


async def handle_text(message, bot, engine, pairing, lock):
    if message.chat.type != 'private' or message.from_user is None or not message.text:
        return
    user_id = message.from_user.id
    if pairing.accept(user_id, message.text):
        await bot.send_message(chat_id=message.chat.id, text='Capri прив’язано. Напиши повідомлення.')
        return
    if pairing.owner_id != user_id:
        return
    if message.text.strip() == '/stop':
        await lock.stop()
        return
    lock.submit(message.chat.id, message.text)


async def run(token: str, executable: Path, data: Path):
    engine = Engine(executable, data)
    bot = Bot(token)
    dp = Dispatcher()
    pairing = Pairing(data / 'owner.json')
    lock = InboundFlow(bot, engine)
    router = Router()
    @router.message(F.text)
    async def on_text(message):
        await handle_text(message, bot, engine, pairing, lock)
    dp.include_router(router)
    try:
        await engine.start()
        me = await bot.get_me()
        if pairing.nonce:
            command = '/start ' + pairing.nonce
            (data / 'pairing.txt').write_text(command, encoding='utf-8')
            print(f'Pair @{me.username} with: {command}', flush=True)
        else:
            print(f'Capri @{me.username} ready for owner {pairing.owner_id}', flush=True)
        await dp.start_polling(bot, allowed_updates=['message'], close_bot_session=False)
    finally:
        await lock.stop()
        await engine.close()
        await bot.session.close()
