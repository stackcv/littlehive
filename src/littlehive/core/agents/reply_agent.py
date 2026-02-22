from __future__ import annotations


class ReplyAgent:
    agent_id = "reply_agent"

    def compose(self, *, provider_text: str, user_text: str, memory_snippets: list[str]) -> str:
        if provider_text:
            return provider_text.strip()
        if memory_snippets:
            return f"I found related context: {memory_snippets[0][:160]}"
        return f"Received: {user_text[:220]}"
