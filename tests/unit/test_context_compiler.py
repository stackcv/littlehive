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


def test_context_compiler_dedupes_recent_turns_and_memories():
    compiler = ContextCompiler()
    turns = [
        ChatTurn(role="assistant", content="I'm a text-based AI and don't have direct access to real-time information."),
        ChatTurn(role="assistant", content="I'm a text-based AI and don't have direct access to real-time information."),
        ChatTurn(role="user", content="weather in bengaluru today?"),
    ]
    memories = [
        "assistant: I'm a text-based AI and don't have direct access to real-time information.",
        "weather in bengaluru today?",
        "user prefers concise answers",
    ]

    compiled = compiler.compile(
        agent_role="reply_agent",
        system_prompt="short",
        user_message="weather in bengaluru today?",
        recent_turns=turns,
        memory_snippets=memories,
        budget=TokenBudget(max_input_tokens=600, reserved_output_tokens=64),
    )

    assert len(compiled.included_turns) == 2
    assert "dedupe_recent_turns" in compiled.trim_actions
    assert "dedupe_memories" in compiled.trim_actions
    assert any("user prefers concise answers" in m for m in compiled.included_memories)
    assert not any("text-based ai" in m.lower() for m in compiled.included_memories)
