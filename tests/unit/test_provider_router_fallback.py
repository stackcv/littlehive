from __future__ import annotations

import pytest

from littlehive.core.providers.base import ProviderAdapter, ProviderRequest, ProviderResponse
from littlehive.core.providers.router import ProviderRouter


class FailingAdapter(ProviderAdapter):
    name = "p1"

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        _ = request
        raise RuntimeError("boom")

    def health(self) -> bool:
        return False


class SuccessAdapter(ProviderAdapter):
    name = "p2"

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(provider=self.name, model=request.model, output_text="ok", raw={})

    def health(self) -> bool:
        return True


def test_provider_router_fallback_to_second_provider():
    router = ProviderRouter()
    router.register(FailingAdapter())
    router.register(SuccessAdapter())
    calls: list[tuple[str, str]] = []

    response = router.dispatch_with_fallback(
        ProviderRequest(model="m", prompt="hello"),
        provider_order=["p1", "p2"],
        call_logger=lambda provider, model, status: calls.append((provider, status)),
    )

    assert response.output_text == "ok"
    assert calls[-1] == ("p2", "ok")
    assert any(provider == "p1" and status in {"error", "retry_error_2"} for provider, status in calls)


def test_provider_router_raises_when_all_fail():
    router = ProviderRouter()
    router.register(FailingAdapter())
    with pytest.raises(RuntimeError, match="all providers failed"):
        router.dispatch_with_fallback(ProviderRequest(model="m", prompt="hello"), provider_order=["p1"])
