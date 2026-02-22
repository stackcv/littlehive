from __future__ import annotations

from dataclasses import dataclass

from littlehive.core.orchestrator.handoff import Transfer
from littlehive.core.tools.base import ToolCallContext
from littlehive.core.tools.executor import ToolExecutor
from littlehive.core.tools.injection import build_tool_docs_bundle
from littlehive.core.tools.registry import ToolRegistry


@dataclass(slots=True)
class ExecutionResult:
    selected_tools: list[str]
    outputs: list[dict]
    injection_log: dict


class ExecutionAgent:
    agent_id = "execution_agent"

    def __init__(self, tool_registry: ToolRegistry, tool_executor: ToolExecutor) -> None:
        self.tool_registry = tool_registry
        self.tool_executor = tool_executor

    def execute_from_transfer(self, transfer: Transfer, ctx: ToolCallContext) -> ExecutionResult:
        routing_bundle = build_tool_docs_bundle(
            registry=self.tool_registry,
            query=transfer.input_summary,
            mode="routing",
            selected_tool_names=None,
            k=4,
        )

        selected: list[str] = []
        text = transfer.input_summary.lower()
        for item in routing_bundle.routing:
            n = item["name"]
            if n.startswith("memory") and any(k in text for k in ["remember", "preference", "memory", "fix"]):
                selected.append(n)
            if n == "status.get" and "status" in text:
                selected.append(n)
            if n.startswith("task.") and "task" in text:
                selected.append(n)

        if not selected and routing_bundle.routing:
            selected = [routing_bundle.routing[0]["name"]]

        invocation_bundle = build_tool_docs_bundle(
            registry=self.tool_registry,
            query=transfer.input_summary,
            mode="invocation",
            selected_tool_names=selected,
            k=4,
        )

        outputs: list[dict] = []
        for tool_name in selected[:2]:
            full_bundle = build_tool_docs_bundle(
                registry=self.tool_registry,
                query=transfer.input_summary,
                mode="full_for_selected",
                selected_tool_names=[tool_name],
                k=4,
            )
            # Full schema only enters context at actual invocation step.
            _ = full_bundle
            if tool_name == "memory.search":
                outputs.append(self.tool_executor.execute(tool_name, ctx, {"query": transfer.input_summary, "top_k": 3}))
            elif tool_name == "memory.write":
                outputs.append(self.tool_executor.execute(tool_name, ctx, {"content": transfer.input_summary}))
            elif tool_name == "memory.failure_fix":
                outputs.append(
                    self.tool_executor.execute(
                        tool_name,
                        ctx,
                        {
                            "error_signature": "generic",
                            "fix": transfer.input_summary[:120],
                            "source": "execution_agent",
                        },
                    )
                )
            elif tool_name == "status.get":
                outputs.append(self.tool_executor.execute(tool_name, ctx, {}))
            elif tool_name == "task.update" and ctx.task_id is not None:
                outputs.append(
                    self.tool_executor.execute(
                        tool_name,
                        ctx,
                        {
                            "task_id": ctx.task_id,
                            "status": "running",
                            "step_index": 0,
                            "agent_id": self.agent_id,
                            "detail": "execution agent tool phase",
                        },
                    )
                )

        return ExecutionResult(
            selected_tools=selected,
            outputs=outputs,
            injection_log={
                "routing_count": len(routing_bundle.routing),
                "invocation_count": len(invocation_bundle.invocation),
                "full_schema_count": len(selected[:2]),
            },
        )

    def run(self, payload: dict) -> dict:
        return payload
