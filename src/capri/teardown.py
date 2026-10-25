"""The pinned official SDK's confirmed-child-teardown contract."""
import asyncio


async def join_cleanup(task):
    """Join a protected task while already unwinding cancellation.

    A second cancellation must not abandon a synchronous lifecycle worker.
    The caller preserves/raises its original CancelledError after recording safety.
    """
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.cancelled():
                raise
    return task.result()


async def complete_cleanup(awaitable):
    """Finish all cleanup, including state updates, before propagating cancellation."""
    task = asyncio.create_task(awaitable)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await join_cleanup(task)
        raise


def stop_child(client) -> bool:
    """True means reaped, including retained survivors; any other outcome is unsafe.

    Audited source: omp-rpc at 45c35e40c46166dc726ccc52f5d27f40f2449f99.
    stop() retains surviving handles even after clearing its active process.
    Callers must serialize this blocking operation and join their prompt worker.
    """
    try:
        return client.stop() is True
    except Exception:
        return False
