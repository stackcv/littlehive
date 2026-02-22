from __future__ import annotations

import asyncio

import pytest

from littlehive.core.runtime.locks import SessionLockManager


@pytest.mark.asyncio
async def test_session_lock_serializes_same_session_work():
    manager = SessionLockManager()
    lock = await manager.get_lock("telegram:1")
    events: list[str] = []

    async def worker(name: str, hold: float) -> None:
        local_lock = await manager.get_lock("telegram:1")
        async with local_lock:
            events.append(f"{name}:start")
            await asyncio.sleep(hold)
            events.append(f"{name}:end")

    async with lock:
        t = asyncio.create_task(worker("second", 0.01))
        await asyncio.sleep(0.02)
        events.append("first:end")
    await t

    assert events[0] == "first:end"
    assert events[1] == "second:start"
    assert events[2] == "second:end"
