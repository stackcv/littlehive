from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, Field


class ToolMetadata(BaseModel):
    name: str
    version: str = "1.0"
    risk_level: str = "low"
    tags: list[str] = Field(default_factory=list)
    routing_summary: str
    invocation_summary: str
    full_schema: dict[str, Any]
    examples: list[str] = Field(default_factory=list)
    timeout_sec: int = 15
    idempotent: bool = True
    permission_required: str = "none"


@dataclass(slots=True)
class ToolCallContext:
    session_db_id: int
    user_db_id: int
    task_id: int | None
    trace_id: str
    extra: dict[str, Any] = field(default_factory=dict)


ToolHandler = Callable[[ToolCallContext, dict[str, Any]], dict[str, Any]]
