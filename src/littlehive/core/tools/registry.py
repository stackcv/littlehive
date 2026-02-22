from __future__ import annotations

from littlehive.core.tools.base import ToolMetadata


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolMetadata] = {}

    def register(self, metadata: ToolMetadata) -> None:
        self._tools[metadata.name] = metadata

    def get(self, name: str) -> ToolMetadata | None:
        return self._tools.get(name)
