from __future__ import annotations

from collections.abc import Callable

from littlehive.core.providers.base import ProviderAdapter, ProviderRequest, ProviderResponse


class ProviderRouter:
    def __init__(self) -> None:
        self._adapters: dict[str, ProviderAdapter] = {}

    def register(self, adapter: ProviderAdapter) -> None:
        self._adapters[adapter.name] = adapter

    def configured(self) -> list[str]:
        return sorted(self._adapters.keys())

    def health(self) -> dict[str, bool]:
        return {name: adapter.health() for name, adapter in self._adapters.items()}

    def dispatch_with_fallback(
        self,
        request: ProviderRequest,
        provider_order: list[str],
        call_logger: Callable[[str, str, str], None] | None = None,
    ) -> ProviderResponse:
        errors: list[str] = []
        for provider_name in provider_order:
            adapter = self._adapters.get(provider_name)
            if adapter is None:
                errors.append(f"{provider_name}:not_registered")
                continue
            try:
                response = adapter.generate(request)
                if call_logger:
                    call_logger(provider_name, request.model, "ok")
                return response
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{provider_name}:{exc}")
                if call_logger:
                    call_logger(provider_name, request.model, "error")

        raise RuntimeError("all providers failed: " + " | ".join(errors))
