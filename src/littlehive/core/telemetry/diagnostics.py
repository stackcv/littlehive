from __future__ import annotations

from sqlalchemy import func, select

from littlehive.db.models import FailureFingerprint, Task, TaskTraceSummary, ToolCall


def runtime_stats(db_session_factory) -> dict:
    with db_session_factory() as db:
        statuses = dict(db.execute(select(Task.status, func.count(Task.id)).group_by(Task.status)).all())
        traces = db.execute(select(func.count(TaskTraceSummary.id))).scalar_one()
        safe = {
            "tasks_by_status": {k: int(v) for k, v in statuses.items()},
            "trace_summaries": int(traces),
        }
        return safe


def failure_summary(db_session_factory, limit: int = 10) -> list[dict]:
    with db_session_factory() as db:
        rows = (
            db.execute(
                select(FailureFingerprint)
                .order_by(FailureFingerprint.last_seen_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
    return [
        {
            "category": r.category,
            "component": r.component,
            "error_type": r.error_type,
            "signature": r.message_signature,
            "count": r.occurrence_count,
            "recovered": r.recovered_count,
            "last_strategy": r.last_recovery_strategy,
            "last_seen": r.last_seen_at.isoformat(),
        }
        for r in rows
    ]


def budget_stats(db_session_factory) -> dict:
    with db_session_factory() as db:
        rows = db.execute(select(TaskTraceSummary)).scalars().all()
    if not rows:
        return {
            "avg_estimated_prompt_tokens": 0.0,
            "trim_event_count": 0,
            "over_budget_incidents": 0,
            "trace_count": 0,
        }
    avg_tokens = sum(float(r.avg_estimated_tokens) for r in rows) / len(rows)
    trims = sum(int(r.trim_event_count) for r in rows)
    over_budget = sum(1 for r in rows if r.outcome_status == "failed")
    return {
        "avg_estimated_prompt_tokens": round(avg_tokens, 3),
        "trim_event_count": int(trims),
        "over_budget_incidents": int(over_budget),
        "trace_count": len(rows),
    }


def tool_retrieval_quality_stats(db_session_factory) -> dict:
    with db_session_factory() as db:
        rows = db.execute(select(ToolCall.status, func.count(ToolCall.id)).group_by(ToolCall.status)).all()
    counts = {str(k): int(v) for k, v in rows}
    ok = counts.get("ok", 0)
    blocked = counts.get("blocked", 0)
    error = counts.get("error", 0)
    waiting = counts.get("waiting_confirmation", 0)
    total = sum(counts.values())
    actionable = max(1, ok + blocked + error)
    return {
        "total_tool_calls": total,
        "ok_calls": ok,
        "blocked_calls": blocked,
        "error_calls": error,
        "waiting_confirmation_calls": waiting,
        "success_rate": round(ok / max(1, total), 4),
        "blocked_rate": round(blocked / actionable, 4),
        "error_rate": round(error / actionable, 4),
    }
