"""Owner-only guest turns and local chat-scoped thread commands."""
import asyncio
from datetime import datetime, timezone
import logging
import re
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import InlineQueryResultArticle, InputTextMessageContent
from .guest_progress import ProgressView
from .guest_threads import ThreadError
from .telegram import _fit, _ERROR

log = logging.getLogger(__name__)


class GuestService:
    def __init__(self, bot, owner_id, username, store, runtime, *, interval=0.9, timeout=210, startup_delay=1.2):
        self.bot, self.owner_id, self.store, self.runtime = bot, owner_id, store, runtime
        self.mention = re.compile(r'(?<!\w)@' + re.escape(username) + r'(?!\w)', re.I)
        self.interval, self.timeout = interval, timeout
        self.startup_delay = startup_delay
        self.seen = set()
        self.busy = False
        self.tasks = set()

    async def _answer(self, query_id, text):
        result = InlineQueryResultArticle(id='capri-guest', title='Capri',
            input_message_content=InputTextMessageContent(message_text=_fit(text), parse_mode=None))
        try:
            sent = await self.bot.answer_guest_query(guest_query_id=query_id, result=result)
            log.info('guest: answer_ack')
            inline_id = getattr(sent, 'inline_message_id', None)
            return inline_id if isinstance(inline_id,str) and inline_id else None
        except Exception:
            # Any lost/unknown acknowledgement is terminal for this query.
            log.warning('guest: answer_failed (no retry)')
            return None

    async def _edit(self, inline_id, text):
        try:
            await self.bot.edit_message_text(inline_message_id=inline_id, text=_fit(text), parse_mode=None)
            log.info('guest: edit_ack')
        except TelegramRetryAfter as exc:
            log.warning('guest: edit_rate_limited')
            return max(0,exc.retry_after)
        except TelegramAPIError:
            log.warning('guest: edit_failed')

    def _listing(self, chat):
        threads = self.store.list(chat)
        if not threads: return 'Немає threads у цьому чаті. /newthread [назва]'
        return '\n'.join(f'{"*" if i == 0 else " "} {t.id} – {t.title or "Без назви"}'
                         for i,t in enumerate(threads))

    def _command(self, chat, text):
        parts = text.split(maxsplit=1)
        name = parts[0].lower() if parts else ''
        arg = parts[1].strip() if len(parts)>1 else ''
        if not name.startswith('/'): return None
        if name in ('/threads','/resume') and not arg: return self._listing(chat)
        if name == '/status':
            t = self.store.current(chat)
            if t is None: return 'Немає поточного thread. /newthread [назва]'
            def date(value): return datetime.fromtimestamp(value,timezone.utc).isoformat(timespec='seconds')
            return f'Thread: {t.id}\nTitle: {t.title or "Без назви"}\nCreated: {date(t.created_at)}\nLast active: {date(t.updated_at)}'
        if name not in ('/newthread','/new','/resume','/title'):
            return 'Команди: /newthread [назва], /threads, /resume <ID або назва>, /title <назва>, /status'
        if self.busy: return 'Зачекай завершення поточної відповіді.'
        if name in ('/newthread','/new'): t = self.store.new(chat,arg or None)
        elif name == '/resume': t = self.store.resume(chat,arg)
        elif not arg: return 'Вкажи назву: /title <назва>'
        else: t = self.store.rename_current(chat,arg)
        return f'Thread: {t.id} – {t.title or "Без назви"}'

    async def handle(self, message):
        sender = message.from_user
        if (not message.guest_query_id or sender is None or sender.is_bot
                or message.sender_chat is not None or self.owner_id() != sender.id):
            return
        query_id = message.guest_query_id
        if query_id in self.seen: return
        self.seen.add(query_id)  # Reserve before any network await.
        task = asyncio.current_task()
        self.tasks.add(task)
        try:
            await self._handle_owner(message)
        except (ThreadError,OSError):
            log.warning('guest: store_unavailable')
        finally:
            self.tasks.discard(task)

    async def _handle_owner(self, message):
        query_id, chat = message.guest_query_id, message.chat.id
        text = self.mention.sub('',message.text or message.caption or '').strip()
        try:
            command = self._command(chat,text)
        except ThreadError as exc:
            command = str(exc)
        except OSError:
            command = 'Guest threads тимчасово недоступні.'
        if command is not None:
            await self._answer(query_id,command)
            return
        if self.busy:
            await self._answer(query_id,'Зачекай завершення поточної відповіді.')
            return
        if not text:
            await self._answer(query_id,'Напиши текст запиту після згадки Capri.')
            return
        self.busy = True
        inline_id = None
        attempted = False
        stream = None
        reader = None
        loop = asyncio.get_running_loop()
        next_send = loop.time() + self.startup_delay

        async def publish(text, *, final=False):
            nonlocal inline_id, attempted, next_send
            # One path owns the shared answer/edit budget, including final.
            if final and attempted:
                await asyncio.sleep(max(0, next_send-loop.time()))
            if not attempted:
                attempted = True
                inline_id = await self._answer(query_id,text)
            elif inline_id:
                retry_after = await self._edit(inline_id,text)
                if retry_after is not None:
                    next_send = loop.time() + max(self.interval,retry_after)
                    if not final: return True
                    # Edits are idempotent; retry a final once after explicit 429.
                    # An uncertain answerGuestQuery is never retried.
                    await asyncio.sleep(max(0,next_send-loop.time()))
                    await self._edit(inline_id,text)
            next_send = loop.time() + self.interval
            return bool(inline_id)

        try:
            thread = self.store.ensure_current(chat)
            directory = self.store.session_dir(thread)
            reference = message.reply_to_message
            reference_text = (reference.text or reference.caption) if reference else None
            if reference_text is None and message.quote is not None:
                reference_text = message.quote.text
            view = ProgressView()
            stream = self.runtime.stream_guest(directory,text=text,reference_text=reference_text)
            changed = asyncio.Event()

            async def consume():
                try:
                    async for event in stream:
                        view.accept(event)
                        changed.set()
                        if view.completed: return
                        # Yield to delivery even when the SDK already queued a burst.
                        await asyncio.sleep(0)
                finally:
                    changed.set()

            # Telegram I/O must never hold the token reader. Only delivery is
            # paced; the view continuously receives the newest model snapshot.
            reader = asyncio.create_task(consume())
            async with asyncio.timeout(self.timeout):
                while not view.completed:
                    if reader.done():
                        reader.result()
                        break
                    now = loop.time()
                    if (not attempted and view.has_text) or now >= next_send:
                        if not await publish(view.render()): return
                        continue
                    changed.clear()
                    try:
                        await asyncio.wait_for(changed.wait(), max(0,next_send-loop.time()))
                    except TimeoutError:
                        pass
                if reader.done(): reader.result()
            final = view.final_text if view.completed else ''
            await publish(final or 'Модель не повернула текстової відповіді.', final=True)
            try:
                self.store.touch(chat)
            except (ThreadError,OSError):
                log.warning('guest: activity_timestamp_failed')
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning('guest: turn_failed')
            await publish(_ERROR, final=True)
        finally:
            try:
                if reader is not None:
                    reader.cancel()
                    await asyncio.gather(reader,return_exceptions=True)
                if stream is not None:
                    await stream.aclose()
            finally:
                self.busy = False

    async def close(self):
        tasks = tuple(self.tasks)
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
