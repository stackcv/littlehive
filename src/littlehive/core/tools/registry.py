from __future__ import annotations

from littlehive.core.tools.base import ToolHandler, ToolMetadata


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, tuple[ToolMetadata, ToolHandler]] = {}

    def register(self, metadata: ToolMetadata, handler: ToolHandler) -> None:
        self._tools[metadata.name] = (metadata, handler)

    def get_handler(self, name: str) -> ToolHandler | None:
        item = self._tools.get(name)
        return item[1] if item else None

    def list_tools(self) -> list[ToolMetadata]:
        return [item[0] for item in self._tools.values()]
