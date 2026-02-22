from __future__ import annotations

from littlehive.core.tools.registry import ToolRegistry, ToolShortlistItem


def find_tools(registry: ToolRegistry, query: str, k: int = 4) -> list[ToolShortlistItem]:
    return registry.find_tools(query=query, k=k)
