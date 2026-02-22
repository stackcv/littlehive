from __future__ import annotations

from dataclasses import dataclass

from littlehive.core.orchestrator.handoff import Transfer, TransferBudget, TransferTraceContext


@dataclass(slots=True)
class PlannerOutput:
    plan_steps: list[str]
    tool_intent_query: str
    transfer: Transfer | None


class PlannerAgent:
    agent_id = "planner_agent"

    def plan(
        self,
        *,
        user_text: str,
        session_id: str,
        task_id: str,
        request_id: str,
        max_input_tokens: int,
        reserved_output_tokens: int,
    ) -> PlannerOutput:
        text = user_text.lower().strip()
        tool_needed = any(tok in text for tok in ["status", "remember", "search", "task", "memory", "fix"]) or text.startswith("/")
        steps = ["interpret_intent", "prepare_response"]
        tool_query = ""
        transfer = None
        if tool_needed:
            steps.insert(1, "execute_tools")
            tool_query = text[:80]
            transfer = Transfer(
                target_agent="execution_agent",
                subtask="execute shortlisted tools for current user request",
                input_summary=user_text[:240],
                constraints=["bounded_context", "tool_schema_on_demand"],
                expected_output_format="json",
                budget=TransferBudget(max_input_tokens=max_input_tokens, reserved_output_tokens=reserved_output_tokens),
                relevant_memory_ids=[],
                fallback_policy="return_partial",
                trace_context=TransferTraceContext(request_id=request_id, task_id=task_id, session_id=session_id),
            )
        return PlannerOutput(plan_steps=steps, tool_intent_query=tool_query, transfer=transfer)

    def run(self, payload: dict) -> dict:
        return payload
