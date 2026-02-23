from __future__ import annotations

import pytest

from littlehive.core.telemetry.logging import get_logger
from littlehive.core.tools.base import ToolCallContext, ToolMetadata
from littlehive.core.tools.executor import ToolExecutor
from littlehive.core.tools.registry import ToolRegistry


def test_tool_retry_idempotent_vs_non_idempotent():
    registry = ToolRegistry()
    calls = {"idempotent": 0, "non_idempotent": 0}

    def idempotent_handler(ctx, args):
        _ = (ctx, args)
        calls["idempotent"] += 1
        if calls["idempotent"] < 2:
            raise TimeoutError("temporary")
        return {"ok": True}

    def non_idempotent_handler(ctx, args):
        _ = (ctx, args)
        calls["non_idempotent"] += 1
        raise TimeoutError("temporary")

    registry.register(
        ToolMetadata(
            name="idempotent.tool",
            tags=["test"],
            routing_summary="idempotent",
            invocation_summary="idempotent.tool()",
            full_schema={"type": "object"},
            timeout_sec=1,
            idempotent=True,
        ),
        idempotent_handler,
    )
    registry.register(
        ToolMetadata(
            name="nonid.tool",
            tags=["test"],
            routing_summary="non idempotent",
            invocation_summary="nonid.tool()",
            full_schema={"type": "object"},
            timeout_sec=1,
            idempotent=False,
        ),
        non_idempotent_handler,
    )

    ex = ToolExecutor(registry, get_logger("test.tool"))
    ctx = ToolCallContext(session_db_id=1, user_db_id=1, task_id=1, trace_id="r1")

    assert ex.execute("idempotent.tool", ctx, {})["ok"] is True
    assert calls["idempotent"] == 2

    with pytest.raises(RuntimeError):
        ex.execute("nonid.tool", ctx, {})
    assert calls["non_idempotent"] == 1
