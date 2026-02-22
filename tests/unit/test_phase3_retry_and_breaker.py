from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from littlehive.core.runtime.circuit_breaker import CircuitBreaker
from littlehive.core.runtime.errors import classify_error
from littlehive.core.runtime.retries import RetryPolicy, run_with_retry_sync


def test_retry_classification_and_bounded_attempts():
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        raise TimeoutError("timeout on provider")

    with pytest.raises(RuntimeError, match="retries_exhausted"):
        run_with_retry_sync(
            flaky,
            policy=RetryPolicy(max_attempts=2, base_backoff_seconds=0.0, jitter_seconds=0.0),
            category="provider",
            component="p1",
        )
    assert attempts["n"] == 2

    info = classify_error(ValueError("unauthorized auth error"), category="provider", component="p1")
    assert info.retryable is False


def test_circuit_breaker_state_transitions():
    br = CircuitBreaker(failure_threshold=2, cool_down_seconds=1)
    assert br.allow() is True
    br.record_failure()
    assert br.state.state == "closed"
    br.record_failure()
    assert br.state.state == "open"
    assert br.allow() is False

    br.state.last_failure_ts = datetime.now(timezone.utc) - timedelta(seconds=2)
    assert br.allow() is True
    assert br.state.state == "half_open"
    br.record_success()
    assert br.state.state == "closed"
