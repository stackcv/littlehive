from littlehive.core.agents.base import Agent


class OrchestratorAgent(Agent):
    agent_id = "orchestrator_agent"

    def run(self, payload: dict) -> dict:
        return payload
