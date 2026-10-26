"""One owner's private messages and isolated Telegram guest threads."""
import asyncio
import logging
from pathlib import Path
import secrets
from collections import deque
from contextlib import suppress
from aiogram import Bot, Dispatcher, F, Router
from .config import Pairing
from .engine import Engine, SteerResult
from .telegram import deliver
from .guest import GuestService
from .guest_engine import GuestEngine
from .guest_threads import GuestThreadStore, ThreadError
from .engine import EngineError
from .teardown import complete_cleanup, join_cleanup, stop_child
from .permission import handle_permission_callback, show_permission
from .approval import ApprovalUI

log = logging.getLogger(__name__)


class OmpRuntime:
    """Serialize children sharing auth/config; restart the owner lazily after guest."""
    def __init__(self, owner, guest):
        self.owner, self.guest = owner, guest
        self.lock = asyncio.Lock()
        self.owner_ready = True
        self.safe = True

    def _check(self):
        if not self.safe or not self.guest.safe or not getattr(self.owner, 'safe', True):
            raise EngineError('OMP teardown unconfirmed; restart Capri')

    async def stream(self, text):
        async with self.lock:
            self._check()
            if not self.owner_ready:
                start = asyncio.create_task(self.owner.start())
                try:
                    await asyncio.shield(start)
                except asyncio.CancelledError:
                    try:
                        await join_cleanup(start)
                    except Exception:
                        pass
                    finally:
                        if self.owner.client is not None:
                            self.safe = False
                            try:
                                stop = asyncio.create_task(asyncio.to_thread(stop_child, self.owner.client))
                                self.safe = await join_cleanup(stop)
                            except Exception:
                                self.safe = False
                            if self.safe: self.owner.client = None
                    raise
                self.owner_ready = True
            stream = self.owner.stream(text)
            try:
                async for part in stream: yield part
            finally:
                await stream.aclose()

    async def steer(self, text):
        if not self.owner_ready or self.lock.locked() and not self.owner._active:
            return SteerResult.NOT_ACTIVE
        return await self.owner.steer(text)

    async def answer_approval(self, request_id, value):
        # The turn holds runtime.lock while OMP awaits this UI response.
        if not self.owner_ready or not self.safe:
            return False
        return await self.owner.answer_approval(request_id, value)

    async def permission(self, mode=None):
        if self.lock.locked():
            raise EngineError('Спершу дочекайся завершення відповіді або надішли /stop.')
        async with self.lock:
            self._check()
            async def configure():
                if mode is not None and self.owner_ready:
                    # Reap before saving: no idle child's pending settings save
                    # can race this update. The next DM resumes the same session.
                    self.safe = False
                    self.owner_ready = False
                    self.safe = await asyncio.to_thread(stop_child, self.owner.client)
                    if self.safe:
                        self.owner.client = None
                    self._check()
                return await self.owner.permission(mode)
            return await complete_cleanup(configure())

    async def stream_guest(self, directory, **kwargs):
        async with self.lock:
            self._check()
            if self.owner_ready:
                self.safe = False
                stop = asyncio.create_task(asyncio.to_thread(stop_child, self.owner.client))
                try:
                    self.safe = await asyncio.shield(stop)
                except asyncio.CancelledError:
                    try:
                        self.safe = await join_cleanup(stop)
                    except Exception:
                        self.safe = False
                    finally:
                        self.owner_ready = False
                        if self.safe: self.owner.client = None
                    raise
                except Exception:
                    self.safe = False
                self.owner_ready = False
                self._check()
                self.owner.client = None
            stream = self.guest.stream(directory, **kwargs)
            try:
                async for part in stream: yield part
            finally:
                await stream.aclose()


class InboundFlow:
    """One owner, one response consumer, FIFO overflow and a short steer debounce."""
    def __init__(self, bot, engine, *, debounce=0.5, approvals=None):
        self.bot = bot
        self.engine = engine
        self.approvals = approvals
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
                result = await self.engine.steer('\n\n'.join(text for _, text in batch))
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
            if result is SteerResult.ACCEPTED:
                for _ in batch:
                    self.pending.popleft()
            else:
                if result is SteerResult.UNSUPPORTED:
                    self.steer_available = False
                # A finished turn leaves the batch for the normal FIFO drain.
                return

    async def _drain(self):
        while self.pending:
            chat_id, text = self.pending.popleft()
            self.responding = True
            try:
                await deliver(self.bot, chat_id, self.engine.stream(text),
                    draft_id=secrets.randbelow(2**31-1)+1, approvals=self.approvals)
            finally:
                self.responding = False
            if self.burst is not None:
                await self.burst
                self.burst = None

    async def wait(self):
        if self.worker is not None:
            await self.worker

    async def stop(self):
        self.pending.clear()
        # Cancel both before joining either: a steer ACK must never delay abort.
        tasks = [task for task in (self.burst, self.worker) if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        self.burst = None


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
    parts = message.text.strip().split(maxsplit=1)
    if parts and parts[0] in ('/permission', '/permissions'):
        await show_permission(bot, message.chat.id, engine,
                              parts[1] if len(parts) > 1 else None)
        return
    lock.submit(message.chat.id, message.text)


async def run(token: str, executable: Path, data: Path):
    engine = Engine(executable, data)
    bot = Bot(token)
    dp = Dispatcher()
    pairing = Pairing(data / 'owner.json')
    runtime = OmpRuntime(engine, GuestEngine(executable, data))
    approvals = ApprovalUI(bot, lambda: pairing.owner_id, runtime.answer_approval)
    lock = InboundFlow(bot, runtime, approvals=approvals)
    guest = None
    owner_handlers = set()
    stopping = False
    router = Router()
    async def owner_handler(handler, *args):
        if stopping:
            return
        task = asyncio.current_task()
        owner_handlers.add(task)
        try:
            return await handler(*args)
        finally:
            owner_handlers.discard(task)
    @router.message(F.text)
    async def on_text(message):
        await owner_handler(handle_text, message, bot, runtime, pairing, lock)
    @router.guest_message()
    async def on_guest(message):
        if guest is not None:
            await guest.handle(message)
    @router.callback_query(F.data.startswith('permission:'))
    async def on_permission(query):
        await owner_handler(handle_permission_callback, query, bot, runtime, pairing)
    @router.callback_query(F.data.startswith('approval:'))
    async def on_approval(query):
        await owner_handler(approvals.handle, query)
    dp.include_router(router)
    try:
        await engine.start()
        me = await bot.get_me()
        capability = getattr(me, 'supports_guest_queries', None)
        print(f'Guest Mode supports_guest_queries={capability}', flush=True)
        if capability is True:
            try:
                guest = GuestService(bot, lambda: pairing.owner_id, me.username,
                                     GuestThreadStore(data), runtime)
            except (ThreadError, OSError):
                print('Guest Mode unavailable: guest thread store is invalid; DM remains enabled.', flush=True)
        else:
            print('Enable Guest Mode in @BotFather → Bot Settings. DM remains enabled.', flush=True)
        if pairing.nonce:
            command = '/start ' + pairing.nonce
            (data / 'pairing.txt').write_text(command, encoding='utf-8')
            print(f'Pair @{me.username} with: {command}', flush=True)
        else:
            print(f'Capri @{me.username} ready for owner {pairing.owner_id}', flush=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), close_bot_session=False)
    finally:
        stopping = True
        async def cleanup():
            handlers = list(owner_handlers)
            for task in handlers:
                task.cancel()
            try:
                if guest is not None:
                    await guest.close()
                await lock.stop()
            finally:
                # aiogram does not join detached update handlers on polling
                # shutdown. A permission save must finish before closing OMP.
                await asyncio.gather(*handlers, return_exceptions=True)
                try:
                    await engine.close()
                finally:
                    await bot.session.close()
        await complete_cleanup(cleanup())
