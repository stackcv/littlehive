from __future__ import annotations

from littlehive.core.tools.base import ToolMetadata
from littlehive.core.tools.registry import ToolRegistry


def _noop(ctx, args):
    _ = (ctx, args)
    return {"ok": True}


def test_itr_find_tools_ranking_and_determinism():
    registry = ToolRegistry()
    registry.register(
        ToolMetadata(
            name="memory.search",
            tags=["memory", "search"],
            routing_summary="search memory cards",
            invocation_summary="memory.search(query)",
            full_schema={"type": "object"},
        ),
        _noop,
    )
    registry.register(
        ToolMetadata(
            name="status.get",
            tags=["status", "health"],
            routing_summary="get status",
            invocation_summary="status.get()",
            full_schema={"type": "object"},
        ),
        _noop,
    )

    first = registry.find_tools("memory", k=2)
    second = registry.find_tools("memory", k=2)
    assert first and second
    assert [x.name for x in first] == [x.name for x in second]
    assert first[0].name == "memory.search"
