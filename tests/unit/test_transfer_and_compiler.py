from __future__ import annotations

from littlehive.core.agents.planner_agent import PlannerAgent
from littlehive.core.context.budget import TokenBudget
from littlehive.core.context.compiler import ChatTurn, ContextCompiler
from littlehive.core.tools.base import ToolMetadata
from littlehive.core.tools.registry import ToolRegistry


def _noop(ctx, args):
    _ = (ctx, args)
    return {"ok": True}


def test_transfer_object_routes_to_execution_agent():
    planner = PlannerAgent()
    out = planner.plan(
        user_text="please use memory tools to remember this",
        session_id="1",
        task_id="1",
        request_id="r1",
        max_input_tokens=600,
        reserved_output_tokens=120,
    )
    assert out.transfer is not None
    assert out.transfer.target_agent == "execution_agent"


def test_context_compiler_v2_trim_order_and_schema_controls():
    registry = ToolRegistry()
    registry.register(
        ToolMetadata(
            name="memory.search",
            tags=["memory"],
            routing_summary="search memory",
            invocation_summary="memory.search(query)",
            full_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        ),
        _noop,
    )

    compiler = ContextCompiler()
    turns = [ChatTurn(role="user", content="x" * 120) for _ in range(5)]
    memories = ["m" * 120 for _ in range(5)]

    compiled = compiler.compile(
        agent_role="reply_agent",
        system_prompt="short",
        user_message="y" * 200,
        recent_turns=turns,
        memory_snippets=memories,
        budget=TokenBudget(max_input_tokens=80, reserved_output_tokens=20),
        tool_context_mode="routing",
        tool_registry=registry,
        tool_query="memory",
    )
    assert compiled.preflight is not None
    assert compiled.preflight.allowed or compiled.over_budget
    if compiled.trim_actions:
        assert compiled.trim_actions[0] in {"dedupe_recent_turns", "dedupe_memories", "drop_memory_card", "drop_oldest_recent_turn"}
    assert "tool_full_schema" not in compiled.prompt_text

    compiled_full = compiler.compile(
        agent_role="execution_agent",
        system_prompt="short",
        user_message="run",
        recent_turns=[],
        memory_snippets=[],
        budget=TokenBudget(max_input_tokens=120, reserved_output_tokens=20),
        tool_context_mode="full_for_selected",
        selected_tool_names=["memory.search"],
        tool_registry=registry,
        tool_query="memory",
    )
    assert "tool_full_schema" in compiled_full.prompt_text
