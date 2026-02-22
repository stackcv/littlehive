from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from littlehive.db.models import Task, TaskStep
from littlehive.core.tools.base import ToolCallContext, ToolMetadata


def register_task_tools(registry, db_session_factory):
    def task_create(ctx: ToolCallContext, args: dict) -> dict:
        summary = (args.get("summary") or "")[:512]
        with db_session_factory() as db:
            task = Task(
                session_id=ctx.session_db_id,
                status="running",
                summary=summary,
                last_error="",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
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
            task.updated_at = datetime.utcnow()
            if "last_error" in args:
                task.last_error = (args.get("last_error") or "")[:1000]
            step = TaskStep(
                task_id=task.id,
                step_index=step_index,
                agent_id=args.get("agent_id", "orchestrator_agent"),
                status=status,
                detail=detail,
                created_at=datetime.utcnow(),
            )
            db.add(step)
            db.flush()
            db.commit()
            return {"task_id": task.id, "status": task.status, "step_id": step.id}

    registry.register(
        ToolMetadata(
            name="task.create",
            routing_summary="Create a task for session pipeline processing.",
            invocation_summary="task.create(summary)",
            full_schema={"type": "object", "properties": {"summary": {"type": "string"}}},
        ),
        task_create,
    )
    registry.register(
        ToolMetadata(
            name="task.update",
            routing_summary="Update task status and record step.",
            invocation_summary="task.update(task_id, status, step_index)",
            full_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer"},
                    "status": {"type": "string"},
                    "step_index": {"type": "integer"},
                    "detail": {"type": "string"},
                },
            },
        ),
        task_update,
    )
