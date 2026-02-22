from __future__ import annotations

from datetime import datetime, timezone

from littlehive.core.admin.service import AdminService, redact_text
from littlehive.core.config.schema import AppConfig
from littlehive.core.permissions.policy_engine import PermissionProfile, PolicyEngine
from littlehive.core.telemetry.diagnostics import budget_stats
from littlehive.db.models import TaskTraceSummary
from littlehive.db.session import Base, create_session_factory


def test_permission_profile_transitions_behavior():
    engine = PolicyEngine(PermissionProfile.READ_ONLY)
    assert engine.evaluate_tool_risk("low", safe_mode=True).allowed is False

    engine.set_profile(PermissionProfile.ASSIST_ONLY)
    assert engine.evaluate_tool_risk("low", safe_mode=True).allowed is True
    assert engine.evaluate_tool_risk("medium", safe_mode=True).allowed is False

    engine.set_profile(PermissionProfile.EXECUTE_SAFE)
    medium = engine.evaluate_tool_risk("medium", safe_mode=True)
    assert medium.allowed is True
    assert medium.requires_confirmation is True

    engine.set_profile(PermissionProfile.FULL_TRUSTED)
    critical = engine.evaluate_tool_risk("critical", safe_mode=False)
    assert critical.allowed is True


def test_redaction_hides_secret_like_values():
    assert redact_text("api key=abc") == "***REDACTED***"
    assert redact_text("normal text") == "normal text"


def test_usage_summary_handles_partial_telemetry(tmp_path):
    sf, engine = create_session_factory(f"sqlite:///{tmp_path / 'phase45_usage.db'}")
    import littlehive.db.models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    with sf() as db:
        db.add(
            TaskTraceSummary(
                task_id=1,
                session_id=1,
                request_id="r1",
                agent_sequence="planner>reply",
                transfer_count=0,
                provider_attempts=1,
                tool_attempts=0,
                retry_count=0,
                breaker_events=0,
                trim_event_count=2,
                avg_estimated_tokens=180.0,
                outcome_status="completed",
                created_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    out = budget_stats(sf)
    assert out["avg_estimated_prompt_tokens"] == 180.0
    assert out["trim_event_count"] == 2
    assert out["trace_count"] == 1


def test_config_has_phase45_defaults():
    cfg = AppConfig()
    assert cfg.dashboard_host == "127.0.0.1"
    assert cfg.dashboard_port == 8666
    assert cfg.admin_token_env == "LITTLEHIVE_ADMIN_TOKEN"


def test_admin_service_profile_persistence(tmp_path):
    sf, engine = create_session_factory(f"sqlite:///{tmp_path / 'phase45_profile.db'}")
    import littlehive.db.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    cfg = AppConfig()
    svc = AdminService(cfg=cfg, db_session_factory=sf, provider_router=None)

    initial = svc.get_or_create_permission_state()
    assert initial.current_profile == cfg.runtime.permission_profile

    changed = svc.update_profile(PermissionProfile.FULL_TRUSTED, actor="unit")
    assert changed.current_profile == PermissionProfile.FULL_TRUSTED.value
