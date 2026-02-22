from __future__ import annotations

from littlehive.core.context.budget import TokenBudget
from littlehive.core.context.compiler import ChatTurn, ContextCompiler


def test_context_compiler_trims_when_over_budget():
    compiler = ContextCompiler()
    turns = [ChatTurn(role="user", content="x" * 120) for _ in range(6)]
    memories = ["m" * 120 for _ in range(6)]

    compiled = compiler.compile(
        agent_role="reply_agent",
        system_prompt="short",
        user_message="y" * 160,
        recent_turns=turns,
        memory_snippets=memories,
        budget=TokenBudget(max_input_tokens=80, reserved_output_tokens=32),
    )

    assert compiled.preflight is not None
    assert compiled.preflight.allowed
    assert compiled.preflight.estimated_input_tokens <= 80
    assert compiled.trim_actions
