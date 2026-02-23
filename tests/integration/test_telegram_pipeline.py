from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from littlehive.channels.telegram.adapter import TelegramRuntime
from littlehive.channels.telegram.auth import TelegramAllowlistAuth
from littlehive.channels.telegram.handlers import TelegramHandlers
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
from littlehive.db.models import Message, Task, ToolCall
from littlehive.db.session import Base, create_session_factory


class TestProvider(ProviderAdapter):
    name = "local_compatible"

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        _ = request
        return ProviderResponse(provider=self.name, model="test-model", output_text="test-reply", raw={})

    def health(self) -> bool:
        return True


@dataclass
class FakeUser:
    id: int


@dataclass
class FakeChat:
    id: int


class FakeMessage:
    def __init__(self, text: str):
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


class FakeUpdate:
    def __init__(self, user_id: int, chat_id: int, text: str):
        self.effective_user = FakeUser(id=user_id)
        self.effective_chat = FakeChat(id=chat_id)
        self.effective_message = FakeMessage(text=text)


@pytest.fixture
def runtime_fixture(tmp_path):
    db_file = tmp_path / "telegram_pipeline.db"
    session_factory, engine = create_session_factory(f"sqlite:///{db_file}")
    import littlehive.db.models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    cfg = AppConfig()
    cfg.channels.telegram.enabled = True
    cfg.channels.telegram.owner_user_id = 1
    cfg.channels.telegram.allow_user_ids = [1]
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
                    created_at=datetime.now(UTC),
                )
            )
            db.commit()

    executor = ToolExecutor(registry=registry, logger=get_logger("test"), call_logger=persist_tool_call)
    pipeline = TaskPipeline(cfg=cfg, db_session_factory=session_factory, tool_executor=executor, provider_router=provider_router)
    runtime = TelegramRuntime(
        auth=TelegramAllowlistAuth(cfg.channels.telegram),
        lock_manager=SessionLockManager(),
        pipeline=pipeline,
        tool_executor=executor,
        db_session_factory=session_factory,
        logger=get_logger("test.runtime"),
    )
    return runtime, session_factory


@pytest.mark.asyncio
async def test_telegram_handler_to_pipeline_response(runtime_fixture):
    runtime, session_factory = runtime_fixture
    handlers = TelegramHandlers(runtime)
    update = FakeUpdate(user_id=1, chat_id=11, text="hello")

    await handlers.handle_update(update, context=None)

    assert update.effective_message.replies
    assert "test-reply" in update.effective_message.replies[0]

    with session_factory() as db:
        assert db.query(Task).count() >= 1
        assert db.query(Message).count() >= 2


@pytest.mark.asyncio
async def test_task_loop_persists_task_status_transitions(runtime_fixture):
    runtime, session_factory = runtime_fixture
    result = await runtime.pipeline.run_for_telegram(telegram_user_id=1, chat_id=77, user_text="hello world")
    assert result.status == "completed"

    with session_factory() as db:
        task = db.query(Task).order_by(Task.id.desc()).first()
        assert task is not None
        assert task.status == "completed"


@pytest.mark.asyncio
async def test_memory_write_and_search_one_session(runtime_fixture):
    runtime, session_factory = runtime_fixture
    response = await runtime.handle_user_text(user_id=1, chat_id=55, text="remember that my tea is masala chai")
    assert response

    user_db_id, session_db_id = runtime.pipeline.ensure_user_session(1, 55)
    ctx = type("Ctx", (), {"session_db_id": session_db_id, "user_db_id": user_db_id, "task_id": None, "trace_id": "t"})()
    search = runtime.tool_executor.execute("memory.search", ctx, {"query": "chai", "top_k": 3})
    assert search["items"]
