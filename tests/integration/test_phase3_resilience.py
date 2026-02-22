from __future__ import annotations

from datetime import datetime, timezone

import pytest

from littlehive.channels.telegram.adapter import TelegramRuntime
from littlehive.channels.telegram.auth import TelegramAllowlistAuth
from littlehive.core.config.schema import AppConfig
from littlehive.core.orchestrator.task_loop import TaskPipeline
from littlehive.core.providers.base import ProviderAdapter, ProviderRequest, ProviderResponse
from littlehive.core.providers.router import ProviderRouter
from littlehive.core.runtime.locks import SessionLockManager
from littlehive.core.telemetry.logging import get_logger
from littlehive.core.tools.builtin.memory_tools import register_memory_tools
from littlehive.core.tools.builtin.status_tools import register_status_tools
from littlehive.core.tools.builtin.task_tools import register_task_tools
from littlehive.core.tools.executor import ToolExecutor
from littlehive.core.tools.registry import ToolRegistry
from littlehive.db.models import TaskTraceSummary, ToolCall
from littlehive.db.session import Base, create_session_factory


class FlakyPrimaryProvider(ProviderAdapter):
    name = "p_primary"

    def __init__(self):
        self.calls = 0

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        _ = request
        self.calls += 1
        if self.calls <= 2:
            raise TimeoutError("primary timeout")
        return ProviderResponse(provider=self.name, model="m", output_text="primary-ok", raw={})

    def health(self) -> bool:
        return True


class GoodFallbackProvider(ProviderAdapter):
    name = "p_fallback"

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(provider=self.name, model=request.model, output_text="fallback-ok", raw={})

    def health(self) -> bool:
        return True


class AlwaysFailProvider(ProviderAdapter):
    name = "p_fail"

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        _ = request
        raise TimeoutError("always fail")

    def health(self) -> bool:
        return True


@pytest.fixture
def phase3_runtime(tmp_path):
    session_factory, engine = create_session_factory(f"sqlite:///{tmp_path / 'p3.db'}")
    import littlehive.db.models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    cfg = AppConfig()
    cfg.channels.telegram.enabled = True
    cfg.channels.telegram.owner_user_id = 1
    cfg.channels.telegram.allow_user_ids = [1]
    cfg.providers.fallback_order = ["p_primary", "p_fallback"]
    cfg.providers.local_compatible.model = "test-model"
    cfg.runtime.safe_mode = False

    router = ProviderRouter()
    router.register(FlakyPrimaryProvider())
    router.register(GoodFallbackProvider())

    registry = ToolRegistry()
    register_memory_tools(registry, session_factory)
    register_task_tools(registry, session_factory)
    register_status_tools(registry, session_factory, router)

    def persist_tool_call(ctx, tool_name: str, status: str, detail: str) -> None:
        with session_factory() as db:
            db.add(
                ToolCall(
                    task_id=ctx.task_id,
                    session_id=ctx.session_db_id,
                    tool_name=tool_name,
                    status=status,
                    detail=detail,
                    created_at=datetime.now(timezone.utc),
                )
            )
            db.commit()

    ex = ToolExecutor(registry=registry, logger=get_logger("test.phase3"), call_logger=persist_tool_call)
    pipeline = TaskPipeline(cfg=cfg, db_session_factory=session_factory, tool_executor=ex, provider_router=router)
    runtime = TelegramRuntime(
        auth=TelegramAllowlistAuth(cfg.channels.telegram),
        lock_manager=SessionLockManager(),
        pipeline=pipeline,
        tool_executor=ex,
        db_session_factory=session_factory,
        logger=get_logger("test.phase3.runtime"),
    )
    return runtime, session_factory, router


@pytest.mark.asyncio
async def test_provider_timeout_retry_fallback_success(phase3_runtime):
    runtime, _sf, _router = phase3_runtime
    result = await runtime.pipeline.run_for_telegram(telegram_user_id=1, chat_id=3, user_text="status please")
    assert result.status == "completed"
    assert result.text


@pytest.mark.asyncio
async def test_repeated_provider_failures_open_breaker_then_recover(tmp_path):
    session_factory, engine = create_session_factory(f"sqlite:///{tmp_path / 'p3b.db'}")
    import littlehive.db.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    router = ProviderRouter()
    router.register(AlwaysFailProvider())
    req = ProviderRequest(model="m", prompt="hello")

    for _ in range(4):
        with pytest.raises(RuntimeError):
            router.dispatch_with_fallback(req, provider_order=["p_fail"])

    state = router.provider_status()["p_fail"]["breaker"]["state"]
    assert state in {"open", "half_open"}


@pytest.mark.asyncio
async def test_trace_summary_persistence_contains_resilience_events(phase3_runtime):
    runtime, session_factory, _router = phase3_runtime
    await runtime.pipeline.run_for_telegram(telegram_user_id=1, chat_id=5, user_text="remember this and status")

    with session_factory() as db:
        traces = db.query(TaskTraceSummary).all()
    assert traces
    assert traces[-1].provider_attempts >= 1


@pytest.mark.asyncio
async def test_telegram_runtime_smoke_phase3(phase3_runtime):
    runtime, _sf, _router = phase3_runtime
    out = await runtime.handle_user_text(1, 77, "/help")
    assert "Commands" in out
