from __future__ import annotations

from dataclasses import dataclass

from littlehive.core.tools.base import ToolCallContext
from littlehive.core.tools.executor import ToolExecutor


@dataclass(slots=True)
class MemoryAgentOutput:
    snippets: list[str]
    wrote_memory: bool


class MemoryAgent:
    agent_id = "memory_agent"

    def __init__(self, tool_executor: ToolExecutor) -> None:
        self.tool_executor = tool_executor

    def handle(self, ctx: ToolCallContext, user_text: str, search: bool, write: bool, top_k: int) -> MemoryAgentOutput:
        snippets: list[str] = []
        if search:
            result = self.tool_executor.execute("memory.search", ctx, {"query": user_text, "top_k": top_k})
            snippets = [item["content"] for item in result.get("items", [])]

        wrote = False
        if write and user_text:
            write_result = self.tool_executor.execute("memory.write", ctx, {"content": user_text})
            wrote = write_result.get("status") == "ok"

        return MemoryAgentOutput(snippets=snippets, wrote_memory=wrote)
