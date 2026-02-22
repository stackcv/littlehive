from __future__ import annotations

import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from littlehive.core.runtime.errors import ErrorInfo, classify_error

T = TypeVar("T")


@dataclass(slots=True)
class RetryPolicy:
    max_attempts: int = 2
    base_backoff_seconds: float = 0.1
    jitter_seconds: float = 0.05


def _sleep_backoff(policy: RetryPolicy, attempt: int) -> None:
    if attempt <= 0:
        return
    delay = policy.base_backoff_seconds * (2 ** (attempt - 1))
    delay += random.uniform(0.0, policy.jitter_seconds)
    time.sleep(min(delay, 0.5))


def run_with_retry_sync(
    fn: Callable[[], T],
    *,
    policy: RetryPolicy,
    category: str,
    component: str,
    on_attempt: Callable[[int, str, ErrorInfo | None], None] | None = None,
) -> T:
    last_error: Exception | None = None
    attempts = max(1, policy.max_attempts)
    for i in range(1, attempts + 1):
        try:
            value = fn()
            if on_attempt:
                on_attempt(i, "ok", None)
            return value
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            info = classify_error(exc, category=category, component=component)
            if on_attempt:
                on_attempt(i, "error", info)
            if (not info.retryable) or i >= attempts:
                break
            _sleep_backoff(policy, i)
    raise RuntimeError(f"retries_exhausted: {last_error}")


async def run_with_retries(fn: Callable[[], Awaitable[str]], attempts: int) -> str:
    last_error: Exception | None = None
    for _ in range(max(1, attempts)):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise RuntimeError(f"retries_exhausted: {last_error}")
