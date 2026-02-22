from __future__ import annotations

from sqlalchemy import func, select

from littlehive.db.models import MemoryRecord, ProviderCall, Task
from littlehive.core.tools.base import ToolCallContext, ToolMetadata


def register_status_tools(registry, db_session_factory, provider_router):
    def status_get(ctx: ToolCallContext, args: dict) -> dict:
        _ = args
        with db_session_factory() as db:
            task_count = db.execute(select(func.count(Task.id))).scalar_one()
            memory_count = db.execute(select(func.count(MemoryRecord.id))).scalar_one()
            provider_count = db.execute(select(func.count(ProviderCall.id))).scalar_one()
        return {
            "session_id": ctx.session_db_id,
            "tasks": int(task_count),
            "memories": int(memory_count),
            "provider_calls": int(provider_count),
            "providers": provider_router.health(),
        }

    registry.register(
        ToolMetadata(
            name="status.get",
            version="2.0",
            risk_level="low",
            tags=["status", "health", "diagnostics"],
            routing_summary="Return runtime health and persistence counters.",
            invocation_summary="status.get() returns counts and provider status.",
            full_schema={"type": "object", "properties": {}},
            examples=["status.get()"],
            timeout_sec=5,
            idempotent=True,
            permission_required="none",
        ),
        status_get,
    )

    def utility_echo(ctx: ToolCallContext, args: dict) -> dict:
        message = str(args.get("message", ""))
        return {
            "session_id": ctx.session_db_id,
            "task_id": ctx.task_id,
            "message": message,
            "length": len(message),
        }

    registry.register(
        ToolMetadata(
            name="utility.echo",
            version="1.0",
            risk_level="low",
            tags=["utility", "echo", "debug"],
            routing_summary="Echo back provided text for connectivity and tool-path checks.",
            invocation_summary="utility.echo(message) returns the same message and length.",
            full_schema={
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
            examples=["utility.echo(message='hello world')"],
            timeout_sec=3,
            idempotent=True,
            permission_required="none",
        ),
        utility_echo,
    )
