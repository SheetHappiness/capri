"""Public-text previews and streamed durable bubbles."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress

from aiogram.exceptions import TelegramRetryAfter
from .bubbles import BubbleComposer
from .bubble_protocol import BubbleProtocol


_LIMIT = 4096
_TRUNCATED = '\n\n[Відповідь скорочено через ліміт Telegram.]'
_ERROR = 'Сталася помилка під час відповіді Capri. Спробуй ще раз.'


def _fit(text: str) -> str:
    if len(text.encode('utf-16-le')) // 2 <= _LIMIT:
        return text
    budget = _LIMIT - len(_TRUNCATED.encode('utf-16-le')) // 2
    # Cutting encoded UTF-16 could leave a lone surrogate; ignore only that boundary.
    return text.encode('utf-16-le')[:budget * 2].decode('utf-16-le', errors='ignore') + _TRUNCATED


async def deliver(
    bot,
    chat_id: int,
    text_stream: AsyncIterator[str],
    *,
    draft_id: int,
    interval: float = 0.75,
    min_chars: int = 140,
    soft_max: int = 800,
) -> None:
    """Consume text independently of draft I/O; never retry an uncertain final send."""
    changed = asyncio.Event()
    composer = BubbleComposer(min_chars, soft_max)
    protocol = BubbleProtocol()
    committed = False
    failed = False
    loop = asyncio.get_running_loop()

    async def drafts() -> None:
        next_send = 0.0
        while True:
            await changed.wait()
            delay = next_send - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            snapshot = _fit(composer.pending)
            changed.clear()
            if not snapshot:
                continue
            try:
                await bot.send_message_draft(
                    chat_id=chat_id, draft_id=draft_id, text=snapshot, parse_mode=None,
                )
            except TelegramRetryAfter as exc:
                next_send = loop.time() + max(interval, exc.retry_after)
                changed.set()
            except Exception:
                # Preview failure must not prevent delivery of the final answer.
                # Stop previews for this answer instead of hammering the API.
                return
            else:
                next_send = loop.time() + interval

    sender = asyncio.create_task(drafts())

    async def commit(boundary):
        nonlocal sender, committed, draft_id
        if not boundary:
            return
        if not composer.pending[:boundary].strip():
            composer.pending = composer.pending[boundary:]
            return
        # Join the old preview before sendMessage clears it. Consume only on ACK.
        sender.cancel()
        with suppress(asyncio.CancelledError):
            await sender
        await bot.send_message(chat_id=chat_id, text=_fit(composer.pending[:boundary]), parse_mode=None)
        composer.pending = composer.pending[boundary:]
        committed = True
        draft_id = draft_id % (2**31 - 1) + 1
        changed.clear()
        sender = asyncio.create_task(drafts())

    async def consume(events):
        for event in events:
            if event is None:
                await commit(len(composer.pending))
            else:
                composer.append(event)
                while (boundary := composer.boundary()) is not None:
                    await commit(boundary)
        changed.set()

    try:
        try:
            async for delta in text_stream:
                if delta:
                    await consume(protocol.feed(delta))
                    # A stream can yield synchronously; let its first preview run now.
                    await asyncio.sleep(0)
            await consume(protocol.finish())
        except Exception:
            failed = True
    finally:
        sender.cancel()
        with suppress(asyncio.CancelledError):
            await sender
        close_stream = getattr(text_stream, 'aclose', None)
        if close_stream is not None:
            await close_stream()

    final = _ERROR if failed else composer.pending
    if final.strip() or not committed:
        if not final.strip():
            final = ''
        await bot.send_message(chat_id=chat_id, text=_fit(final or 'Модель не повернула текстової відповіді.'), parse_mode=None)
