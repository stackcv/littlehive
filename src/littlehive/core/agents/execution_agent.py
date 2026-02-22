from littlehive.core.agents.base import Agent


class ExecutionAgent(Agent):
    agent_id = "execution_agent"

    def run(self, payload: dict) -> dict:
        return payload
