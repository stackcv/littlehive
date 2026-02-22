from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from littlehive.core.runtime.errors import ErrorInfo, compact_error_summary
from littlehive.db.models import FailureFingerprint


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class ReflexionDecision:
    strategy: str
    reason: str
    patch: dict
    confidence: float


def should_trigger_reflexion(*, error_retryable: bool, attempts_used: int, max_per_step: int, safe_mode: bool) -> bool:
    if not error_retryable:
        return False
    if attempts_used >= max_per_step:
        return False
    if safe_mode and attempts_used >= 1:
        return False
    return True


def reflexion_lite_decide(*, error_summary: str, has_fallback_provider: bool, safe_mode: bool) -> ReflexionDecision:
    s = error_summary.lower()
    if "timeout" in s and has_fallback_provider and not safe_mode:
        return ReflexionDecision(
            strategy="switch_provider",
            reason="timeout-like failure with fallback available",
            patch={"use_fallback": True},
            confidence=0.7,
        )
    if "over_budget" in s or "token" in s:
        return ReflexionDecision(
            strategy="reduce_context",
            reason="context appears too large",
            patch={"reduce_recent_turns": True, "reduce_memory_snippets": True},
            confidence=0.8,
        )
    if "tool" in s and safe_mode:
        return ReflexionDecision(
            strategy="skip_tool",
            reason="safe mode prefers conservative fallback",
            patch={"skip_optional_tools": True},
            confidence=0.6,
        )
    return ReflexionDecision(
        strategy="retry_same",
        reason="transient failure candidate",
        patch={"retry": True},
        confidence=0.5,
    )


def upsert_failure_fingerprint(db, info: ErrorInfo) -> FailureFingerprint:
    row = (
        db.execute(
            select(FailureFingerprint)
            .where(FailureFingerprint.category == info.category)
            .where(FailureFingerprint.component == info.component)
            .where(FailureFingerprint.error_type == info.error_type)
            .where(FailureFingerprint.message_signature == info.message_signature)
        )
        .scalars()
        .first()
    )
    if row is None:
        row = FailureFingerprint(
            category=info.category,
            component=info.component,
            error_type=info.error_type,
            message_signature=info.message_signature,
            status_code=info.http_status,
            first_seen_at=_utcnow(),
            last_seen_at=_utcnow(),
            occurrence_count=1,
            recovered_count=0,
            last_recovery_strategy="",
        )
        db.add(row)
    else:
        row.occurrence_count += 1
        row.last_seen_at = _utcnow()
        if info.http_status is not None:
            row.status_code = info.http_status
    db.flush()
    return row


def mark_recovered(db, fingerprint_id: int, strategy: str) -> None:
    row = db.execute(select(FailureFingerprint).where(FailureFingerprint.id == fingerprint_id)).scalar_one_or_none()
    if row is None:
        return
    row.recovered_count += 1
    row.last_recovery_strategy = strategy[:64]
    row.last_seen_at = _utcnow()
    db.flush()


def compact_failure_message(exc: Exception) -> str:
    return compact_error_summary(exc)
