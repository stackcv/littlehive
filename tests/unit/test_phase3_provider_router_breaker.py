from __future__ import annotations

import pytest

from littlehive.core.providers.base import ProviderAdapter, ProviderRequest, ProviderResponse
from littlehive.core.providers.router import ProviderRouter


class AlwaysFailProvider(ProviderAdapter):
    name = "p_fail"

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        _ = request
        raise TimeoutError("provider timeout")

    def health(self) -> bool:
        return True


class GoodProvider(ProviderAdapter):
    name = "p_good"

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(provider=self.name, model=request.model, output_text="ok", raw={})

    def health(self) -> bool:
        return True


def test_router_skips_provider_with_open_breaker():
    router = ProviderRouter()
    router.register(AlwaysFailProvider())
    router.register(GoodProvider())

    req = ProviderRequest(model="m", prompt="hello")
    out = router.dispatch_with_fallback(req, provider_order=["p_fail", "p_good"])
    assert out.output_text == "ok"

    # Repeated failures should open breaker for failing provider.
    for _ in range(3):
        with pytest.raises(RuntimeError):
            router.dispatch_with_fallback(req, provider_order=["p_fail"])

    status = router.provider_status()["p_fail"]["breaker"]["state"]
    assert status in {"open", "half_open"}
