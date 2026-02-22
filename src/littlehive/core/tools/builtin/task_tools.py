from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from littlehive.db.models import Task, TaskStep
from littlehive.core.tools.base import ToolCallContext, ToolMetadata


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def register_task_tools(registry, db_session_factory):
    def task_create(ctx: ToolCallContext, args: dict) -> dict:
        summary = (args.get("summary") or "")[:512]
        with db_session_factory() as db:
            task = Task(
                session_id=ctx.session_db_id,
                status="running",
                summary=summary,
                last_error="",
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            db.add(task)
            db.flush()
            db.commit()
            return {"task_id": task.id, "status": task.status}

    def task_update(ctx: ToolCallContext, args: dict) -> dict:
        task_id = int(args["task_id"])
        status = args.get("status", "running")
        step_index = int(args.get("step_index", 0))
        detail = (args.get("detail") or "")[:1000]
        with db_session_factory() as db:
            task = db.execute(select(Task).where(Task.id == task_id)).scalar_one()
            task.status = status
            task.updated_at = _utcnow()
            if "last_error" in args:
                task.last_error = (args.get("last_error") or "")[:1000]
            step = TaskStep(
                task_id=task.id,
                step_index=step_index,
                agent_id=args.get("agent_id", "orchestrator_agent"),
                status=status,
                detail=detail,
                created_at=_utcnow(),
            )
            db.add(step)
            db.flush()
            db.commit()
            return {"task_id": task.id, "status": task.status, "step_id": step.id}

    registry.register(
        ToolMetadata(
            name="task.create",
            version="2.0",
            risk_level="low",
            tags=["task", "lifecycle"],
            routing_summary="Create task record for current request.",
            invocation_summary="task.create(summary) returns task_id.",
            full_schema={"type": "object", "properties": {"summary": {"type": "string"}}},
            examples=["task.create(summary='answer user request')"],
            timeout_sec=8,
            idempotent=False,
            permission_required="none",
        ),
        task_create,
    )
    registry.register(
        ToolMetadata(
            name="task.update",
            version="2.0",
            risk_level="low",
            tags=["task", "lifecycle", "step"],
            routing_summary="Update task status and append execution step.",
            invocation_summary="task.update(task_id, status, step_index, detail).",
            full_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer"},
                    "status": {"type": "string"},
                    "step_index": {"type": "integer"},
                    "detail": {"type": "string"},
                    "last_error": {"type": "string"},
                },
                "required": ["task_id", "status"],
            },
            examples=["task.update(task_id=1, status='completed', step_index=2, detail='reply ready')"],
            timeout_sec=8,
            idempotent=False,
            permission_required="none",
        ),
        task_update,
    )
