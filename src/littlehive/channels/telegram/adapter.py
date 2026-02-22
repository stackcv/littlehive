from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy import select

from littlehive.channels.telegram.auth import TelegramAllowlistAuth
from littlehive.core.config.loader import load_app_config
from littlehive.core.orchestrator.task_loop import TaskPipeline
from littlehive.core.providers.groq_adapter import GroqAdapter
from littlehive.core.providers.openai_compatible import OpenAICompatibleAdapter
from littlehive.core.providers.router import ProviderRouter
from littlehive.core.runtime.circuit_breaker import BreakerRegistry
from littlehive.core.runtime.locks import SessionLockManager
from littlehive.core.runtime.retries import RetryPolicy
from littlehive.core.telemetry.logging import get_logger
from littlehive.core.telemetry.tracing import recent_traces
from littlehive.core.tools.base import ToolCallContext
from littlehive.core.tools.builtin.memory_tools import register_memory_tools
from littlehive.core.tools.builtin.status_tools import register_status_tools
from littlehive.core.tools.builtin.task_tools import register_task_tools
from littlehive.core.tools.executor import ToolExecutor
from littlehive.core.tools.registry import ToolRegistry
from littlehive.db.models import SessionSummary, ToolCall
from littlehive.db.session import create_session_factory


@dataclass(slots=True)
class TelegramRuntime:
    auth: TelegramAllowlistAuth
    lock_manager: SessionLockManager
    pipeline: TaskPipeline
    tool_executor: ToolExecutor
    db_session_factory: object
    logger: object

    async def handle_user_text(self, user_id: int, chat_id: int, text: str) -> str:
        if not self.auth.is_allowed(user_id):
            return "Unauthorized. Ask the owner to allow your Telegram user ID."
        user_db_id, session_db_id = self.pipeline.ensure_user_session(user_id, chat_id)

        command = text.strip().split()[0] if text.strip().startswith("/") else ""
        if command == "/start":
            return "Welcome to LittleHive. Use /help to see commands."
        if command == "/help":
            return (
                "Commands: /start /help /status /memory /debug\n"
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
            if not traces:
                return "No traces captured yet."
            return "\n".join(f"{t['event']}:{t['status']}:{t['task_id']}" for t in traces)

        lock = await self.lock_manager.get_lock(f"telegram:{chat_id}")
        async with lock:
            response = await self.pipeline.run_for_telegram(telegram_user_id=user_id, chat_id=chat_id, user_text=text)
            return response.text


def build_telegram_runtime(config_path: str | None = None) -> TelegramRuntime:
    cfg = load_app_config(instance_path=config_path)
    logger = get_logger("littlehive.telegram")
    session_factory, _engine = create_session_factory(cfg.database.url)

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
            )
        )

    groq_cfg = cfg.providers.groq
    if groq_cfg.enabled and groq_cfg.api_key_env and os.getenv(groq_cfg.api_key_env):
        router.register(GroqAdapter(api_key_env=groq_cfg.api_key_env, timeout_seconds=groq_cfg.timeout_seconds))

    registry = ToolRegistry()
    register_memory_tools(registry, session_factory)
    register_task_tools(registry, session_factory)
    register_status_tools(registry, session_factory, router)

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
    )

    pipeline = TaskPipeline(cfg=cfg, db_session_factory=session_factory, tool_executor=executor, provider_router=router)

    return TelegramRuntime(
        auth=TelegramAllowlistAuth(cfg.channels.telegram),
        lock_manager=SessionLockManager(),
        pipeline=pipeline,
        tool_executor=executor,
        db_session_factory=session_factory,
        logger=logger,
    )
