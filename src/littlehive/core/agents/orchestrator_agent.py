from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class OrchestratorDecision:
    intent: str
    should_search_memory: bool
    should_write_memory: bool


class OrchestratorAgent:
    agent_id = "orchestrator_agent"

    def decide(self, user_text: str) -> OrchestratorDecision:
        text = user_text.lower()
        if text.startswith("/status") or "status" in text:
            return OrchestratorDecision(intent="status", should_search_memory=False, should_write_memory=False)
        if "remember" in text or text.startswith("/memory"):
            return OrchestratorDecision(intent="memory", should_search_memory=True, should_write_memory=True)
        return OrchestratorDecision(intent="chat", should_search_memory=True, should_write_memory=False)
