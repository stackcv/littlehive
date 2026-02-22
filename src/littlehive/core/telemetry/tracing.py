from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class TraceContext:
    request_id: str
    task_id: str
    session_id: str
    agent_id: str
    phase: str


def trace_event(logger, ctx: TraceContext, event: str, status: str, extra: dict[str, Any] | None = None) -> None:
    payload = {
        "request_id": ctx.request_id,
        "task_id": ctx.task_id,
        "session_id": ctx.session_id,
        "agent_id": ctx.agent_id,
        "phase": ctx.phase,
        "status": status,
    }
    if extra:
        payload.update(extra)
    logger.info(event, **payload)
