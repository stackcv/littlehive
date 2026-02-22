from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ProviderRequest:
    model: str
    prompt: str
    temperature: float = 0.2
    max_output_tokens: int = 256
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProviderResponse:
    provider: str
    model: str
    output_text: str
    raw: dict[str, Any]


class ProviderAdapter(ABC):
    name: str

    @abstractmethod
    def generate(self, request: ProviderRequest) -> ProviderResponse:
        raise NotImplementedError

    @abstractmethod
    def health(self) -> bool:
        raise NotImplementedError
