from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from littlehive.core.context.budget import TokenBudget, TokenBudgetPreflight, PreflightResult
from littlehive.core.tools.injection import build_tool_docs_bundle
from littlehive.core.tools.registry import ToolRegistry


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
    included_sections: list[str] = field(default_factory=list)
    dropped_sections: list[str] = field(default_factory=list)
    section_token_estimates: dict[str, int] = field(default_factory=dict)
    over_budget: bool = False


class ContextCompiler:
    def __init__(self) -> None:
        self.preflight = TokenBudgetPreflight()

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, len(text) // 4)

    def compile(
        self,
        *,
        agent_role: str,
        system_prompt: str,
        user_message: str,
        recent_turns: list[ChatTurn],
        memory_snippets: list[str],
        budget: TokenBudget,
        task_payload: str | None = None,
        handoff_payload: str | None = None,
        tool_context_mode: str = "none",
        selected_tool_names: list[str] | None = None,
        tool_registry: ToolRegistry | None = None,
        tool_query: str = "",
        extra_metadata: dict[str, Any] | None = None,
    ) -> CompiledContext:
        trim_actions: list[str] = []
        turns = list(recent_turns)
        memories = list(memory_snippets)
        invocation_docs: list[dict] = []
        routing_docs: list[dict] = []
        full_docs: list[dict] = []
        metadata = dict(extra_metadata or {})

        if tool_context_mode != "none" and tool_registry is not None:
            docs = build_tool_docs_bundle(
                registry=tool_registry,
                query=tool_query or user_message,
                mode=tool_context_mode,
                selected_tool_names=selected_tool_names,
                k=4,
            )
            routing_docs = docs.routing
            invocation_docs = docs.invocation
            full_docs = docs.full

        def render_sections() -> dict[str, str]:
            sections: dict[str, str] = {
                "role": f"agent={agent_role}",
                "system": system_prompt,
                "user": user_message,
                "recent_turns": "\n".join(f"{t.role}: {t.content}" for t in turns),
                "memories": "\n".join(f"- {m}" for m in memories),
            }
            if task_payload:
                sections["task_payload"] = task_payload
            if handoff_payload:
                sections["handoff_payload"] = handoff_payload
            if routing_docs:
                sections["tool_routing"] = str(routing_docs)
            if invocation_docs:
                sections["tool_invocation"] = str(invocation_docs)
            if full_docs:
                sections["tool_full_schema"] = str(full_docs)
            if metadata:
                sections["metadata"] = str(metadata)
            return sections

        sections = render_sections()

        def render_text(parts: dict[str, str]) -> str:
            return "\n".join(f"[{k}]\n{v}" for k, v in parts.items() if v)

        text = render_text(sections)
        preflight = self.preflight.check(text, budget, trim_actions)

        dropped_sections: list[str] = []
        # Deterministic trim order:
        # 1) low-priority memories
        # 2) older recent turns
        # 3) extra invocation summaries
        # 4) nonessential metadata
        # 5) task wording compression
        while not preflight.allowed:
            if memories:
                memories.pop()
                trim_actions.append("drop_memory_card")
            elif turns:
                turns.pop(0)
                trim_actions.append("drop_oldest_recent_turn")
            elif len(invocation_docs) > 1:
                invocation_docs.pop()
                trim_actions.append("drop_extra_invocation_summary")
            elif metadata:
                metadata = {}
                dropped_sections.append("metadata")
                trim_actions.append("drop_metadata")
            elif len(user_message) > 40:
                user_message = user_message[: max(40, len(user_message) // 2)]
                trim_actions.append("compress_task_wording")
            else:
                trim_actions.append("over_budget_failure")
                break

            sections = render_sections()
            text = render_text(sections)
            preflight = self.preflight.check(text, budget, trim_actions)
            if len(trim_actions) > 30:
                break

        section_estimates = {k: self._estimate_tokens(v) for k, v in sections.items() if v}
        over_budget = not preflight.allowed
        included_sections = list(sections.keys())
        if over_budget:
            dropped_sections.append("budget_exceeded")

        return CompiledContext(
            prompt_text=text,
            included_turns=turns,
            included_memories=memories,
            trim_actions=trim_actions,
            preflight=preflight,
            included_sections=included_sections,
            dropped_sections=dropped_sections,
            section_token_estimates=section_estimates,
            over_budget=over_budget,
        )
