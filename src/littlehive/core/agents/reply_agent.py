from littlehive.core.agents.base import Agent


class ReplyAgent(Agent):
    agent_id = "reply_agent"

    def run(self, payload: dict) -> dict:
        return payload
