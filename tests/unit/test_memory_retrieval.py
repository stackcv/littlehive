from __future__ import annotations

from datetime import datetime, timezone

from littlehive.core.memory.retrieval import retrieve_memory_cards
from littlehive.db.models import MemoryRecord
from littlehive.db.session import Base, create_session_factory


def test_memory_retrieval_ranking_dedupe_truncation(tmp_path):
    session_factory, engine = create_session_factory(f"sqlite:///{tmp_path / 'mem.db'}")
    import littlehive.db.models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    with session_factory() as db:
        db.add(
            MemoryRecord(
                session_id=1,
                user_id=1,
                memory_type="card",
                card_type="session_summary",
                content="project summary with important memory key",
                pinned=1,
                created_at=datetime.now(timezone.utc),
            )
        )
        db.add(
            MemoryRecord(
                session_id=1,
                user_id=1,
                memory_type="card",
                card_type="fact",
                content="important memory key",
                pinned=0,
                created_at=datetime.now(timezone.utc),
            )
        )
        db.add(
            MemoryRecord(
                session_id=1,
                user_id=1,
                memory_type="card",
                card_type="fact",
                content="important memory key",  # duplicate
                pinned=0,
                created_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    with session_factory() as db:
        out = retrieve_memory_cards(db, session_id=1, query="important", top_k=3, max_snippet_chars=10)

    assert out
    assert len(out) <= 3
    assert len({x["content"] for x in out}) == len(out)
    assert all(len(x["content"]) <= 10 for x in out)
