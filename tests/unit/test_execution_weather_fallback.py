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
        if tool_name == "weather.get":
            raise RuntimeError("weather tool not configured")
        return {"status": "ok"}


def _register(registry: ToolRegistry, name: str) -> None:
    registry.register(
        ToolMetadata(
            name=name,
            tags=["test"],
            routing_summary=f"route {name}",
            invocation_summary=f"invoke {name}",
            full_schema={"type": "object", "properties": {}},
        ),
        lambda ctx, args: {"ok": True},
    )


def test_weather_error_is_recorded_when_unconfigured():
    registry = ToolRegistry()
    _register(registry, "weather.get")

    ex = _ExecutorStub()
    agent = ExecutionAgent(tool_registry=registry, tool_executor=ex)

    transfer = Transfer(
        target_agent="execution_agent",
        subtask="fetch weather",
        input_summary="what is the weather in Pune today",
        budget=TransferBudget(max_input_tokens=400, reserved_output_tokens=128),
        trace_context=TransferTraceContext(request_id="r1", task_id="t1", session_id="s1"),
    )
    ctx = ToolCallContext(session_db_id=1, user_db_id=1, task_id=1, trace_id="tr1")

    result = agent.execute_from_transfer(transfer, ctx)

    assert result.selected_tools[0] == "weather.get"
    assert ex.calls[0][0] == "weather.get"
    assert len(ex.calls) == 1
    assert any(
        isinstance(item, dict) and item.get("status") == "error" and item.get("tool_name") == "weather.get"
        for item in result.outputs
    )
