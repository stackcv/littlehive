from __future__ import annotations

from datetime import datetime, timezone

from littlehive.core.telemetry.diagnostics import tool_retrieval_quality_stats
from littlehive.db.models import ToolCall
from littlehive.db.session import Base, create_session_factory


def test_tool_retrieval_quality_stats_aggregates_status_rates(tmp_path):
    sf, engine = create_session_factory(f"sqlite:///{tmp_path / 'tool_quality.db'}")
    import littlehive.db.models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    with sf() as db:
        now = datetime.now(timezone.utc)
        db.add(ToolCall(task_id=1, session_id=1, tool_name="a", status="ok", detail="", created_at=now))
        db.add(ToolCall(task_id=1, session_id=1, tool_name="b", status="ok", detail="", created_at=now))
        db.add(ToolCall(task_id=1, session_id=1, tool_name="c", status="blocked", detail="", created_at=now))
        db.add(ToolCall(task_id=1, session_id=1, tool_name="d", status="error", detail="", created_at=now))
        db.commit()

    out = tool_retrieval_quality_stats(sf)
    assert out["total_tool_calls"] == 4
    assert out["ok_calls"] == 2
    assert out["blocked_calls"] == 1
    assert out["error_calls"] == 1
    assert out["success_rate"] == 0.5
