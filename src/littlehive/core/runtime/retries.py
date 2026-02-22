from __future__ import annotations

from collections.abc import Awaitable, Callable


async def run_with_retries(fn: Callable[[], Awaitable[str]], attempts: int) -> str:
    last_error: Exception | None = None
    for _ in range(max(1, attempts)):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise RuntimeError(f"retries_exhausted: {last_error}")
