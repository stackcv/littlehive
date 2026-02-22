from __future__ import annotations

from abc import ABC, abstractmethod


class Agent(ABC):
    agent_id: str

    @abstractmethod
    def run(self, payload: dict) -> dict:
        raise NotImplementedError
