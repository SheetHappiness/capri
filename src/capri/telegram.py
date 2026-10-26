"""Public-text previews and streamed durable bubbles."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress

from aiogram.exceptions import TelegramRetryAfter
from omp_rpc import ExtensionUiRequest, RpcAgentEvent
from .activity import TurnActivity
from .bubbles import BubbleComposer
from .bubble_protocol import BubbleProtocol
from .teardown import complete_cleanup


_LIMIT = 4096
_TRUNCATED = '\n\n[Відповідь скорочено через ліміт Telegram.]'
_ERROR = 'Сталася помилка під час відповіді Capri. Спробуй ще раз.'
_ACTIVITY_FINISH_TIMEOUT = 2.0


def _fit(text: str) -> str:
    if len(text.encode('utf-16-le')) // 2 <= _LIMIT:
        return text
    budget = _LIMIT - len(_TRUNCATED.encode('utf-16-le')) // 2
    # Cutting encoded UTF-16 could leave a lone surrogate; ignore only that boundary.
    return text.encode('utf-16-le')[:budget * 2].decode('utf-16-le', errors='ignore') + _TRUNCATED


async def deliver(
    bot,
    chat_id: int,
    text_stream: AsyncIterator[str | RpcAgentEvent | ExtensionUiRequest],
    *,
    draft_id: int,
    interval: float = 0.75,
    min_chars: int = 140,
    soft_max: int = 800,
    approvals=None,
) -> None:
    """Route native activity separately; keep text consumption independent of I/O."""
    changed = asyncio.Event()
    composer = BubbleComposer(min_chars, soft_max)
    protocol = BubbleProtocol()
    committed = False
    failed = False
    loop = asyncio.get_running_loop()
    activity = TurnActivity()
    activity_changed = asyncio.Event()
    activity_finished = False

    async def activity_updates() -> None:
        message_id = None
        next_send = 0.0
        last_snapshot = ''
        final_retries = 0
        while True:
            await activity_changed.wait()
            delay = next_send - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            activity_changed.clear()
            snapshot = activity.render()
            if snapshot and snapshot != last_snapshot:
                try:
                    if message_id is None:
                        message = await bot.send_message(chat_id=chat_id, text=snapshot, parse_mode=None)
                        message_id = message.message_id
                    else:
                        await bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                                                    text=snapshot, parse_mode=None)
                except TelegramRetryAfter as exc:
                    # A rejected request is safe to retry, using the latest
                    # state. Bound final retries so activity cannot hold a turn.
                    if activity_finished:
                        final_retries += 1
                        if final_retries > 1:
                            return
                    next_send = loop.time() + max(interval, exc.retry_after)
                    activity_changed.set()
                    continue
                except Exception:
                    # An uncertain initial send may already exist. Never send
                    # a replacement or let a technical preview lose the answer.
                    return
                last_snapshot = snapshot
                next_send = loop.time() + interval
            if activity_finished and snapshot == activity.render():
                return

    activity_sender = asyncio.create_task(activity_updates())

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
                if isinstance(delta, ExtensionUiRequest):
                    if approvals is not None:
                        await approvals.show(chat_id, delta)
                elif isinstance(delta, str) and delta:
                    await consume(protocol.feed(delta))
                elif not isinstance(delta, str):
                    activity.update(delta)
                    activity_changed.set()
                # A stream can yield synchronously; let its previews run now.
                await asyncio.sleep(0)
            await consume(protocol.finish())
        except Exception:
            failed = True
        # No new text is coming. Stop drafts before awaiting the paced activity
        # footer, so protocol.finish() cannot trigger a duplicate final preview.
        sender.cancel()
        activity.finish('failed' if failed else 'done')
        activity_finished = True
        activity_changed.set()
        # A technical view must not hold the answer through a long flood wait
        # or slow API request. wait_for cancels and joins its sender on timeout.
        with suppress(TimeoutError):
            await asyncio.wait_for(activity_sender, _ACTIVITY_FINISH_TIMEOUT)
    finally:
        async def cleanup():
            # Cancel both before joining either, then close the OMP source.
            # Shield the whole cleanup against repeated /stop/shutdown cancels.
            for task in (sender, activity_sender):
                task.cancel()
            for task in (sender, activity_sender):
                with suppress(asyncio.CancelledError):
                    await task
            close_stream = getattr(text_stream, 'aclose', None)
            try:
                if close_stream is not None:
                    await close_stream()
            finally:
                if approvals is not None:
                    await approvals.finish()
        await complete_cleanup(cleanup())

    final = _ERROR if failed else composer.pending
    if final.strip() or not committed:
        if not final.strip():
            final = ''
        await bot.send_message(chat_id=chat_id, text=_fit(final or 'Модель не повернула текстової відповіді.'), parse_mode=None)
