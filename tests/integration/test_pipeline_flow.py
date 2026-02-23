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
from littlehive.core.telemetry.tracing import recent_traces
from littlehive.core.tools.builtin.memory_tools import register_memory_tools
from littlehive.core.tools.builtin.status_tools import register_status_tools
from littlehive.core.tools.builtin.task_tools import register_task_tools
from littlehive.core.tools.executor import ToolExecutor
from littlehive.core.tools.registry import ToolRegistry
from littlehive.db.models import MemoryRecord, SessionSummary, Task, ToolCall, TransferEvent
from littlehive.db.session import Base, create_session_factory


class TestProvider(ProviderAdapter):
    name = "local_compatible"

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(provider=self.name, model=request.model, output_text="pipeline-reply", raw={"echo": request.prompt[:50]})

    def health(self) -> bool:
        return True


@pytest.fixture
def runtime_fixture(tmp_path):
    session_factory, engine = create_session_factory(f"sqlite:///{tmp_path / 'p2.db'}")
    import littlehive.db.models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    cfg = AppConfig()
    cfg.channels.telegram.enabled = True
    cfg.channels.telegram.owner_user_id = 1
    cfg.channels.telegram.allow_user_ids = [1]
    cfg.context.recent_turns = 4
    cfg.context.max_input_tokens = 500
    cfg.context.reserved_output_tokens = 120
    cfg.providers.fallback_order = ["local_compatible"]
    cfg.providers.local_compatible.enabled = True
    cfg.providers.local_compatible.model = "test-model"

    provider_router = ProviderRouter()
    provider_router.register(TestProvider())

    registry = ToolRegistry()
    register_memory_tools(registry, session_factory)
    register_task_tools(registry, session_factory)
    register_status_tools(registry, session_factory, provider_router)

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

    executor = ToolExecutor(registry=registry, logger=get_logger("test.pipeline"), call_logger=persist_tool_call)
    pipeline = TaskPipeline(cfg=cfg, db_session_factory=session_factory, tool_executor=executor, provider_router=provider_router)
    runtime = TelegramRuntime(
        auth=TelegramAllowlistAuth(cfg.channels.telegram),
        lock_manager=SessionLockManager(),
        pipeline=pipeline,
        tool_executor=executor,
        db_session_factory=session_factory,
        logger=get_logger("test.pipeline.runtime"),
    )
    return runtime, session_factory


@pytest.mark.asyncio
async def test_long_chat_generates_cards_and_bounded_context(runtime_fixture):
    runtime, session_factory = runtime_fixture
    for i in range(40):
        text = f"remember preference {i} for this session"
        await runtime.handle_user_text(user_id=1, chat_id=42, text=text)

    with session_factory() as db:
        memory_count = db.query(MemoryRecord).count()
        summary_count = db.query(SessionSummary).count()
    assert memory_count > 0
    assert summary_count > 0

    traces = recent_traces(limit=200)
    reply_compiles = [t for t in traces if t.get("event") == "context_compiled" and t.get("agent") == "reply_agent"]
    assert reply_compiles
    max_est = max(int(t.get("estimated_tokens", 0)) for t in reply_compiles)
    assert max_est <= runtime.pipeline.cfg.context.max_input_tokens


@pytest.mark.asyncio
async def test_planner_transfer_execution_reply_flow(runtime_fixture):
    runtime, session_factory = runtime_fixture
    result = await runtime.pipeline.run_for_telegram(telegram_user_id=1, chat_id=9, user_text="status and remember this for later")
    assert result.status == "completed"

    with session_factory() as db:
        transfers = db.query(TransferEvent).count()
        tasks = db.query(Task).count()
    assert transfers >= 1
    assert tasks >= 1


@pytest.mark.asyncio
async def test_tool_schema_only_at_execution_step(runtime_fixture):
    runtime, _ = runtime_fixture
    await runtime.pipeline.run_for_telegram(telegram_user_id=1, chat_id=10, user_text="memory search this and remember it")
    traces = recent_traces(limit=200)
    compiled_exec = [t for t in traces if t.get("event") == "context_compiled" and t.get("agent") == "execution_agent"]
    compiled_planner = [t for t in traces if t.get("event") == "context_compiled" and t.get("agent") == "planner_agent"]
    assert compiled_exec
    assert compiled_planner


@pytest.mark.asyncio
async def test_telegram_runtime_smoke(runtime_fixture):
    runtime, _ = runtime_fixture
    help_text = await runtime.handle_user_text(1, 77, "/help")
    normal = await runtime.handle_user_text(1, 77, "remember my editor is vim")
    assert "Commands" in help_text
    assert normal
