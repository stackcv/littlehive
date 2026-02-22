from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from littlehive.db.models import MemoryRecord


class MemoryStore:
    def __init__(self, db: Session) -> None:
        self.db = db

    def write(self, session_id: int, user_id: int, content: str, memory_type: str = "note") -> MemoryRecord:
        row = MemoryRecord(
            session_id=session_id,
            user_id=user_id,
            memory_type=memory_type,
            content=content[:1000],
            created_at=datetime.utcnow(),
        )
        self.db.add(row)
        self.db.flush()
        return row

    def list_recent(self, session_id: int, limit: int = 5) -> list[MemoryRecord]:
        stmt = select(MemoryRecord).where(MemoryRecord.session_id == session_id).order_by(MemoryRecord.id.desc()).limit(limit)
        return list(self.db.execute(stmt).scalars())
