from __future__ import annotations

from littlehive.core.telemetry.logging import get_logger
from littlehive.core.tools.base import ToolCallContext
from littlehive.core.tools.builtin.status_tools import register_status_tools
from littlehive.core.tools.executor import ToolExecutor
from littlehive.core.tools.registry import ToolRegistry
from littlehive.db.session import Base, create_session_factory


class _RouterStub:
    def health(self) -> dict[str, bool]:
        return {"local_compatible": True}


def test_utility_echo_tool_executes_via_executor():
    session_factory, engine = create_session_factory("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)

    registry = ToolRegistry()
    register_status_tools(registry, session_factory, _RouterStub())

    ex = ToolExecutor(registry=registry, logger=get_logger("test.utility.echo"))
    ctx = ToolCallContext(session_db_id=7, user_db_id=11, task_id=13, trace_id="echo1")

    out = ex.execute("utility.echo", ctx, {"message": "hello tool"})
    assert out["message"] == "hello tool"
    assert out["length"] == 10
    assert out["session_id"] == 7
    assert out["task_id"] == 13
