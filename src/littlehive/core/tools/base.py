from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ToolMetadata:
    name: str
    routing_summary: str
    invocation_summary: str
    full_schema: dict
