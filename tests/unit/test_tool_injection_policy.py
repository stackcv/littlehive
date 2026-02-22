from __future__ import annotations

from littlehive.core.tools.base import ToolMetadata
from littlehive.core.tools.injection import build_tool_docs_bundle
from littlehive.core.tools.registry import ToolRegistry


def _noop(ctx, args):
    _ = (ctx, args)
    return {"ok": True}


def test_tool_injection_modes_enforce_schema_on_demand():
    registry = ToolRegistry()
    registry.register(
        ToolMetadata(
            name="task.update",
            tags=["task"],
            routing_summary="update task status",
            invocation_summary="task.update(task_id, status)",
            full_schema={"type": "object", "properties": {"task_id": {"type": "integer"}}},
        ),
        _noop,
    )

    routing = build_tool_docs_bundle(registry=registry, query="task", mode="routing")
    invocation = build_tool_docs_bundle(
        registry=registry,
        query="task",
        mode="invocation",
        selected_tool_names=["task.update"],
    )
    full = build_tool_docs_bundle(
        registry=registry,
        query="task",
        mode="full_for_selected",
        selected_tool_names=["task.update"],
    )

    assert routing.routing
    assert not routing.full
    assert invocation.invocation
    assert not invocation.full
    assert full.full and full.full[0]["name"] == "task.update"
