from __future__ import annotations

from collections.abc import Callable
from time import perf_counter

from littlehive.core.providers.base import ProviderAdapter, ProviderRequest, ProviderResponse
from littlehive.core.runtime.circuit_breaker import BreakerRegistry
from littlehive.core.runtime.errors import ErrorInfo
from littlehive.core.runtime.retries import RetryPolicy, run_with_retry_sync


class ProviderRouter:
    def __init__(
        self,
        *,
        retry_policy: RetryPolicy | None = None,
        breaker_registry: BreakerRegistry | None = None,
    ) -> None:
        self._adapters: dict[str, ProviderAdapter] = {}
        self._stats: dict[str, dict[str, float | int]] = {}
        self.retry_policy = retry_policy or RetryPolicy(max_attempts=2, base_backoff_seconds=0.08, jitter_seconds=0.04)
        self.breakers = breaker_registry or BreakerRegistry(failure_threshold=3, cool_down_seconds=25)

    def register(self, adapter: ProviderAdapter) -> None:
        self._adapters[adapter.name] = adapter
        self._stats.setdefault(adapter.name, {"success": 0, "failure": 0, "latency_ms": 0.0})

    def configured(self) -> list[str]:
        return sorted(self._adapters.keys())

    def health(self) -> dict[str, bool]:
        out: dict[str, bool] = {}
        for name, adapter in self._adapters.items():
            breaker_ok = self.breakers.for_key(f"provider:{name}").allow()
            out[name] = bool(adapter.health() and breaker_ok)
        return out

    def provider_scores(self) -> dict[str, float]:
        scores: dict[str, float] = {}
        for name in self.configured():
            st = self._stats.get(name, {})
            success = float(st.get("success", 0))
            failure = float(st.get("failure", 0))
            latency = float(st.get("latency_ms", 0.0))
            breaker = self.breakers.for_key(f"provider:{name}").snapshot()["state"]
            score = 100.0 + success * 2.0 - failure * 4.0 - (latency / 25.0)
            if breaker == "open":
                score -= 1000.0
            elif breaker == "half_open":
                score -= 50.0
            scores[name] = round(score, 3)
        return scores

    def provider_status(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        scores = self.provider_scores()
        for name in self.configured():
            out[name] = {
                "health": self._adapters[name].health(),
                "score": scores[name],
                "breaker": self.breakers.for_key(f"provider:{name}").snapshot(),
                "stats": self._stats.get(name, {}),
            }
        return out

    def dispatch_with_fallback(
        self,
        request: ProviderRequest,
        provider_order: list[str],
        call_logger: Callable[[str, str, str], None] | None = None,
    ) -> ProviderResponse:
        errors: list[str] = []

        ranked_names = [n for n in provider_order if n in self._adapters]
        scores = self.provider_scores()
        ranked_names.sort(key=lambda n: scores.get(n, -99999), reverse=True)

        for provider_name in ranked_names:
            adapter = self._adapters.get(provider_name)
            if adapter is None:
                errors.append(f"{provider_name}:not_registered")
                continue

            breaker = self.breakers.for_key(f"provider:{provider_name}")
            if not breaker.allow():
                errors.append(f"{provider_name}:circuit_open")
                if call_logger:
                    call_logger(provider_name, request.model, "blocked_by_breaker")
                continue

            started = perf_counter()
            try:
                def _on_attempt(attempt: int, status: str, info: ErrorInfo | None) -> None:
                    if call_logger:
                        if attempt > 1:
                            call_logger(provider_name, request.model, f"retry_{status}_{attempt}")

                response = run_with_retry_sync(
                    lambda: adapter.generate(request),
                    policy=self.retry_policy,
                    category="provider",
                    component=provider_name,
                    on_attempt=_on_attempt,
                )
                elapsed = (perf_counter() - started) * 1000
                self._stats[provider_name]["success"] = int(self._stats[provider_name]["success"]) + 1
                self._stats[provider_name]["latency_ms"] = round(elapsed, 3)
                breaker.record_success()
                if call_logger:
                    call_logger(provider_name, request.model, "ok")
                return response
            except Exception as exc:  # noqa: BLE001
                self._stats[provider_name]["failure"] = int(self._stats[provider_name]["failure"]) + 1
                breaker.record_failure()
                errors.append(f"{provider_name}:{exc}")
                if call_logger:
                    call_logger(provider_name, request.model, "error")

        raise RuntimeError("all providers failed: " + " | ".join(errors))
