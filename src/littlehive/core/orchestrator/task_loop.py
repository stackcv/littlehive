from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from littlehive.core.agents.execution_agent import ExecutionAgent
from littlehive.core.agents.memory_agent import MemoryAgent
from littlehive.core.agents.orchestrator_agent import OrchestratorAgent
from littlehive.core.agents.planner_agent import PlannerAgent
from littlehive.core.agents.reply_agent import ReplyAgent
from littlehive.core.config.schema import AppConfig
from littlehive.core.context.budget import TokenBudget
from littlehive.core.context.compiler import ChatTurn, ContextCompiler
from littlehive.core.memory.cards import should_compact
from littlehive.core.orchestrator.handoff import Transfer
from littlehive.core.providers.base import ProviderRequest
from littlehive.core.providers.router import ProviderRouter
from littlehive.core.runtime.errors import classify_error
from littlehive.core.runtime.recovery import (
    compact_failure_message,
    mark_recovered,
    reflexion_lite_decide,
    should_trigger_reflexion,
    upsert_failure_fingerprint,
)
from littlehive.core.runtime.retries import run_with_retries
from littlehive.core.runtime.timeouts import run_with_timeout
from littlehive.core.telemetry.logging import get_logger
from littlehive.core.telemetry.summary import persist_task_trace_summary
from littlehive.core.telemetry.tracing import TraceContext, trace_event
from littlehive.core.tools.base import ToolCallContext
from littlehive.core.tools.executor import ToolExecutor
from littlehive.db.models import Message, ProviderCall, Session, Task, TransferEvent, User
from littlehive.db.models import ToolCall


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
        safe_mode_getter=None,
    ) -> None:
        self.cfg = cfg
        self.db_session_factory = db_session_factory
        self.tool_executor = tool_executor
        self.provider_router = provider_router
        self.logger = get_logger("littlehive.task_pipeline")
        self.compiler = ContextCompiler()
        self.orchestrator = OrchestratorAgent()
        self.memory_agent = MemoryAgent(tool_executor)
        self.planner = PlannerAgent()
        self.execution = ExecutionAgent(
            tool_executor.registry,
            tool_executor,
            history_loader=self._recent_tool_names,
        )
        self.reply_agent = ReplyAgent()
        self._task_reuse_window = timedelta(minutes=45)
        self._safe_mode_getter = safe_mode_getter or (lambda: bool(self.cfg.runtime.safe_mode))

    def _safe_mode(self) -> bool:
        return bool(self._safe_mode_getter())

    def _default_model(self) -> str:
        preferred = (self.cfg.providers.primary or "").strip()
        if preferred == "groq":
            if self.cfg.providers.groq.model:
                return self.cfg.providers.groq.model
            if self.cfg.providers.local_compatible.model:
                return self.cfg.providers.local_compatible.model
        else:
            if self.cfg.providers.local_compatible.model:
                return self.cfg.providers.local_compatible.model
            if self.cfg.providers.groq.model:
                return self.cfg.providers.groq.model
        return "llama3.1:8b"

    def ensure_user_session(self, telegram_user_id: int, chat_id: int) -> tuple[int, int]:
        with self.db_session_factory() as db:
            user = db.execute(select(User).where(User.telegram_user_id == telegram_user_id)).scalar_one_or_none()
            if user is None:
                user = User(external_id=f"tg:{telegram_user_id}", telegram_user_id=telegram_user_id, created_at=_utcnow())
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
                    created_at=_utcnow(),
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

    def _recent_tool_names(self, session_id: int, cap: int = 8) -> list[str]:
        with self.db_session_factory() as db:
            rows = (
                db.execute(
                    select(ToolCall)
                    .where(ToolCall.session_id == session_id)
                    .where(ToolCall.status == "ok")
                    .order_by(ToolCall.id.desc())
                    .limit(cap)
                )
                .scalars()
                .all()
            )
        rows.reverse()
        return [r.tool_name for r in rows if isinstance(r.tool_name, str) and r.tool_name.strip()]

    def _persist_message(self, session_id: int, role: str, content: str, trace_id: str) -> None:
        with self.db_session_factory() as db:
            db.add(
                Message(
                    session_id=session_id,
                    role=role,
                    content=content[:4000],
                    trace_id=trace_id,
                    created_at=_utcnow(),
                )
            )
            db.commit()

    def _log_provider_call(self, session_id: int, task_id: int, provider_name: str, model: str, status: str, trace: TraceContext) -> None:
        with self.db_session_factory() as db:
            db.add(
                ProviderCall(
                    task_id=task_id,
                    session_id=session_id,
                    provider_name=provider_name,
                    model=model,
                    status=status,
                    detail="",
                    created_at=_utcnow(),
                )
            )
            db.commit()
        trace_event(
            self.logger,
            trace,
            event="provider_attempt",
            status=status,
            extra={"provider": provider_name, "model": model},
        )

    def _log_transfer_event(self, task_id: int, session_id: int, trace_id: str, transfer: Transfer) -> None:
        with self.db_session_factory() as db:
            db.add(
                TransferEvent(
                    task_id=task_id,
                    session_id=session_id,
                    from_agent="planner_agent",
                    to_agent=transfer.target_agent,
                    subtask=transfer.subtask[:512],
                    relevant_memory_ids=",".join(str(x) for x in transfer.relevant_memory_ids),
                    trace_id=trace_id,
                    created_at=_utcnow(),
                )
            )
            db.commit()

    def _upsert_failure(self, info):
        with self.db_session_factory() as db:
            row = upsert_failure_fingerprint(db, info)
            db.commit()
            return row.id

    def _mark_recovered(self, fingerprint_id: int, strategy: str) -> None:
        with self.db_session_factory() as db:
            mark_recovered(db, fingerprint_id=fingerprint_id, strategy=strategy)
            db.commit()

    def _user_context_metadata(self, user_id: int) -> dict:
        with self.db_session_factory() as db:
            row = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if row is None:
            return {}
        profile = {
            "name": row.display_name,
            "timezone": row.preferred_timezone,
            "city": row.city,
            "country": row.country,
            "notes": row.profile_notes,
        }
        compact = {k: v for k, v in profile.items() if isinstance(v, str) and v.strip()}
        return {"user_profile": compact} if compact else {}

    def _reuse_recent_task(self, session_id: int) -> int | None:
        cutoff = _utcnow() - self._task_reuse_window
        with self.db_session_factory() as db:
            row = (
                db.execute(select(Task).where(Task.session_id == session_id).order_by(Task.updated_at.desc()).limit(1))
                .scalars()
                .first()
            )
            if row is None:
                return None
            threshold = cutoff if getattr(row.updated_at, "tzinfo", None) else cutoff.replace(tzinfo=None)
            return int(row.id) if row.updated_at >= threshold else None

    async def run_for_telegram(self, telegram_user_id: int, chat_id: int, user_text: str) -> PipelineResponse:
        user_db_id, session_db_id = self.ensure_user_session(telegram_user_id, chat_id)
        trace_id = uuid.uuid4().hex[:12]

        task_ctx = ToolCallContext(session_db_id=session_db_id, user_db_id=user_db_id, task_id=None, trace_id=trace_id)
        reused_task_id = self._reuse_recent_task(session_db_id)
        if reused_task_id is None:
            task_record = self.tool_executor.execute("task.create", task_ctx, {"summary": user_text[:120]})
            task_id = int(task_record["task_id"])
        else:
            task_id = reused_task_id
            task_ctx.task_id = task_id
            self.tool_executor.execute(
                "task.update",
                task_ctx,
                {
                    "task_id": task_id,
                    "status": "running",
                    "step_index": 0,
                    "agent_id": "orchestrator_agent",
                    "detail": "new message turn",
                },
            )

        trace = TraceContext(
            request_id=trace_id,
            task_id=str(task_id),
            session_id=str(session_db_id),
            agent_id="orchestrator_agent",
            phase="phase3",
        )
        trace_event(self.logger, trace, event="task_start", status="ok")
        self._persist_message(session_db_id, "user", user_text, trace_id)
        user_meta = self._user_context_metadata(user_db_id)

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
            budget = TokenBudget(
                max_input_tokens=self.cfg.context.max_input_tokens,
                reserved_output_tokens=self.cfg.context.reserved_output_tokens,
            )

            planner_compiled = self.compiler.compile(
                agent_role="planner_agent",
                system_prompt="Plan in compact steps and prefer tool retrieval over large schemas.",
                user_message=user_text,
                recent_turns=recent,
                memory_snippets=mem.snippets[: self.cfg.context.snippet_cap],
                budget=budget,
                task_payload="determine whether transfer to execution is needed",
                tool_context_mode="routing",
                allowed_tool_names=self.tool_executor.list_allowed_tool_names(),
                tool_registry=self.tool_executor.registry,
                tool_query=user_text,
                extra_metadata={"phase": "planner", **user_meta},
            )
            trace_event(
                self.logger,
                trace,
                event="context_compiled",
                status="ok" if not planner_compiled.over_budget else "over_budget",
                extra={
                    "agent": "planner_agent",
                    "estimated_tokens": planner_compiled.preflight.estimated_input_tokens if planner_compiled.preflight else -1,
                    "sections": ",".join(planner_compiled.included_sections),
                    "trim_actions": ",".join(planner_compiled.trim_actions),
                },
            )
            if planner_compiled.over_budget:
                raise RuntimeError("planner_context_over_budget")

            planner_output = self.planner.plan(
                user_text=user_text,
                session_id=str(session_db_id),
                task_id=str(task_id),
                request_id=trace_id,
                max_input_tokens=budget.max_input_tokens,
                reserved_output_tokens=budget.reserved_output_tokens,
            )

            execution_summary = ""
            if planner_output.transfer is not None:
                self._log_transfer_event(task_id, session_db_id, trace_id, planner_output.transfer)
                trace_event(
                    self.logger,
                    trace,
                    event="transfer_created",
                    status="ok",
                    extra={
                        "from_agent": "planner_agent",
                        "to_agent": planner_output.transfer.target_agent,
                        "subtask": planner_output.transfer.subtask[:120],
                    },
                )

                execution_compiled = self.compiler.compile(
                    agent_role="execution_agent",
                    system_prompt="Execute with bounded tool docs and structured output.",
                    user_message="",
                    recent_turns=[],
                    memory_snippets=mem.snippets[:2],
                    budget=budget,
                    handoff_payload=planner_output.transfer.model_dump_json(),
                    tool_context_mode="invocation",
                    selected_tool_names=[],
                    allowed_tool_names=self.tool_executor.list_allowed_tool_names(),
                    tool_registry=self.tool_executor.registry,
                    tool_query=planner_output.tool_intent_query,
                    extra_metadata={"phase": "execution", **user_meta},
                )
                trace_event(
                    self.logger,
                    trace,
                    event="context_compiled",
                    status="ok" if not execution_compiled.over_budget else "over_budget",
                    extra={
                        "agent": "execution_agent",
                        "estimated_tokens": execution_compiled.preflight.estimated_input_tokens if execution_compiled.preflight else -1,
                        "sections": ",".join(execution_compiled.included_sections),
                        "trim_actions": ",".join(execution_compiled.trim_actions),
                    },
                )
                if execution_compiled.over_budget:
                    raise RuntimeError("execution_context_over_budget")

                exec_result = self.execution.execute_from_transfer(planner_output.transfer, task_ctx)
                trace_event(
                    self.logger,
                    trace,
                    event="tool_doc_injection",
                    status="ok",
                    extra={
                        "routing_count": exec_result.injection_log.get("routing_count", 0),
                        "invocation_count": exec_result.injection_log.get("invocation_count", 0),
                        "full_schema_count": exec_result.injection_log.get("full_schema_count", 0),
                        "confidence": exec_result.confidence,
                        "needs_clarification": int(exec_result.needs_clarification),
                    },
                )
                if exec_result.needs_clarification:
                    trace_event(
                        self.logger,
                        trace,
                        event="tool_selection",
                        status="low_confidence",
                        extra={"confidence": exec_result.confidence},
                    )
                    return exec_result.clarification_question
                execution_summary = f"tools={exec_result.selected_tools}; outputs={exec_result.outputs}"

            reply_compiled = self.compiler.compile(
                agent_role="reply_agent",
                system_prompt="You are LittleHive. Reply briefly and clearly.",
                user_message=user_text,
                recent_turns=recent,
                memory_snippets=mem.snippets[: self.cfg.context.snippet_cap],
                budget=budget,
                task_payload=execution_summary[:900] if execution_summary else "",
                tool_context_mode="none",
                extra_metadata={"phase": "reply", **user_meta},
            )
            trace_event(
                self.logger,
                trace,
                event="context_compiled",
                status="ok" if not reply_compiled.over_budget else "over_budget",
                extra={
                    "agent": "reply_agent",
                    "estimated_tokens": reply_compiled.preflight.estimated_input_tokens if reply_compiled.preflight else -1,
                    "sections": ",".join(reply_compiled.included_sections),
                    "trim_actions": ",".join(reply_compiled.trim_actions),
                },
            )
            if reply_compiled.over_budget:
                raise RuntimeError("reply_context_over_budget")

            provider_request = ProviderRequest(
                model=self._default_model(),
                prompt=reply_compiled.prompt_text,
                max_output_tokens=self.cfg.context.reserved_output_tokens,
            )
            if bool(getattr(self.cfg.telemetry, "log_compiled_prompts", False)):
                cap = int(getattr(self.cfg.telemetry, "prompt_log_max_chars", 4000))
                prompt_text = reply_compiled.prompt_text
                trace_event(
                    self.logger,
                    trace,
                    event="llm_prompt_compiled",
                    status="debug",
                    extra={
                        "prompt_chars": len(prompt_text),
                        "prompt_preview": prompt_text[:cap],
                    },
                )
            provider_response_text = ""
            fallback_order = list(self.cfg.providers.fallback_order)
            fingerprint_id = None

            try:
                provider_response = self.provider_router.dispatch_with_fallback(
                    provider_request,
                    provider_order=fallback_order,
                    call_logger=lambda provider, model, status: self._log_provider_call(
                        session_db_id, task_id, provider, model, status, trace
                    ),
                )
                provider_response_text = provider_response.output_text
            except Exception as exc:  # noqa: BLE001
                info = classify_error(exc, category="provider", component="router")
                fingerprint_id = self._upsert_failure(info)
                compact = compact_failure_message(exc)
                trace_event(self.logger, trace, event="provider_failure", status="error", extra={"error": compact})

                if should_trigger_reflexion(
                    error_retryable=info.retryable,
                    attempts_used=0,
                    max_per_step=self.cfg.runtime.reflexion_max_per_step,
                    safe_mode=self._safe_mode(),
                ):
                    reflexion_context = self.compiler.compile(
                        agent_role="recovery_agent",
                        system_prompt="Produce compact retry strategy only.",
                        user_message=f"error={compact}",
                        recent_turns=[],
                        memory_snippets=mem.snippets[:1],
                        budget=TokenBudget(max_input_tokens=min(300, budget.max_input_tokens), reserved_output_tokens=64),
                        task_payload="recover provider call",
                        extra_metadata={"phase": "reflexion"},
                    )
                    trace_event(
                        self.logger,
                        trace,
                        event="context_compiled",
                        status="ok",
                        extra={
                            "agent": "recovery_agent",
                            "estimated_tokens": reflexion_context.preflight.estimated_input_tokens if reflexion_context.preflight else -1,
                            "sections": ",".join(reflexion_context.included_sections),
                            "trim_actions": ",".join(reflexion_context.trim_actions),
                        },
                    )

                    decision = reflexion_lite_decide(
                        error_summary=compact,
                        has_fallback_provider=len(fallback_order) > 1,
                        safe_mode=self._safe_mode(),
                    )
                    trace_event(
                        self.logger,
                        trace,
                        event="reflexion_decision",
                        status="ok",
                        extra={"strategy": decision.strategy, "confidence": decision.confidence, "reason": decision.reason[:160]},
                    )

                    try:
                        if decision.strategy == "switch_provider" and not self._safe_mode():
                            provider_response = self.provider_router.dispatch_with_fallback(
                                provider_request,
                                provider_order=list(reversed(fallback_order)),
                                call_logger=lambda provider, model, status: self._log_provider_call(
                                    session_db_id, task_id, provider, model, status, trace
                                ),
                            )
                            provider_response_text = provider_response.output_text
                        elif decision.strategy == "reduce_context":
                            reduced = self.compiler.compile(
                                agent_role="reply_agent",
                                system_prompt="You are LittleHive. Reply briefly and clearly.",
                                user_message=user_text[:120],
                                recent_turns=recent[-2:],
                                memory_snippets=mem.snippets[:1],
                                budget=TokenBudget(max_input_tokens=max(180, budget.max_input_tokens // 2), reserved_output_tokens=budget.reserved_output_tokens),
                                task_payload=execution_summary[:250],
                            )
                            provider_request.prompt = reduced.prompt_text
                            provider_response = self.provider_router.dispatch_with_fallback(
                                provider_request,
                                provider_order=fallback_order,
                                call_logger=lambda provider, model, status: self._log_provider_call(
                                    session_db_id, task_id, provider, model, status, trace
                                ),
                            )
                            provider_response_text = provider_response.output_text
                        elif decision.strategy == "retry_same":
                            trace_event(self.logger, trace, event="reflexion_retry", status="ok")
                            provider_response = self.provider_router.dispatch_with_fallback(
                                provider_request,
                                provider_order=fallback_order,
                                call_logger=lambda provider, model, status: self._log_provider_call(
                                    session_db_id, task_id, provider, model, status, trace
                                ),
                            )
                            provider_response_text = provider_response.output_text
                        elif decision.strategy in {"skip_tool", "abort"}:
                            provider_response_text = ""

                        if provider_response_text and fingerprint_id is not None:
                            self._mark_recovered(fingerprint_id, decision.strategy)
                            if decision.strategy in {"switch_provider", "reduce_context", "retry_same"}:
                                self.tool_executor.execute(
                                    "memory.failure_fix",
                                    task_ctx,
                                    {
                                        "error_signature": info.message_signature,
                                        "fix": f"Recovered via {decision.strategy}",
                                        "source": "provider",
                                    },
                                )
                    except Exception as recovery_exc:  # noqa: BLE001
                        trace_event(
                            self.logger,
                            trace,
                            event="reflexion_failed",
                            status="error",
                            extra={"error": compact_failure_message(recovery_exc)},
                        )

            reply = self.reply_agent.compose(
                provider_text=provider_response_text,
                user_text=user_text,
                memory_snippets=reply_compiled.included_memories,
            )

            if should_compact(
                turn_count=len(recent) + 1,
                token_estimate=reply_compiled.preflight.estimated_input_tokens if reply_compiled.preflight else 0,
            ):
                self.tool_executor.execute("memory.summarize", task_ctx, {})

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
            info = classify_error(exc, category="runtime", component="task_pipeline")
            self._upsert_failure(info)
            self.tool_executor.execute(
                "task.update",
                task_ctx,
                {
                    "task_id": task_id,
                    "status": "failed",
                    "step_index": 1,
                    "agent_id": "orchestrator_agent",
                    "detail": "exception",
                    "last_error": compact_failure_message(exc),
                },
            )
            status = "failed"

        self._persist_message(session_db_id, "assistant", reply_text, trace_id)
        trace_event(self.logger, trace, event="task_end", status=status)
        persist_task_trace_summary(
            self.db_session_factory,
            task_id=task_id,
            session_id=session_db_id,
            request_id=trace_id,
            outcome_status=status,
        )
        return PipelineResponse(text=reply_text, task_id=task_id, status=status, trace_id=trace_id)


def runtime_counts(db_session_factory) -> dict[str, int]:
    with db_session_factory() as db:
        return {
            "tasks": int(db.execute(select(func.count(Task.id))).scalar_one()),
            "messages": int(db.execute(select(func.count(Message.id))).scalar_one()),
        }


@dataclass(slots=True)
class DummyTaskResult:
    task_id: str
    status: str
    response_text: str


def run_dummy_task_pipeline() -> DummyTaskResult:
    return DummyTaskResult(task_id="phase3-dummy", status="ok", response_text="dummy-response")
