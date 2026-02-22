from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from littlehive.db.models import MemoryRecord


def search_memories(db: Session, session_id: int, query: str, top_k: int = 3) -> list[MemoryRecord]:
    stmt = (
        select(MemoryRecord)
        .where(MemoryRecord.session_id == session_id)
        .where(MemoryRecord.content.ilike(f"%{query}%"))
        .order_by(MemoryRecord.id.desc())
        .limit(top_k)
    )
    return list(db.execute(stmt).scalars())
