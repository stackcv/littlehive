from __future__ import annotations

from littlehive.core.agents.execution_agent import ExecutionAgent
from littlehive.core.orchestrator.handoff import Transfer, TransferBudget, TransferTraceContext
from littlehive.core.tools.base import ToolCallContext, ToolMetadata
from littlehive.core.tools.registry import ToolRegistry


class _ExecutorStub:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def execute(self, tool_name: str, ctx: ToolCallContext, args: dict) -> dict:
        _ = ctx
        self.calls.append((tool_name, args))
        return {"status": "ok", "tool": tool_name}

    def list_allowed_tool_names(self) -> set[str]:
        return {"weather.get", "memory.write", "status.get"}


def _register(registry: ToolRegistry, name: str, tags: list[str], routing_summary: str, invocation_summary: str) -> None:
    registry.register(
        ToolMetadata(
            name=name,
            tags=tags,
            routing_summary=routing_summary,
            invocation_summary=invocation_summary,
            full_schema={"type": "object", "properties": {}},
        ),
        lambda ctx, args: {"ok": True},
    )


def _transfer(text: str) -> Transfer:
    return Transfer(
        target_agent="execution_agent",
        subtask="execute",
        input_summary=text,
        budget=TransferBudget(max_input_tokens=500, reserved_output_tokens=128),
        trace_context=TransferTraceContext(request_id="r", task_id="t", session_id="s"),
    )


def test_hybrid_semantic_ranking_maps_umbrella_to_weather():
    registry = ToolRegistry()
    _register(registry, "weather.get", ["weather", "rain", "forecast"], "get weather forecast and rain chance", "weather.get(location)")
    _register(registry, "status.get", ["status", "health"], "runtime counters", "status.get()")
    _register(registry, "memory.write", ["memory", "write"], "save preference", "memory.write(content)")

    ex = _ExecutorStub()
    agent = ExecutionAgent(tool_registry=registry, tool_executor=ex)
    ctx = ToolCallContext(session_db_id=10, user_db_id=1, task_id=1, trace_id="tr")

    result = agent.execute_from_transfer(_transfer("Should I carry an umbrella tomorrow?"), ctx)

    assert result.needs_clarification is False
    assert ex.calls
    assert ex.calls[0][0] == "weather.get"


def test_history_aware_followup_prefers_last_successful_tool():
    registry = ToolRegistry()
    _register(registry, "weather.get", ["weather", "forecast"], "weather lookup", "weather.get(location)")
    _register(registry, "status.get", ["status", "health"], "runtime status", "status.get()")
    _register(registry, "memory.write", ["memory", "write"], "save memory", "memory.write(content)")

    ex = _ExecutorStub()

    def history_loader(session_id: int, cap: int) -> list[str]:
        _ = (session_id, cap)
        return ["status.get", "memory.write"]

    agent = ExecutionAgent(tool_registry=registry, tool_executor=ex, history_loader=history_loader)
    ctx = ToolCallContext(session_db_id=10, user_db_id=1, task_id=1, trace_id="tr")

    result = agent.execute_from_transfer(_transfer("Also do that again"), ctx)

    assert result.needs_clarification is False
    assert ex.calls
    assert ex.calls[0][0] == "memory.write"
