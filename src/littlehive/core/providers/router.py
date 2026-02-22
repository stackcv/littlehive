from __future__ import annotations

from littlehive.core.providers.base import ProviderAdapter, ProviderRequest, ProviderResponse


class ProviderRouter:
    def __init__(self) -> None:
        self._adapters: dict[str, ProviderAdapter] = {}

    def register(self, adapter: ProviderAdapter) -> None:
        self._adapters[adapter.name] = adapter

    def dispatch(self, request: ProviderRequest) -> ProviderResponse:
        adapter = self._adapters.get(request.provider)
        if adapter is None:
            raise ValueError(f"Provider '{request.provider}' is not registered")
        return adapter.generate(request)
