from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(slots=True)
class ToolMetadata:
    name: str
    routing_summary: str
    invocation_summary: str
    full_schema: dict[str, Any]


@dataclass(slots=True)
class ToolCallContext:
    session_db_id: int
    user_db_id: int
    task_id: int | None
    trace_id: str
    extra: dict[str, Any] = field(default_factory=dict)


ToolHandler = Callable[[ToolCallContext, dict[str, Any]], dict[str, Any]]
