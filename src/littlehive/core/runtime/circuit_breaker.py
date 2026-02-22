from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(slots=True)
class BreakerState:
    state: str = "closed"
    failure_count: int = 0
    success_count: int = 0
    last_failure_ts: datetime | None = None


class CircuitBreaker:
    def __init__(self, *, failure_threshold: int = 3, cool_down_seconds: int = 20) -> None:
        self.failure_threshold = max(1, failure_threshold)
        self.cool_down_seconds = max(1, cool_down_seconds)
        self.state = BreakerState()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def allow(self) -> bool:
        if self.state.state == "closed":
            return True
        if self.state.state == "open":
            if self.state.last_failure_ts is None:
                return False
            if self._now() - self.state.last_failure_ts >= timedelta(seconds=self.cool_down_seconds):
                self.state.state = "half_open"
                return True
            return False
        if self.state.state == "half_open":
            return True
        return True

    def record_success(self) -> None:
        self.state.success_count += 1
        self.state.failure_count = 0
        self.state.state = "closed"

    def record_failure(self) -> None:
        self.state.failure_count += 1
        self.state.last_failure_ts = self._now()
        if self.state.state == "half_open":
            self.state.state = "open"
            return
        if self.state.failure_count >= self.failure_threshold:
            self.state.state = "open"

    def snapshot(self) -> dict:
        return {
            "state": self.state.state,
            "failure_count": self.state.failure_count,
            "success_count": self.state.success_count,
            "last_failure_ts": self.state.last_failure_ts.isoformat() if self.state.last_failure_ts else None,
        }


class BreakerRegistry:
    def __init__(self, *, failure_threshold: int = 3, cool_down_seconds: int = 20) -> None:
        self.failure_threshold = failure_threshold
        self.cool_down_seconds = cool_down_seconds
        self._breakers: dict[str, CircuitBreaker] = {}

    def for_key(self, key: str) -> CircuitBreaker:
        if key not in self._breakers:
            self._breakers[key] = CircuitBreaker(
                failure_threshold=self.failure_threshold,
                cool_down_seconds=self.cool_down_seconds,
            )
        return self._breakers[key]

    def snapshot(self) -> dict[str, dict]:
        return {k: b.snapshot() for k, b in self._breakers.items()}
