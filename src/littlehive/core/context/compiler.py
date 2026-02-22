from __future__ import annotations

from dataclasses import dataclass, field

from littlehive.core.context.budget import TokenBudget, TokenBudgetPreflight, PreflightResult


@dataclass(slots=True)
class ChatTurn:
    role: str
    content: str


@dataclass(slots=True)
class CompiledContext:
    prompt_text: str
    included_turns: list[ChatTurn]
    included_memories: list[str]
    trim_actions: list[str] = field(default_factory=list)
    preflight: PreflightResult | None = None


class ContextCompiler:
    def __init__(self) -> None:
        self.preflight = TokenBudgetPreflight()

    def compile(
        self,
        *,
        agent_role: str,
        system_prompt: str,
        user_message: str,
        recent_turns: list[ChatTurn],
        memory_snippets: list[str],
        budget: TokenBudget,
    ) -> CompiledContext:
        trim_actions: list[str] = []
        turns = list(recent_turns)
        memories = list(memory_snippets)

        def render() -> str:
            turns_text = "\n".join(f"{t.role}: {t.content}" for t in turns)
            mem_text = "\n".join(f"- {m}" for m in memories)
            return (
                f"role={agent_role}\n"
                f"system={system_prompt}\n"
                f"user={user_message}\n"
                f"recent_turns:\n{turns_text}\n"
                f"memories:\n{mem_text}"
            )

        text = render()
        preflight = self.preflight.check(text, budget, trim_actions)

        while not preflight.allowed:
            if memories:
                memories.pop()
                trim_actions.append("drop_memory_snippet")
            elif turns:
                turns.pop(0)
                trim_actions.append("drop_oldest_turn")
            else:
                # last-resort trim of user content to avoid unbounded prompt growth
                user_message = user_message[: max(32, len(user_message) // 2)]
                trim_actions.append("trim_user_message")
            text = render()
            preflight = self.preflight.check(text, budget, trim_actions)
            if len(trim_actions) > 20:
                break

        return CompiledContext(
            prompt_text=text,
            included_turns=turns,
            included_memories=memories,
            trim_actions=trim_actions,
            preflight=preflight,
        )
