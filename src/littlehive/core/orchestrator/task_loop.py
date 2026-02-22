from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select

from littlehive.core.agents.memory_agent import MemoryAgent
from littlehive.core.agents.orchestrator_agent import OrchestratorAgent
from littlehive.core.agents.reply_agent import ReplyAgent
from littlehive.core.config.schema import AppConfig
from littlehive.core.context.budget import TokenBudget
from littlehive.core.context.compiler import ChatTurn, ContextCompiler
from littlehive.core.providers.base import ProviderRequest
from littlehive.core.providers.router import ProviderRouter
from littlehive.core.runtime.retries import run_with_retries
from littlehive.core.runtime.timeouts import run_with_timeout
from littlehive.core.telemetry.logging import get_logger
from littlehive.core.telemetry.tracing import TraceContext, trace_event
from littlehive.core.tools.base import ToolCallContext
from littlehive.core.tools.executor import ToolExecutor
from littlehive.db.models import Message, ProviderCall, Session, Task, User


@dataclass(slots=True)
class PipelineResponse:
    text: str
    task_id: int
    status: str
    trace_id: str


class TaskPipeline:
    def __init__(
        self,
        *,
        cfg: AppConfig,
        db_session_factory,
        tool_executor: ToolExecutor,
        provider_router: ProviderRouter,
    ) -> None:
        self.cfg = cfg
        self.db_session_factory = db_session_factory
        self.tool_executor = tool_executor
        self.provider_router = provider_router
        self.logger = get_logger("littlehive.task_pipeline")
        self.compiler = ContextCompiler()
        self.orchestrator = OrchestratorAgent()
        self.memory_agent = MemoryAgent(tool_executor)
        self.reply_agent = ReplyAgent()

    def ensure_user_session(self, telegram_user_id: int, chat_id: int) -> tuple[int, int]:
        with self.db_session_factory() as db:
            user = db.execute(select(User).where(User.telegram_user_id == telegram_user_id)).scalar_one_or_none()
            if user is None:
                user = User(external_id=f"tg:{telegram_user_id}", telegram_user_id=telegram_user_id, created_at=datetime.utcnow())
                db.add(user)
                db.flush()

            external_session = f"telegram:{chat_id}"
            session = (
                db.execute(
                    select(Session).where(Session.channel == "telegram").where(Session.external_id == external_session)
                ).scalar_one_or_none()
            )
            if session is None:
                session = Session(
                    user_id=user.id,
                    channel="telegram",
                    external_id=external_session,
                    latest_summary="",
                    created_at=datetime.utcnow(),
                )
                db.add(session)
                db.flush()

            db.commit()
            return user.id, session.id

    def _recent_turns(self, session_id: int, cap: int) -> list[ChatTurn]:
        with self.db_session_factory() as db:
            rows = (
                db.execute(select(Message).where(Message.session_id == session_id).order_by(Message.id.desc()).limit(cap)).scalars().all()
            )
            rows.reverse()
            return [ChatTurn(role=m.role, content=m.content[:500]) for m in rows]

    def _persist_message(self, session_id: int, role: str, content: str, trace_id: str) -> None:
        with self.db_session_factory() as db:
            db.add(
                Message(
                    session_id=session_id,
                    role=role,
                    content=content[:4000],
                    trace_id=trace_id,
                    created_at=datetime.utcnow(),
                )
            )
            db.commit()

    def _log_provider_call(self, session_id: int, task_id: int, provider_name: str, model: str, status: str) -> None:
        with self.db_session_factory() as db:
            db.add(
                ProviderCall(
                    task_id=task_id,
                    session_id=session_id,
                    provider_name=provider_name,
                    model=model,
                    status=status,
                    detail="",
                    created_at=datetime.utcnow(),
                )
            )
            db.commit()

    async def run_for_telegram(self, telegram_user_id: int, chat_id: int, user_text: str) -> PipelineResponse:
        user_db_id, session_db_id = self.ensure_user_session(telegram_user_id, chat_id)
        trace_id = uuid.uuid4().hex[:12]

        task_ctx = ToolCallContext(session_db_id=session_db_id, user_db_id=user_db_id, task_id=None, trace_id=trace_id)
        task_record = self.tool_executor.execute("task.create", task_ctx, {"summary": user_text[:120]})
        task_id = int(task_record["task_id"])

        trace = TraceContext(
            request_id=trace_id,
            task_id=str(task_id),
            session_id=str(session_db_id),
            agent_id="orchestrator_agent",
            phase="phase1",
        )
        trace_event(self.logger, trace, event="task_start", status="ok")
        self._persist_message(session_db_id, "user", user_text, trace_id)

        task_ctx.task_id = task_id

        async def _run_once() -> str:
            if self.cfg.runtime.max_steps < 1:
                raise RuntimeError("max_steps must be >= 1")
            decision = self.orchestrator.decide(user_text)
            mem = self.memory_agent.handle(
                task_ctx,
                user_text=user_text,
                search=decision.should_search_memory,
                write=decision.should_write_memory,
                top_k=self.cfg.context.memory_top_k,
            )

            recent = self._recent_turns(session_db_id, self.cfg.context.recent_turns)
            compiled = self.compiler.compile(
                agent_role="reply_agent",
                system_prompt="You are LittleHive. Reply briefly and clearly.",
                user_message=user_text,
                recent_turns=recent,
                memory_snippets=mem.snippets[: self.cfg.context.snippet_cap],
                budget=TokenBudget(
                    max_input_tokens=self.cfg.context.max_input_tokens,
                    reserved_output_tokens=self.cfg.context.reserved_output_tokens,
                ),
            )
            trace_event(
                self.logger,
                trace,
                event="context_compiled",
                status="ok" if compiled.preflight and compiled.preflight.allowed else "trimmed",
                extra={
                    "estimated_tokens": compiled.preflight.estimated_input_tokens if compiled.preflight else -1,
                    "trim_actions": ",".join(compiled.trim_actions),
                },
            )

            provider_request = ProviderRequest(
                model=self.cfg.providers.local_compatible.model or "llama3.1:8b",
                prompt=compiled.prompt_text,
                max_output_tokens=self.cfg.context.reserved_output_tokens,
            )
            provider_response_text = ""
            try:
                provider_response = self.provider_router.dispatch_with_fallback(
                    provider_request,
                    provider_order=self.cfg.providers.fallback_order,
                    call_logger=lambda provider, model, status: self._log_provider_call(
                        session_db_id, task_id, provider, model, status
                    ),
                )
                provider_response_text = provider_response.output_text
            except Exception:  # noqa: BLE001
                provider_response_text = ""

            reply = self.reply_agent.compose(
                provider_text=provider_response_text,
                user_text=user_text,
                memory_snippets=compiled.included_memories,
            )
            self.tool_executor.execute(
                "memory.summarize",
                task_ctx,
                {},
            )
            return reply

        try:
            reply_text = await run_with_timeout(
                run_with_retries(_run_once, attempts=self.cfg.runtime.retry_attempts),
                timeout_seconds=self.cfg.runtime.request_timeout_seconds,
            )
            self.tool_executor.execute(
                "task.update",
                task_ctx,
                {
                    "task_id": task_id,
                    "status": "completed",
                    "step_index": 1,
                    "agent_id": "reply_agent",
                    "detail": "reply generated",
                },
            )
            status = "completed"
        except asyncio.TimeoutError:
            reply_text = "Request timed out. Please try again."
            self.tool_executor.execute(
                "task.update",
                task_ctx,
                {
                    "task_id": task_id,
                    "status": "failed",
                    "step_index": 1,
                    "agent_id": "orchestrator_agent",
                    "detail": "timeout",
                    "last_error": "timeout",
                },
            )
            status = "failed"
        except Exception as exc:  # noqa: BLE001
            reply_text = "I hit a runtime issue and could not complete that request."
            self.tool_executor.execute(
                "task.update",
                task_ctx,
                {
                    "task_id": task_id,
                    "status": "failed",
                    "step_index": 1,
                    "agent_id": "orchestrator_agent",
                    "detail": "exception",
                    "last_error": str(exc),
                },
            )
            status = "failed"

        self._persist_message(session_db_id, "assistant", reply_text, trace_id)
        trace_event(self.logger, trace, event="task_end", status=status)
        return PipelineResponse(text=reply_text, task_id=task_id, status=status, trace_id=trace_id)


def runtime_counts(db_session_factory) -> dict[str, int]:
    with db_session_factory() as db:
        return {
            "tasks": int(db.execute(select(func.count(Task.id))).scalar_one()),
            "messages": int(db.execute(select(func.count(Message.id))).scalar_one()),
        }


# Backward-compatible Phase 0 hook.
@dataclass(slots=True)
class DummyTaskResult:
    task_id: str
    status: str
    response_text: str


def run_dummy_task_pipeline() -> DummyTaskResult:
    return DummyTaskResult(task_id="phase1-dummy", status="ok", response_text="dummy-response")
