from __future__ import annotations

import os
from time import perf_counter

import httpx
from pydantic import BaseModel

from littlehive.core.config.schema import AppConfig
from littlehive.core.providers.router import ProviderRouter


class ProviderCheckResult(BaseModel):
    provider: str
    enabled: bool
    ok: bool
    latency_ms: float | None = None
    error: str | None = None


def provider_health_summary(router: ProviderRouter) -> dict[str, bool]:
    return router.health()


def provider_detailed_summary(router: ProviderRouter) -> dict[str, dict]:
    return router.provider_status()


def check_configured_providers(cfg: AppConfig, skip_tests: bool = False, timeout_seconds: float = 4.0) -> dict[str, ProviderCheckResult]:
    results: dict[str, ProviderCheckResult] = {}

    local = cfg.providers.local_compatible
    if not local.enabled:
        results["local_compatible"] = ProviderCheckResult(provider="local_compatible", enabled=False, ok=False, error="disabled")
    elif skip_tests:
        results["local_compatible"] = ProviderCheckResult(provider="local_compatible", enabled=True, ok=False, error="skipped")
    else:
        base = (local.base_url or "").rstrip("/")
        if not base:
            results["local_compatible"] = ProviderCheckResult(
                provider="local_compatible", enabled=True, ok=False, error="missing base_url"
            )
        else:
            headers = {"Content-Type": "application/json"}
            if local.api_key_env and os.getenv(local.api_key_env):
                headers["Authorization"] = f"Bearer {os.getenv(local.api_key_env, '')}"
            started = perf_counter()
            try:
                with httpx.Client(timeout=timeout_seconds) as client:
                    resp = client.get(f"{base}/models", headers=headers)
                    resp.raise_for_status()
                results["local_compatible"] = ProviderCheckResult(
                    provider="local_compatible",
                    enabled=True,
                    ok=True,
                    latency_ms=round((perf_counter() - started) * 1000, 2),
                )
            except Exception as exc:  # noqa: BLE001
                results["local_compatible"] = ProviderCheckResult(
                    provider="local_compatible",
                    enabled=True,
                    ok=False,
                    latency_ms=round((perf_counter() - started) * 1000, 2),
                    error=str(exc),
                )

    groq = cfg.providers.groq
    if not groq.enabled:
        results["groq"] = ProviderCheckResult(provider="groq", enabled=False, ok=False, error="disabled")
    elif skip_tests:
        results["groq"] = ProviderCheckResult(provider="groq", enabled=True, ok=False, error="skipped")
    else:
        if not groq.api_key_env or not os.getenv(groq.api_key_env):
            results["groq"] = ProviderCheckResult(
                provider="groq", enabled=True, ok=False, error="missing api key in env"
            )
        else:
            started = perf_counter()
            try:
                with httpx.Client(timeout=timeout_seconds) as client:
                    resp = client.get(
                        "https://api.groq.com/openai/v1/models",
                        headers={
                            "Authorization": f"Bearer {os.getenv(groq.api_key_env, '')}",
                            "Content-Type": "application/json",
                        },
                    )
                    resp.raise_for_status()
                results["groq"] = ProviderCheckResult(
                    provider="groq",
                    enabled=True,
                    ok=True,
                    latency_ms=round((perf_counter() - started) * 1000, 2),
                )
            except Exception as exc:  # noqa: BLE001
                results["groq"] = ProviderCheckResult(
                    provider="groq",
                    enabled=True,
                    ok=False,
                    latency_ms=round((perf_counter() - started) * 1000, 2),
                    error=str(exc),
                )

    return results
