from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

_TRACE_EVENTS: deque[dict[str, Any]] = deque(maxlen=500)


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
    _TRACE_EVENTS.append({"event": event, **payload})
    logger.info(event, **payload)


def recent_traces(session_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    items = list(_TRACE_EVENTS)
    if session_id is not None:
        items = [i for i in items if i.get("session_id") == session_id]
    return items[-limit:]
