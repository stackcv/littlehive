from littlehive.core.agents.base import Agent


class PlannerAgent(Agent):
    agent_id = "planner_agent"

    def run(self, payload: dict) -> dict:
        return payload
