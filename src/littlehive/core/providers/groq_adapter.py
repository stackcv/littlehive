from __future__ import annotations

import os

import httpx
from tenacity import retry, stop_after_attempt, wait_fixed

from littlehive.core.providers.base import ProviderAdapter, ProviderRequest, ProviderResponse


class GroqAdapter(ProviderAdapter):
    name = "groq"

    def __init__(self, api_key_env: str | None, timeout_seconds: int = 20, default_model: str | None = None) -> None:
        self.api_key_env = api_key_env
        self.timeout_seconds = timeout_seconds
        self.base_url = "https://api.groq.com/openai/v1"
        self.default_model = (default_model or "").strip() or None

    def _headers(self) -> dict[str, str]:
        token = os.getenv(self.api_key_env or "", "")
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    @retry(stop=stop_after_attempt(2), wait=wait_fixed(0.2), reraise=True)
    def generate(self, request: ProviderRequest) -> ProviderResponse:
        model = self.default_model or request.model
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": request.prompt}],
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
        }

        with httpx.Client(timeout=self.timeout_seconds) as client:
            resp = client.post(f"{self.base_url}/chat/completions", json=payload, headers=self._headers())
            resp.raise_for_status()
            body = resp.json()

        text = body.get("choices", [{}])[0].get("message", {}).get("content", "")
        return ProviderResponse(provider=self.name, model=model, output_text=text, raw=body)

    def health(self) -> bool:
        if not os.getenv(self.api_key_env or ""):
            return False
        try:
            with httpx.Client(timeout=3.0) as client:
                response = client.get(f"{self.base_url}/models", headers=self._headers())
                return response.status_code < 500
        except Exception:
            return False
