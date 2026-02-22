from __future__ import annotations

from littlehive.core.providers.base import ProviderAdapter, ProviderRequest, ProviderResponse


class OpenAICompatibleAdapter(ProviderAdapter):
    name = "openai_compatible"

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(
            provider=self.name,
            model=request.model,
            output_text="stubbed",
            raw={"phase": 0},
        )
