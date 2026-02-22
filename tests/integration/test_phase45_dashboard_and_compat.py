from __future__ import annotations

from datetime import datetime

import pytest

from littlehive.apps.dashboard import build_dashboard, main as dashboard_main
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
from littlehive.db.models import ToolCall
from littlehive.db.session import Base, create_session_factory


class TestProvider(ProviderAdapter):
    name = "local_compatible"

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        _ = request
        return ProviderResponse(provider=self.name, model="test-model", output_text="test-reply", raw={})

    def health(self) -> bool:
        return True


class _Msg:
    def __init__(self, text: str):
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


class _User:
    def __init__(self, uid: int):
        self.id = uid


class _Chat:
    def __init__(self, cid: int):
        self.id = cid


class _Update:
    def __init__(self, user_id: int, chat_id: int, text: str):
        self.effective_user = _User(user_id)
        self.effective_chat = _Chat(chat_id)
        self.effective_message = _Msg(text)


def _runtime(tmp_path):
    db_file = tmp_path / "phase45_compat.db"
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
                    created_at=datetime.utcnow(),
                )
            )
            db.commit()

    executor = ToolExecutor(registry=registry, logger=get_logger("test.phase45"), call_logger=persist_tool_call)
    pipeline = TaskPipeline(cfg=cfg, db_session_factory=session_factory, tool_executor=executor, provider_router=provider_router)
    return TelegramRuntime(
        auth=TelegramAllowlistAuth(cfg.channels.telegram),
        lock_manager=SessionLockManager(),
        pipeline=pipeline,
        tool_executor=executor,
        db_session_factory=session_factory,
        logger=get_logger("test.phase45.runtime"),
    )


def test_dashboard_build_smoke(tmp_path):
    runtime, state = build_dashboard(config_path=None, read_only=True, admin_token_override="")
    assert runtime.admin_service.overview()["version"]
    assert state.read_only is True


def test_dashboard_cli_smoke_flag(monkeypatch):
    monkeypatch.setattr("sys.argv", ["littlehive-dashboard", "--smoke"])
    assert dashboard_main() == 0


@pytest.mark.asyncio
async def test_telegram_status_and_debug_compat(tmp_path):
    runtime = _runtime(tmp_path)
    handlers = TelegramHandlers(runtime)

    status_update = _Update(user_id=1, chat_id=7, text="/status")
    await handlers.handle_update(status_update, context=None)
    assert status_update.effective_message.replies

    debug_update = _Update(user_id=1, chat_id=7, text="/debug")
    await handlers.handle_update(debug_update, context=None)
    assert debug_update.effective_message.replies
