from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy import select

from littlehive.channels.telegram.auth import TelegramAllowlistAuth
from littlehive.core.admin.service import AdminService
from littlehive.core.config.loader import load_app_config
from littlehive.core.orchestrator.task_loop import TaskPipeline
from littlehive.core.permissions.policy_engine import PermissionProfile, PolicyEngine
from littlehive.core.providers.groq_adapter import GroqAdapter
from littlehive.core.providers.openai_compatible import OpenAICompatibleAdapter
from littlehive.core.providers.router import ProviderRouter
from littlehive.core.runtime.circuit_breaker import BreakerRegistry
from littlehive.core.runtime.locks import SessionLockManager
from littlehive.core.runtime.retries import RetryPolicy
from littlehive.core.telemetry.diagnostics import budget_stats, failure_summary, runtime_stats
from littlehive.core.telemetry.logging import get_logger
from littlehive.core.telemetry.tracing import recent_traces
from littlehive.core.tools.base import ToolCallContext
from littlehive.core.tools.builtin.memory_tools import register_memory_tools
from littlehive.core.tools.builtin.status_tools import register_status_tools
from littlehive.core.tools.builtin.task_tools import register_task_tools
from littlehive.core.tools.executor import ToolExecutor
from littlehive.core.tools.registry import ToolRegistry
from littlehive.db.models import SessionSummary, Task, ToolCall
from littlehive.db.session import Base, create_session_factory


@dataclass(slots=True)
class TelegramRuntime:
    auth: TelegramAllowlistAuth
    lock_manager: SessionLockManager
    pipeline: TaskPipeline
    tool_executor: ToolExecutor
    db_session_factory: object
    logger: object
    admin_service: AdminService | None = None

    async def handle_user_text(self, user_id: int, chat_id: int, text: str) -> str:
        if not self.auth.is_allowed(user_id):
            return "Unauthorized. Ask the owner to allow your Telegram user ID."
        user_db_id, session_db_id = self.pipeline.ensure_user_session(user_id, chat_id)

        command = text.strip().split()[0] if text.strip().startswith("/") else ""
        if command == "/start":
            return "Welcome to LittleHive. Use /help to see commands."
        if command == "/help":
            return (
                "Commands: /start /help /status /memory /debug /allow /deny\n"
                "Send any normal message to run the assistant pipeline."
            )

        if command == "/status":
            ctx = ToolCallContext(session_db_id=session_db_id, user_db_id=user_db_id, task_id=None, trace_id="status")
            status = self.tool_executor.execute("status.get", ctx, {})
            return (
                f"tasks={status['tasks']} memories={status['memories']} "
                f"provider_calls={status['provider_calls']} providers={status['providers']}"
            )

        if command == "/memory":
            with self.db_session_factory() as db:
                summary = (
                    db.execute(select(SessionSummary).where(SessionSummary.session_id == session_db_id)).scalar_one_or_none()
                )
            return summary.summary if summary and summary.summary else "No memory summary yet."

        if command == "/debug":
            if not self.auth.is_owner(user_id):
                return "Unauthorized debug command."
            traces = recent_traces(limit=5)
            rt = runtime_stats(self.db_session_factory)
            bs = budget_stats(self.db_session_factory)
            failures = failure_summary(self.db_session_factory, limit=3)
            trace_text = "\n".join(f"{t['event']}:{t['status']}:{t['task_id']}" for t in traces) if traces else "none"
            return (
                f"traces:\n{trace_text}\n"
                f"runtime={rt['tasks_by_status']}\n"
                f"budget_avg={bs['avg_estimated_prompt_tokens']} trims={bs['trim_event_count']}\n"
                f"failures={len(failures)}"
            )

        if command in {"/allow", "/deny"}:
            if not self.auth.is_owner(user_id):
                return "Unauthorized. Only owner can change access."
            if self.admin_service is None:
                return "Access control backend unavailable."
            parts = text.strip().split()
            if len(parts) < 2:
                return f"Usage: {command} <telegram_user_id>"
            target = parts[1].strip()
            if ":" in target:
                channel, external_id = target.split(":", 1)
                channel = channel.strip().lower()
                external_id = external_id.strip()
            else:
                channel = "telegram"
                external_id = target
            if not external_id:
                return "Invalid target. Expected user id or channel:user_id."
            allowed = command == "/allow"
            self.admin_service.set_principal_grant(
                channel=channel,
                external_id=external_id,
                grant_type="chat_access",
                allowed=allowed,
                actor=f"owner:{user_id}",
            )
            if command == "/deny":
                self.admin_service.set_principal_grant(
                    channel=channel,
                    external_id=external_id,
                    grant_type="owner",
                    allowed=False,
                    actor=f"owner:{user_id}",
                )
            return f"{'Allowed' if allowed else 'Denied'} {channel}:{external_id}"

        lock = await self.lock_manager.get_lock(f"telegram:{chat_id}")
        async with lock:
            response = await self.pipeline.run_for_telegram(telegram_user_id=user_id, chat_id=chat_id, user_text=text)
            return response.text


def build_telegram_runtime(config_path: str | None = None) -> TelegramRuntime:
    cfg = load_app_config(instance_path=config_path)
    logger = get_logger("littlehive.telegram")
    session_factory, engine = create_session_factory(cfg.database.url)
    import littlehive.db.models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    provider_breakers = BreakerRegistry(
        failure_threshold=cfg.runtime.breaker_failure_threshold,
        cool_down_seconds=cfg.runtime.breaker_cool_down_seconds,
    )
    provider_retry = RetryPolicy(max_attempts=cfg.runtime.provider_retry_attempts, base_backoff_seconds=0.08, jitter_seconds=0.04)
    router = ProviderRouter(retry_policy=provider_retry, breaker_registry=provider_breakers)

    local_cfg = cfg.providers.local_compatible
    if local_cfg.enabled and local_cfg.base_url:
        router.register(
            OpenAICompatibleAdapter(
                base_url=local_cfg.base_url,
                api_key_env=local_cfg.api_key_env,
                timeout_seconds=local_cfg.timeout_seconds,
                default_model=local_cfg.model,
            )
        )

    groq_cfg = cfg.providers.groq
    if groq_cfg.enabled and groq_cfg.api_key_env and os.getenv(groq_cfg.api_key_env):
        router.register(
            GroqAdapter(
                api_key_env=groq_cfg.api_key_env,
                timeout_seconds=groq_cfg.timeout_seconds,
                default_model=groq_cfg.model,
            )
        )

    registry = ToolRegistry()
    register_memory_tools(registry, session_factory)
    register_task_tools(registry, session_factory)
    register_status_tools(registry, session_factory, router)

    admin_service = AdminService(cfg=cfg, db_session_factory=session_factory, provider_router=router)
    admin_service.get_or_create_runtime_state()
    admin_service.bootstrap_telegram_grants()
    state = admin_service.get_or_create_permission_state()
    try:
        profile = PermissionProfile(state.current_profile)
    except ValueError:
        try:
            profile = PermissionProfile(cfg.runtime.permission_profile)
        except ValueError:
            profile = PermissionProfile.EXECUTE_SAFE
    policy_engine = PolicyEngine(profile=profile)

    def _persist_tool_call(ctx: ToolCallContext, tool_name: str, status: str, detail: str) -> None:
        with session_factory() as db:
            db.add(
                ToolCall(
                    task_id=ctx.task_id,
                    session_id=ctx.session_db_id,
                    tool_name=tool_name,
                    status=status,
                    detail=detail[:500],
                )
            )
            db.commit()

    def _create_confirmation(ctx: ToolCallContext, tool_name: str, args: dict) -> int:
        row = admin_service.create_confirmation(
            action_type="tool_invocation",
            action_summary=f"Approve tool {tool_name} for task {ctx.task_id}",
            payload={"tool_name": tool_name, "args": args},
            task_id=ctx.task_id,
            session_id=ctx.session_db_id,
            ttl_seconds=300,
        )
        if ctx.task_id is not None:
            with session_factory() as db:
                task = db.execute(select(Task).where(Task.id == ctx.task_id)).scalar_one_or_none()
                if task is not None:
                    task.status = "waiting_confirmation"
                    db.commit()
        return int(row.id)

    tool_breakers = BreakerRegistry(
        failure_threshold=max(2, cfg.runtime.breaker_failure_threshold + 1),
        cool_down_seconds=cfg.runtime.breaker_cool_down_seconds,
    )
    tool_retry = RetryPolicy(max_attempts=cfg.runtime.tool_retry_attempts, base_backoff_seconds=0.05, jitter_seconds=0.03)

    executor = ToolExecutor(
        registry=registry,
        logger=logger,
        call_logger=_persist_tool_call,
        retry_policy=tool_retry,
        breaker_registry=tool_breakers,
        policy_engine=policy_engine,
        safe_mode_getter=admin_service.get_safe_mode,
        create_confirmation=_create_confirmation,
    )

    pipeline = TaskPipeline(
        cfg=cfg,
        db_session_factory=session_factory,
        tool_executor=executor,
        provider_router=router,
        safe_mode_getter=admin_service.get_safe_mode,
    )

    return TelegramRuntime(
        auth=TelegramAllowlistAuth(cfg.channels.telegram, admin_service=admin_service),
        lock_manager=SessionLockManager(),
        pipeline=pipeline,
        tool_executor=executor,
        admin_service=admin_service,
        db_session_factory=session_factory,
        logger=logger,
    )
