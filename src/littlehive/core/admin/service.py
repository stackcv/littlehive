from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from time import monotonic

from sqlalchemy import and_, func, select

from littlehive import __version__
from littlehive.core.permissions.policy_engine import PermissionProfile, PolicyEngine
from littlehive.core.telemetry.diagnostics import budget_stats, failure_summary, runtime_stats
from littlehive.db.models import (
    MemoryRecord,
    PendingConfirmation,
    PermissionAuditEvent,
    PermissionState,
    Principal,
    PrincipalGrant,
    RuntimeControlEvent,
    RuntimeState,
    SessionSummary,
    Task,
    TaskTraceSummary,
    User,
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

    def get_or_create_runtime_state(self) -> RuntimeState:
        with self.db_session_factory() as db:
            row = db.execute(select(RuntimeState).order_by(RuntimeState.id.asc())).scalar_one_or_none()
            if row is None:
                row = RuntimeState(
                    safe_mode=1 if bool(self.cfg.runtime.safe_mode) else 0,
                    updated_by="system",
                    updated_at=_utcnow(),
                )
                db.add(row)
                db.commit()
                db.refresh(row)
            return row

    def get_safe_mode(self) -> bool:
        row = self.get_or_create_runtime_state()
        return bool(row.safe_mode)

    def update_safe_mode(self, safe_mode: bool, actor: str) -> RuntimeState:
        with self.db_session_factory() as db:
            row = db.execute(select(RuntimeState).order_by(RuntimeState.id.asc())).scalar_one_or_none()
            if row is None:
                row = RuntimeState(
                    safe_mode=1 if safe_mode else 0,
                    updated_by=actor,
                    updated_at=_utcnow(),
                )
                db.add(row)
            else:
                row.safe_mode = 1 if safe_mode else 0
                row.updated_by = actor
                row.updated_at = _utcnow()
            db.commit()
            db.refresh(row)
            return row

    def ensure_principal(self, *, channel: str, external_id: str, display_name: str = "") -> Principal:
        norm_channel = (channel or "").strip().lower()[:32]
        norm_external = (external_id or "").strip()[:128]
        if not norm_channel or not norm_external:
            raise ValueError("channel and external_id are required")

        with self.db_session_factory() as db:
            row = db.execute(
                select(Principal).where(and_(Principal.channel == norm_channel, Principal.external_id == norm_external))
            ).scalar_one_or_none()
            if row is None:
                row = Principal(
                    channel=norm_channel,
                    external_id=norm_external,
                    display_name=(display_name or "")[:128],
                    created_at=_utcnow(),
                    updated_at=_utcnow(),
                )
                db.add(row)
            elif display_name:
                row.display_name = display_name[:128]
                row.updated_at = _utcnow()
            db.commit()
            db.refresh(row)
            return row

    def set_principal_grant(
        self,
        *,
        channel: str,
        external_id: str,
        grant_type: str,
        allowed: bool,
        actor: str,
        display_name: str = "",
    ) -> PrincipalGrant:
        principal = self.ensure_principal(channel=channel, external_id=external_id, display_name=display_name)
        gtype = (grant_type or "chat_access").strip().lower()[:64]
        with self.db_session_factory() as db:
            row = db.execute(
                select(PrincipalGrant)
                .where(PrincipalGrant.principal_id == principal.id)
                .where(PrincipalGrant.grant_type == gtype)
            ).scalar_one_or_none()
            if row is None:
                row = PrincipalGrant(
                    principal_id=principal.id,
                    grant_type=gtype,
                    is_allowed=1 if allowed else 0,
                    updated_by=actor[:128],
                    updated_at=_utcnow(),
                )
                db.add(row)
            else:
                row.is_allowed = 1 if allowed else 0
                row.updated_by = actor[:128]
                row.updated_at = _utcnow()
            db.commit()
            db.refresh(row)
            return row

    def _get_principal_grant(self, *, channel: str, external_id: str, grant_type: str) -> PrincipalGrant | None:
        norm_channel = (channel or "").strip().lower()[:32]
        norm_external = (external_id or "").strip()[:128]
        gtype = (grant_type or "chat_access").strip().lower()[:64]
        with self.db_session_factory() as db:
            principal = db.execute(
                select(Principal).where(and_(Principal.channel == norm_channel, Principal.external_id == norm_external))
            ).scalar_one_or_none()
            if principal is None:
                return None
            return db.execute(
                select(PrincipalGrant)
                .where(PrincipalGrant.principal_id == principal.id)
                .where(PrincipalGrant.grant_type == gtype)
            ).scalar_one_or_none()

    def is_principal_owner(self, *, channel: str, external_id: str, fallback_owner_external_id: str | None = None) -> bool:
        owner = self._get_principal_grant(channel=channel, external_id=external_id, grant_type="owner")
        if owner is not None:
            return bool(owner.is_allowed)
        if fallback_owner_external_id is None:
            return False
        return external_id == fallback_owner_external_id

    def is_principal_chat_allowed(
        self,
        *,
        channel: str,
        external_id: str,
        fallback_allowed_external_ids: set[str] | None = None,
    ) -> bool:
        grant = self._get_principal_grant(channel=channel, external_id=external_id, grant_type="chat_access")
        if grant is not None:
            return bool(grant.is_allowed)
        return external_id in (fallback_allowed_external_ids or set())

    def bootstrap_telegram_grants(self) -> None:
        cfg = self.cfg.channels.telegram
        owner = cfg.owner_user_id
        if owner is not None:
            sid = str(int(owner))
            self.set_principal_grant(
                channel="telegram",
                external_id=sid,
                grant_type="chat_access",
                allowed=True,
                actor="bootstrap",
            )
            self.set_principal_grant(
                channel="telegram",
                external_id=sid,
                grant_type="owner",
                allowed=True,
                actor="bootstrap",
            )
        for uid in cfg.allow_user_ids:
            self.set_principal_grant(
                channel="telegram",
                external_id=str(int(uid)),
                grant_type="chat_access",
                allowed=True,
                actor="bootstrap",
            )

    def list_principals(self, *, channel: str | None = None, limit: int = 200) -> list[dict]:
        with self.db_session_factory() as db:
            q = select(Principal).order_by(Principal.id.asc()).limit(limit)
            if channel:
                q = q.where(Principal.channel == channel.lower())
            rows = db.execute(q).scalars().all()
            out: list[dict] = []
            for row in rows:
                grants = db.execute(select(PrincipalGrant).where(PrincipalGrant.principal_id == row.id)).scalars().all()
                out.append(
                    {
                        "id": row.id,
                        "channel": row.channel,
                        "external_id": row.external_id,
                        "display_name": row.display_name,
                        "grants": {g.grant_type: bool(g.is_allowed) for g in grants},
                        "created_at": row.created_at,
                        "updated_at": row.updated_at,
                    }
                )
            return out

    def request_control_event(self, *, event_type: str, payload: dict | None, actor: str) -> RuntimeControlEvent:
        with self.db_session_factory() as db:
            row = RuntimeControlEvent(
                event_type=(event_type or "restart_services")[:64],
                payload_json=json.dumps(payload or {}, ensure_ascii=True),
                status="pending",
                requested_by=actor[:128],
                detail="",
                created_at=_utcnow(),
                processed_at=None,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return row

    def mark_control_event_processed(self, event_id: int, *, status: str, detail: str) -> RuntimeControlEvent | None:
        with self.db_session_factory() as db:
            row = db.execute(select(RuntimeControlEvent).where(RuntimeControlEvent.id == event_id)).scalar_one_or_none()
            if row is None:
                return None
            row.status = status[:32]
            row.detail = detail[:800]
            row.processed_at = _utcnow()
            db.commit()
            db.refresh(row)
            return row

    def list_pending_control_events(self, *, event_type: str | None = None, limit: int = 50) -> list[RuntimeControlEvent]:
        with self.db_session_factory() as db:
            q = (
                select(RuntimeControlEvent)
                .where(RuntimeControlEvent.status == "pending")
                .order_by(RuntimeControlEvent.id.asc())
                .limit(limit)
            )
            if event_type:
                q = q.where(RuntimeControlEvent.event_type == event_type)
            return db.execute(q).scalars().all()

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
            "safe_mode": self.get_safe_mode(),
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
        data["safe_mode"] = self.get_safe_mode()
        return data

    def list_users(self, limit: int = 100) -> list[dict]:
        with self.db_session_factory() as db:
            rows = db.execute(select(User).order_by(User.id.asc()).limit(limit)).scalars().all()
        return [
            {
                "id": r.id,
                "telegram_user_id": r.telegram_user_id,
                "external_id": r.external_id,
                "display_name": r.display_name,
                "preferred_timezone": r.preferred_timezone,
                "city": r.city,
                "country": r.country,
                "profile_notes": r.profile_notes,
                "profile_updated_at": r.profile_updated_at,
                "created_at": r.created_at,
            }
            for r in rows
        ]

    def get_user_profile(self, user_id: int) -> dict | None:
        with self.db_session_factory() as db:
            row = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if row is None:
            return None
        return {
            "id": row.id,
            "telegram_user_id": row.telegram_user_id,
            "external_id": row.external_id,
            "display_name": row.display_name,
            "preferred_timezone": row.preferred_timezone,
            "city": row.city,
            "country": row.country,
            "profile_notes": row.profile_notes,
            "profile_updated_at": row.profile_updated_at,
            "created_at": row.created_at,
        }

    def update_user_profile(
        self,
        *,
        user_id: int,
        display_name: str | None,
        preferred_timezone: str | None,
        city: str | None,
        country: str | None,
        profile_notes: str | None,
    ) -> dict:
        with self.db_session_factory() as db:
            row = db.execute(select(User).where(User.id == user_id)).scalar_one()
            if display_name is not None:
                row.display_name = display_name[:128]
            if preferred_timezone is not None:
                row.preferred_timezone = preferred_timezone[:64]
            if city is not None:
                row.city = city[:128]
            if country is not None:
                row.country = country[:128]
            if profile_notes is not None:
                row.profile_notes = profile_notes[:2000]
            row.profile_updated_at = _utcnow()
            db.commit()
            db.refresh(row)
        return {
            "id": row.id,
            "telegram_user_id": row.telegram_user_id,
            "external_id": row.external_id,
            "display_name": row.display_name,
            "preferred_timezone": row.preferred_timezone,
            "city": row.city,
            "country": row.country,
            "profile_notes": row.profile_notes,
            "profile_updated_at": row.profile_updated_at,
            "created_at": row.created_at,
        }
