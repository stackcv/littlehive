from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from littlehive.db.models import Message, SessionSummary


def summarize_recent_messages(db: Session, session_id: int, max_messages: int = 6) -> str:
    stmt = select(Message).where(Message.session_id == session_id).order_by(Message.id.desc()).limit(max_messages)
    rows = list(db.execute(stmt).scalars())
    rows.reverse()
    parts = [f"{m.role}:{m.content[:80]}" for m in rows]
    return " | ".join(parts)[:500]


def upsert_session_summary(db: Session, session_id: int, summary: str) -> SessionSummary:
    current = db.execute(select(SessionSummary).where(SessionSummary.session_id == session_id)).scalar_one_or_none()
    if current is None:
        current = SessionSummary(session_id=session_id, summary=summary, updated_at=datetime.utcnow())
        db.add(current)
    else:
        current.summary = summary
        current.updated_at = datetime.utcnow()
    db.flush()
    return current
