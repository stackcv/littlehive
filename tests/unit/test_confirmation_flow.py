from __future__ import annotations

from datetime import timedelta

from littlehive.core.admin.service import AdminService
from littlehive.core.config.schema import AppConfig
from littlehive.db.models import PendingConfirmation
from littlehive.db.session import Base, create_session_factory


def test_confirmation_state_transitions(tmp_path):
    sf, engine = create_session_factory(f"sqlite:///{tmp_path / 'confirmations.db'}")
    import littlehive.db.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    svc = AdminService(cfg=AppConfig(), db_session_factory=sf, provider_router=None)

    row = svc.create_confirmation(
        action_type="tool_invocation",
        action_summary="approve action",
        payload={"x": 1},
        task_id=1,
        session_id=1,
        ttl_seconds=30,
    )
    assert row.status == "waiting_confirmation"

    decided = svc.decide_confirmation(row.id, decision="confirm", actor="tester")
    assert decided.status == "confirmed"


def test_confirmation_expires(tmp_path):
    sf, engine = create_session_factory(f"sqlite:///{tmp_path / 'confirmations_exp.db'}")
    import littlehive.db.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    svc = AdminService(cfg=AppConfig(), db_session_factory=sf, provider_router=None)

    row = svc.create_confirmation(
        action_type="tool_invocation",
        action_summary="approve action",
        payload={"x": 1},
        task_id=1,
        session_id=1,
        ttl_seconds=1,
    )
    with sf() as db:
        found = db.get(PendingConfirmation, row.id)
        found.expires_at = found.created_at - timedelta(seconds=1)
        db.commit()

    pending = svc.list_pending_confirmations()
    assert pending[0].status == "expired"
