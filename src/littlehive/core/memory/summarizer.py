from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from littlehive.core.memory.cards import make_session_summary_card
from littlehive.core.memory.store import MemoryStore
from littlehive.db.models import Message, SessionSummary


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def summarize_recent_messages(db: Session, session_id: int, max_messages: int = 6) -> str:
    stmt = select(Message).where(Message.session_id == session_id).order_by(Message.id.desc()).limit(max_messages)
    rows = list(db.execute(stmt).scalars())
    rows.reverse()
    parts = [f"{m.role}:{m.content[:80]}" for m in rows]
    return " | ".join(parts)[:700]


def upsert_session_summary(db: Session, session_id: int, summary: str) -> SessionSummary:
    current = db.execute(select(SessionSummary).where(SessionSummary.session_id == session_id)).scalar_one_or_none()
    if current is None:
        current = SessionSummary(session_id=session_id, summary=summary, updated_at=_utcnow())
        db.add(current)
    else:
        current.summary = summary
        current.updated_at = _utcnow()
    db.flush()
    return current


def persist_summary_card(db: Session, session_id: int, user_id: int, summary: str) -> int:
    card = make_session_summary_card(summary)
    row = MemoryStore(db).write_card(session_id=session_id, user_id=user_id, card=card)
    db.flush()
    return row.id
