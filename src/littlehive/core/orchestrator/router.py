from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RouteDecision:
    target_agent: str


class TaskRouter:
    def route(self, intent: str) -> RouteDecision:
        return RouteDecision(target_agent="orchestrator_agent")
