from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AgentBase(ABC):
    agent_id: str

    @abstractmethod
    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError
