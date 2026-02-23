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
from littlehive.core.tools.injection import build_tool_docs_bundle
from littlehive.core.tools.registry import ToolRegistry
from littlehive.db.models import ToolCall
from littlehive.db.session import Base, create_session_factory


class TestProvider(ProviderAdapter):
    name = "local_compatible"

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(provider=self.name, model=request.model, output_text="longevity-reply", raw={})

    def health(self) -> bool:
        return True


@pytest.fixture
def runtime_fixture(tmp_path):
    session_factory, engine = create_session_factory(f"sqlite:///{tmp_path / 'p2_long.db'}")
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

    executor = ToolExecutor(registry=registry, logger=get_logger("test.longevity"), call_logger=persist_tool_call)
    pipeline = TaskPipeline(cfg=cfg, db_session_factory=session_factory, tool_executor=executor, provider_router=provider_router)
    runtime = TelegramRuntime(
        auth=TelegramAllowlistAuth(cfg.channels.telegram),
        lock_manager=SessionLockManager(),
        pipeline=pipeline,
        tool_executor=executor,
        db_session_factory=session_factory,
        logger=get_logger("test.longevity.runtime"),
    )
    return runtime, session_factory


@pytest.mark.asyncio
async def test_long_session_prompt_growth_bounded(runtime_fixture):
    runtime, _ = runtime_fixture
    for i in range(120):
        await runtime.handle_user_text(1, 999, f"remember long run preference #{i}")

    traces = recent_traces(limit=500)
    reply_compiles = [t for t in traces if t.get("event") == "context_compiled" and t.get("agent") == "reply_agent"]
    assert reply_compiles
    first = int(reply_compiles[0].get("estimated_tokens", 1))
    last = int(reply_compiles[-1].get("estimated_tokens", 1))
    assert last <= runtime.pipeline.cfg.context.max_input_tokens
    assert last <= max(first * 4, 120)


@pytest.mark.asyncio
async def test_no_global_tool_schema_dump_across_steps(runtime_fixture):
    runtime, _ = runtime_fixture
    registry = runtime.tool_executor.registry

    for i in range(5):
        routing = build_tool_docs_bundle(registry=registry, query=f"memory {i}", mode="routing")
        full = build_tool_docs_bundle(
            registry=registry,
            query=f"memory {i}",
            mode="full_for_selected",
            selected_tool_names=[routing.routing[0]["name"]] if routing.routing else [],
        )
        assert not routing.full
        assert len(full.full) <= 1
