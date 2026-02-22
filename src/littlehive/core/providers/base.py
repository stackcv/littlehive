from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(slots=True)
class ProviderRequest:
    provider: str
    model: str
    prompt: str


@dataclass(slots=True)
class ProviderResponse:
    provider: str
    model: str
    output_text: str
    raw: dict


class ProviderAdapter(ABC):
    name: str

    @abstractmethod
    def generate(self, request: ProviderRequest) -> ProviderResponse:
        raise NotImplementedError
