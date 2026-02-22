from __future__ import annotations

import pytest

from littlehive.core.permissions.policy_engine import PermissionProfile, PolicyEngine
from littlehive.core.telemetry.logging import get_logger
from littlehive.core.tools.base import ToolCallContext, ToolMetadata
from littlehive.core.tools.executor import ToolExecutor
from littlehive.core.tools.registry import ToolRegistry


def test_tool_risk_gating_and_confirmation_flow():
    registry = ToolRegistry()

    def medium_handler(ctx, args):
        _ = (ctx, args)
        return {"ok": True}

    registry.register(
        ToolMetadata(
            name="risk.medium",
            tags=["risk"],
            routing_summary="medium",
            invocation_summary="medium()",
            full_schema={"type": "object"},
            timeout_sec=1,
            idempotent=True,
            risk_level="medium",
        ),
        medium_handler,
    )

    confirmations: list[int] = []

    def create_confirmation(ctx, tool_name, args):
        _ = (ctx, tool_name, args)
        confirmations.append(1)
        return 1

    executor = ToolExecutor(
        registry=registry,
        logger=get_logger("test.phase45.risk"),
        policy_engine=PolicyEngine(PermissionProfile.EXECUTE_SAFE),
        safe_mode_getter=lambda: True,
        create_confirmation=create_confirmation,
    )
    ctx = ToolCallContext(session_db_id=1, user_db_id=1, task_id=1, trace_id="x")

    out = executor.execute("risk.medium", ctx, {})
    assert out["status"] == "waiting_confirmation"
    assert confirmations == [1]


def test_tool_risk_blocked_in_read_only():
    registry = ToolRegistry()

    def handler(ctx, args):
        _ = (ctx, args)
        return {"ok": True}

    registry.register(
        ToolMetadata(
            name="risk.low",
            tags=["risk"],
            routing_summary="low",
            invocation_summary="low()",
            full_schema={"type": "object"},
            timeout_sec=1,
            idempotent=True,
            risk_level="low",
        ),
        handler,
    )

    executor = ToolExecutor(
        registry=registry,
        logger=get_logger("test.phase45.risk.block"),
        policy_engine=PolicyEngine(PermissionProfile.READ_ONLY),
    )
    ctx = ToolCallContext(session_db_id=1, user_db_id=1, task_id=1, trace_id="x")

    with pytest.raises(PermissionError):
        executor.execute("risk.low", ctx, {})
