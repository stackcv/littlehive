from __future__ import annotations

from dataclasses import dataclass

from littlehive.channels.telegram.adapter import TelegramRuntime, build_telegram_runtime
from littlehive.core.admin.service import AdminService
from littlehive.core.config.loader import load_app_config
from littlehive.core.permissions.policy_engine import PermissionProfile, PolicyEngine


@dataclass(slots=True)
class OperatorRuntime:
    cfg: object
    telegram_runtime: TelegramRuntime
    admin_service: AdminService
    policy_engine: PolicyEngine


def build_operator_runtime(config_path: str | None = None) -> OperatorRuntime:
    cfg = load_app_config(instance_path=config_path)
    telegram_runtime = build_telegram_runtime(config_path=config_path)
    admin_service = AdminService(
        cfg=cfg,
        db_session_factory=telegram_runtime.db_session_factory,
        provider_router=telegram_runtime.pipeline.provider_router,
    )
    if hasattr(telegram_runtime.tool_executor, "policy_engine"):
        policy_engine = telegram_runtime.tool_executor.policy_engine
    else:
        state = admin_service.get_or_create_permission_state()
        try:
            profile = PermissionProfile(state.current_profile)
        except ValueError:
            profile = PermissionProfile.EXECUTE_SAFE
        policy_engine = PolicyEngine(profile=profile)
    return OperatorRuntime(cfg=cfg, telegram_runtime=telegram_runtime, admin_service=admin_service, policy_engine=policy_engine)
