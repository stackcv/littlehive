from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from collections.abc import Awaitable
from typing import TypeVar

T = TypeVar("T")


async def run_with_timeout(awaitable: Awaitable[T], timeout_seconds: int) -> T:
    return await asyncio.wait_for(awaitable, timeout=timeout_seconds)


def run_with_timeout_sync(fn, *, timeout_seconds: int):
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(fn)
        try:
            return future.result(timeout=max(1, timeout_seconds))
        except FuturesTimeoutError as exc:
            raise TimeoutError(f"operation timed out after {timeout_seconds}s") from exc
