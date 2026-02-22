from __future__ import annotations

from datetime import datetime, timezone

from littlehive.core.telemetry.tracing import recent_traces
from littlehive.db.models import TaskTraceSummary


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def persist_task_trace_summary(db_session_factory, *, task_id: int, session_id: int, request_id: str, outcome_status: str) -> None:
    traces = [t for t in recent_traces(limit=800) if t.get("task_id") == str(task_id) and t.get("request_id") == request_id]
    if not traces:
        return
    agents: list[str] = []
    estimated_tokens: list[int] = []
    transfer_count = 0
    provider_attempts = 0
    tool_attempts = 0
    retry_count = 0
    breaker_events = 0
    trim_event_count = 0

    for t in traces:
        agent = t.get("agent")
        if isinstance(agent, str) and agent not in agents:
            agents.append(agent)
        if t.get("event") == "transfer_created":
            transfer_count += 1
        if t.get("event") == "provider_attempt":
            provider_attempts += 1
        if t.get("event") == "tool_call":
            tool_attempts += 1
        if t.get("event") in {"provider_retry", "tool_retry", "reflexion_retry"}:
            retry_count += 1
        if t.get("event") in {"provider_blocked", "tool_call"} and t.get("status") == "blocked":
            breaker_events += 1
        if t.get("event") == "context_compiled":
            et = int(t.get("estimated_tokens", 0))
            if et > 0:
                estimated_tokens.append(et)
            trims = str(t.get("trim_actions", ""))
            if trims:
                trim_event_count += 1

    avg_tokens = (sum(estimated_tokens) / len(estimated_tokens)) if estimated_tokens else 0.0

    with db_session_factory() as db:
        row = TaskTraceSummary(
            task_id=task_id,
            session_id=session_id,
            request_id=request_id,
            agent_sequence=",".join(agents),
            transfer_count=transfer_count,
            provider_attempts=provider_attempts,
            tool_attempts=tool_attempts,
            retry_count=retry_count,
            breaker_events=breaker_events,
            trim_event_count=trim_event_count,
            avg_estimated_tokens=avg_tokens,
            outcome_status=outcome_status,
            created_at=_utcnow(),
        )
        db.add(row)
        db.commit()
