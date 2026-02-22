from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from littlehive.db.models import MemoryRecord


def _score(query: str, row: MemoryRecord, idx: int) -> float:
    query_l = query.lower().strip()
    content = row.content.lower()
    lexical = float(content.count(query_l)) if query_l else 0.0
    recency = max(0.0, 5.0 - (idx * 0.2))
    pinned_boost = 4.0 if row.pinned else 0.0
    type_weight = {
        "session_summary": 3.0,
        "failure_fix": 2.5,
        "preference": 2.0,
        "decision": 1.8,
        "fact": 1.5,
        "open_loop": 1.3,
    }.get(row.card_type, 1.0)
    return lexical * 5.0 + recency + pinned_boost + type_weight


def _dedupe_key(text: str) -> str:
    return " ".join(text.lower().split())[:120]


def retrieve_memory_cards(
    db: Session,
    *,
    session_id: int,
    query: str,
    top_k: int = 4,
    max_snippet_chars: int = 180,
) -> list[dict]:
    stmt = select(MemoryRecord).where(MemoryRecord.session_id == session_id).order_by(MemoryRecord.id.desc()).limit(120)
    rows = list(db.execute(stmt).scalars())
    ranked = sorted(((row, _score(query, row, idx)) for idx, row in enumerate(rows)), key=lambda x: (-x[1], -x[0].id))

    out: list[dict] = []
    seen: set[str] = set()
    for row, score in ranked:
        key = _dedupe_key(row.content)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "id": row.id,
                "card_type": row.card_type,
                "content": row.content[:max_snippet_chars],
                "score": round(score, 3),
            }
        )
        if len(out) >= top_k:
            break
    return out


def search_memories(db: Session, session_id: int, query: str, top_k: int = 3) -> list[MemoryRecord]:
    # Backward-compatible low-level search call.
    stmt = (
        select(MemoryRecord)
        .where(MemoryRecord.session_id == session_id)
        .where(MemoryRecord.content.ilike(f"%{query}%"))
        .order_by(MemoryRecord.id.desc())
        .limit(top_k)
    )
    return list(db.execute(stmt).scalars())
