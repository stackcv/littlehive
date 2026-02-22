from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from littlehive.core.memory.cards import MemoryCard
from littlehive.db.models import MemoryRecord


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MemoryStore:
    def __init__(self, db: Session) -> None:
        self.db = db

    def write(
        self,
        session_id: int,
        user_id: int,
        content: str,
        memory_type: str = "note",
        card_type: str = "fact",
        pinned: bool = False,
        error_signature: str = "",
        fix_text: str = "",
        source: str = "runtime",
        confidence: float = 0.5,
        success_count: int = 0,
    ) -> MemoryRecord:
        row = MemoryRecord(
            session_id=session_id,
            user_id=user_id,
            memory_type=memory_type,
            card_type=card_type,
            content=content[:1000],
            pinned=1 if pinned else 0,
            error_signature=error_signature[:256],
            fix_text=fix_text[:500],
            source=source[:64],
            confidence=confidence,
            success_count=success_count,
            created_at=_utcnow(),
        )
        self.db.add(row)
        self.db.flush()
        return row

    def write_card(self, session_id: int, user_id: int, card: MemoryCard) -> MemoryRecord:
        return self.write(
            session_id=session_id,
            user_id=user_id,
            content=card.content,
            memory_type="card",
            card_type=card.card_type,
            pinned=card.pinned,
            error_signature=card.error_signature or "",
            fix_text=card.fix_text or "",
            source=card.source,
            confidence=card.confidence,
            success_count=card.success_count,
        )

    def list_recent(self, session_id: int, limit: int = 5) -> list[MemoryRecord]:
        stmt = select(MemoryRecord).where(MemoryRecord.session_id == session_id).order_by(MemoryRecord.id.desc()).limit(limit)
        return list(self.db.execute(stmt).scalars())
