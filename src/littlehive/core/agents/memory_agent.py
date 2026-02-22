from littlehive.core.agents.base import Agent


class MemoryAgent(Agent):
    agent_id = "memory_agent"

    def run(self, payload: dict) -> dict:
        return payload
