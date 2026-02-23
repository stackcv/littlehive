from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
import yaml
from fastapi.testclient import TestClient

from littlehive.apps.api_server import create_app
from littlehive.core.config.loader import load_app_config
from littlehive.db.models import MemoryRecord, PermissionAuditEvent, RuntimeControlEvent, Session, Task, TaskTraceSummary, User
from littlehive.db.session import create_session_factory


def _write_config(path, db_url: str) -> None:
    base = yaml.safe_load(open("config/defaults.yaml", encoding="utf-8"))
    base["database"]["url"] = db_url
    base["channels"]["telegram"]["enabled"] = True
    base["channels"]["telegram"]["owner_user_id"] = 1
    base["channels"]["telegram"]["allow_user_ids"] = [1]
    base["providers"]["local_compatible"]["enabled"] = False
    base["providers"]["groq"]["enabled"] = False
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(base, f, sort_keys=False)


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    cfg_path = tmp_path / "instance.yaml"
    db_url = f"sqlite:///{tmp_path / 'admin_api.db'}"
    _write_config(cfg_path, db_url)
    os.environ["LITTLEHIVE_ADMIN_TOKEN"] = "test-token"

    app = create_app(config_path=str(cfg_path))

    cfg = load_app_config(instance_path=str(cfg_path))
    sf, _ = create_session_factory(cfg.database.url)
    with sf() as db:
        user = User(external_id="tg:1", telegram_user_id=1, created_at=datetime.now(timezone.utc))
        db.add(user)
        db.flush()
        session = Session(
            user_id=user.id,
            channel="telegram",
            external_id="telegram:1",
            latest_summary="",
            created_at=datetime.now(timezone.utc),
        )
        db.add(session)
        db.flush()
        task = Task(
            session_id=session.id,
            status="completed",
            summary="seed task",
            last_error="",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(task)
        db.flush()
        db.add(
            TaskTraceSummary(
                task_id=task.id,
                session_id=session.id,
                request_id="r1",
                agent_sequence="planner>execution>reply",
                transfer_count=1,
                provider_attempts=2,
                tool_attempts=1,
                retry_count=1,
                breaker_events=0,
                trim_event_count=2,
                avg_estimated_tokens=180.0,
                outcome_status="completed",
                created_at=datetime.now(timezone.utc),
            )
        )
        db.add(
            MemoryRecord(
                session_id=session.id,
                user_id=user.id,
                memory_type="note",
                card_type="fact",
                content="my api key is super-secret",
                pinned=0,
                error_signature="",
                fix_text="",
                source="runtime",
                confidence=0.5,
                success_count=0,
                created_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    with TestClient(app) as client:
        yield client, sf


def test_admin_read_only_endpoints(api_client):
    client, _sf = api_client
    assert client.get("/health").status_code == 200
    assert client.get("/status").status_code == 200
    assert client.get("/providers").status_code == 200
    assert client.get("/agents").status_code == 200
    assert client.get("/tasks").status_code == 200
    assert client.get("/diagnostics/failures").status_code == 200
    assert client.get("/diagnostics/tool-quality").status_code == 200


def test_patch_permission_profile_updates_and_audits(api_client):
    client, sf = api_client
    resp = client.patch(
        "/permissions/profile",
        headers={"x-admin-token": "test-token"},
        json={"profile": "execute_with_confirmation"},
    )
    assert resp.status_code == 200
    assert resp.json()["current_profile"] == "execute_with_confirmation"

    with sf() as db:
        count = db.query(PermissionAuditEvent).count()
    assert count >= 1


def test_patch_runtime_safe_mode(api_client):
    client, _sf = api_client
    resp = client.patch(
        "/agents/runtime",
        headers={"x-admin-token": "test-token"},
        json={"safe_mode": False},
    )
    assert resp.status_code == 200
    assert resp.json()["safe_mode"] is False


def test_trace_endpoint_returns_compact_summary(api_client):
    client, _sf = api_client
    tasks = client.get("/tasks").json()["items"]
    task_id = tasks[0]["task_id"]
    trace = client.get(f"/tasks/{task_id}/trace")
    assert trace.status_code == 200
    body = trace.json()
    assert body["retry_count"] >= 0
    assert "agent_sequence" in body


def test_trace_endpoint_returns_latest_row_when_multiple_exist(api_client):
    client, sf = api_client
    tasks = client.get("/tasks").json()["items"]
    task_id = tasks[0]["task_id"]

    with sf() as db:
        task = db.query(Task).filter(Task.id == task_id).one()
        db.add(
            TaskTraceSummary(
                task_id=task_id,
                session_id=task.session_id,
                request_id="r2",
                agent_sequence="planner>reply",
                transfer_count=0,
                provider_attempts=1,
                tool_attempts=0,
                retry_count=0,
                breaker_events=0,
                trim_event_count=0,
                avg_estimated_tokens=90.0,
                outcome_status="completed",
                created_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    trace = client.get(f"/tasks/{task_id}/trace")
    assert trace.status_code == 200
    body = trace.json()
    assert body["request_id"] == "r2"


def test_memory_search_redacts_secret_like_data(api_client):
    client, _sf = api_client
    result = client.get("/memory/search", params={"q": "key"})
    assert result.status_code == 200
    items = result.json()["items"]
    assert items
    assert items[0]["snippet"] == "***REDACTED***"


def test_confirmation_flow_confirm_and_deny(api_client):
    client, _sf = api_client
    created = client.post(
        "/confirmations",
        headers={"x-admin-token": "test-token"},
        json={
            "action_type": "tool_invocation",
            "action_summary": "approve medium tool",
            "task_id": 1,
            "session_id": 1,
            "payload": {"tool": "demo.medium"},
            "ttl_seconds": 120,
        },
    )
    assert created.status_code == 200
    cid = created.json()["id"]

    denied = client.patch(
        f"/confirmations/{cid}",
        headers={"x-admin-token": "test-token"},
        json={"decision": "deny", "actor": "integration"},
    )
    assert denied.status_code == 200
    assert denied.json()["status"] == "denied"


def test_user_profile_list_and_update(api_client):
    client, _sf = api_client
    listed = client.get("/users")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert items
    user_id = items[0]["id"]

    updated = client.patch(
        f"/users/{user_id}/profile",
        headers={"x-admin-token": "test-token"},
        json={
            "display_name": "Anupam",
            "preferred_timezone": "Asia/Kolkata",
            "city": "Pune",
            "country": "India",
            "profile_notes": "Prefers concise answers",
        },
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["display_name"] == "Anupam"
    assert body["preferred_timezone"] == "Asia/Kolkata"

    fetched = client.get(f"/users/{user_id}/profile")
    assert fetched.status_code == 200
    assert fetched.json()["city"] == "Pune"


def test_principal_grant_and_runtime_apply(api_client):
    client, sf = api_client
    grant = client.post(
        "/principals/grants",
        headers={"x-admin-token": "test-token"},
        json={
            "channel": "telegram",
            "external_id": "7760209623",
            "grant_type": "chat_access",
            "allowed": True,
            "actor": "integration",
        },
    )
    assert grant.status_code == 200
    assert grant.json()["allowed"] is True

    principals = client.get("/principals", params={"channel": "telegram"})
    assert principals.status_code == 200
    assert any(x["external_id"] == "7760209623" for x in principals.json()["items"])

    applied = client.post(
        "/runtime/apply",
        headers={"x-admin-token": "test-token"},
        json={"safe_mode": False, "request_restart": True, "actor": "integration"},
    )
    assert applied.status_code == 200
    assert applied.json()["safe_mode"] is False
    assert applied.json()["restart_requested"] is True
    assert applied.json()["control_event_id"] is not None

    with sf() as db:
        row = (
            db.query(RuntimeControlEvent)
            .order_by(RuntimeControlEvent.id.desc())
            .first()
        )
        assert row is not None
        assert row.status == "pending"
