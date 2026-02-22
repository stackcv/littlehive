from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from time import monotonic

from sqlalchemy import func, select

from littlehive import __version__
from littlehive.core.permissions.policy_engine import PermissionProfile, PolicyEngine
from littlehive.core.telemetry.diagnostics import budget_stats, failure_summary, runtime_stats
from littlehive.db.models import (
    MemoryRecord,
    PendingConfirmation,
    PermissionAuditEvent,
    PermissionState,
    SessionSummary,
    Task,
    TaskTraceSummary,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def redact_text(value: str) -> str:
    upper = value.upper()
    if any(k in upper for k in ["TOKEN", "SECRET", "KEY", "PASSWORD"]):
        return "***REDACTED***"
    return value


class AdminService:
    def __init__(self, *, cfg, db_session_factory, provider_router=None) -> None:
        self.cfg = cfg
        self.db_session_factory = db_session_factory
        self.provider_router = provider_router
        self._started = monotonic()
        self._default_profile = str(getattr(cfg.runtime, "permission_profile", "execute_safe"))

    def uptime_seconds(self) -> int:
        return int(monotonic() - self._started)

    def get_or_create_permission_state(self) -> PermissionState:
        with self.db_session_factory() as db:
            row = db.execute(select(PermissionState).order_by(PermissionState.id.asc())).scalar_one_or_none()
            if row is None:
                row = PermissionState(current_profile=self._default_profile, updated_by="system", updated_at=_utcnow())
                db.add(row)
                db.commit()
                db.refresh(row)
            return row

    def get_policy_engine(self) -> PolicyEngine:
        state = self.get_or_create_permission_state()
        return PolicyEngine(PermissionProfile(state.current_profile))

    def update_profile(self, profile: PermissionProfile, actor: str) -> PermissionState:
        with self.db_session_factory() as db:
            row = db.execute(select(PermissionState).order_by(PermissionState.id.asc())).scalar_one_or_none()
            if row is None:
                row = PermissionState(current_profile=profile.value, updated_by=actor, updated_at=_utcnow())
                db.add(row)
                db.flush()
                prev = ""
            else:
                prev = row.current_profile
                row.current_profile = profile.value
                row.updated_by = actor
                row.updated_at = _utcnow()
            db.add(
                PermissionAuditEvent(
                    actor=actor,
                    event_type="profile_update",
                    previous_profile=prev,
                    next_profile=profile.value,
                    detail="",
                    created_at=_utcnow(),
                )
            )
            db.commit()
            db.refresh(row)
            return row

    def create_confirmation(
        self,
        *,
        action_type: str,
        action_summary: str,
        payload: dict,
        task_id: int | None,
        session_id: int | None,
        ttl_seconds: int = 300,
    ) -> PendingConfirmation:
        with self.db_session_factory() as db:
            row = PendingConfirmation(
                task_id=task_id,
                session_id=session_id,
                action_type=action_type,
                action_summary=action_summary[:800],
                payload_json=json.dumps(payload, ensure_ascii=True),
                status="waiting_confirmation",
                created_at=_utcnow(),
                expires_at=_utcnow() + timedelta(seconds=ttl_seconds),
                decided_at=None,
                decided_by="",
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return row

    def list_pending_confirmations(self) -> list[PendingConfirmation]:
        now = _utcnow()
        with self.db_session_factory() as db:
            pending = (
                db.execute(
                    select(PendingConfirmation)
                    .where(PendingConfirmation.status == "waiting_confirmation")
                    .order_by(PendingConfirmation.created_at.desc())
                )
                .scalars()
                .all()
            )
            changed = False
            for row in pending:
                threshold = now if getattr(row.expires_at, "tzinfo", None) else now.replace(tzinfo=None)
                if row.expires_at < threshold:
                    row.status = "expired"
                    row.decided_at = now
                    row.decided_by = "system"
                    changed = True
            if changed:
                db.commit()
            return pending

    def decide_confirmation(self, confirmation_id: int, decision: str, actor: str) -> PendingConfirmation:
        with self.db_session_factory() as db:
            row = db.execute(select(PendingConfirmation).where(PendingConfirmation.id == confirmation_id)).scalar_one()
            if row.status != "waiting_confirmation":
                return row
            row.status = "confirmed" if decision == "confirm" else "denied"
            row.decided_at = _utcnow()
            row.decided_by = actor[:120]
            db.commit()
            db.refresh(row)
            return row

    def overview(self) -> dict:
        with self.db_session_factory() as db:
            total_tasks = int(db.execute(select(func.count(Task.id))).scalar_one())
            active_tasks = int(
                db.execute(select(func.count(Task.id)).where(Task.status.in_(["pending", "running", "waiting_confirmation"]))).scalar_one()
            )
        providers = sorted(self.provider_router.configured()) if self.provider_router is not None else []
        return {
            "version": __version__,
            "environment": self.cfg.environment,
            "instance": self.cfg.instance.name,
            "safe_mode": bool(self.cfg.runtime.safe_mode),
            "active_tasks": active_tasks,
            "total_tasks": total_tasks,
            "providers_configured": providers,
            "uptime_seconds": self.uptime_seconds(),
        }

    def providers(self) -> list[dict]:
        if self.provider_router is None:
            return []
        status = self.provider_router.provider_status()
        scores = self.provider_router.provider_scores()
        items: list[dict] = []
        for name in sorted(status):
            st = status[name]
            items.append(
                {
                    "name": name,
                    "health": bool(st["health"]),
                    "score": float(scores.get(name, 0.0)),
                    "breaker_state": st["breaker"]["state"],
                    "failures": int(st["stats"].get("failure", 0)),
                    "latency_ms": float(st["stats"].get("latency_ms", 0.0)),
                }
            )
        return items

    def list_tasks(self, limit: int = 50, status: str | None = None, session_id: int | None = None) -> list[dict]:
        with self.db_session_factory() as db:
            query = select(Task).order_by(Task.id.desc()).limit(limit)
            if status:
                query = query.where(Task.status == status)
            if session_id is not None:
                query = query.where(Task.session_id == session_id)
            rows = db.execute(query).scalars().all()
        return [
            {
                "task_id": r.id,
                "session_id": r.session_id,
                "status": r.status,
                "summary": r.summary,
                "created_at": r.created_at,
                "updated_at": r.updated_at,
            }
            for r in rows
        ]

    def get_trace(self, task_id: int) -> dict | None:
        with self.db_session_factory() as db:
            row = db.execute(select(TaskTraceSummary).where(TaskTraceSummary.task_id == task_id)).scalar_one_or_none()
        if row is None:
            return None
        return {
            "task_id": row.task_id,
            "session_id": row.session_id,
            "request_id": row.request_id,
            "agent_sequence": row.agent_sequence[:1200],
            "transfer_count": row.transfer_count,
            "provider_attempts": row.provider_attempts,
            "tool_attempts": row.tool_attempts,
            "retry_count": row.retry_count,
            "breaker_events": row.breaker_events,
            "trim_event_count": row.trim_event_count,
            "avg_estimated_tokens": float(row.avg_estimated_tokens),
            "outcome_status": row.outcome_status,
            "created_at": row.created_at,
        }

    def memory_search(self, query: str, session_id: int | None = None, user_id: int | None = None, limit: int = 20) -> list[dict]:
        query_lower = (query or "").strip().lower()
        with self.db_session_factory() as db:
            rows = db.execute(select(MemoryRecord).order_by(MemoryRecord.id.desc())).scalars().all()
        filtered = []
        for row in rows:
            if session_id is not None and row.session_id != session_id:
                continue
            if user_id is not None and row.user_id != user_id:
                continue
            if query_lower and query_lower not in row.content.lower() and query_lower not in row.card_type.lower():
                continue
            filtered.append(
                {
                    "id": row.id,
                    "session_id": row.session_id,
                    "user_id": row.user_id,
                    "card_type": row.card_type,
                    "memory_type": row.memory_type,
                    "snippet": redact_text(row.content[:240]),
                    "created_at": row.created_at,
                }
            )
        return filtered[:limit]

    def session_memory_summary(self, session_id: int) -> str:
        with self.db_session_factory() as db:
            summary = db.execute(select(SessionSummary).where(SessionSummary.session_id == session_id)).scalar_one_or_none()
        if summary is None:
            return ""
        return summary.summary[:500]

    def usage_summary(self) -> dict:
        return budget_stats(self.db_session_factory)

    def failure_summary(self, limit: int = 20) -> list[dict]:
        return failure_summary(self.db_session_factory, limit=limit)

    def runtime_summary(self) -> dict:
        data = runtime_stats(self.db_session_factory)
        data["safe_mode"] = bool(self.cfg.runtime.safe_mode)
        return data
