from __future__ import annotations

import os
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query

from littlehive import __version__
from littlehive.apps.runtime_support import build_operator_runtime
from littlehive.cli import base_parser
from littlehive.core.admin.schemas import (
    AgentUpdateRequest,
    ConfirmationCreateRequest,
    ConfirmationDecisionRequest,
    PermissionProfileResponse,
    PermissionProfileUpdateRequest,
    PrincipalGrantUpdateRequest,
    RuntimeApplyRequest,
    UserProfileModel,
    UserProfileUpdateRequest,
)
from littlehive.core.permissions.policy_engine import PermissionProfile


def create_app(config_path: str | None = None) -> FastAPI:
    runtime = build_operator_runtime(config_path=config_path)
    app = FastAPI(title="LittleHive Admin API", version=__version__)

    def _require_admin_token(x_admin_token: Annotated[str | None, Header()] = None) -> None:
        token_env = runtime.cfg.admin_token_env
        expected = os.getenv(token_env, "").strip()
        if expected and x_admin_token != expected:
            raise HTTPException(status_code=401, detail="invalid_admin_token")

    def _assert_mutations_allowed() -> None:
        if runtime.cfg.admin_read_only:
            raise HTTPException(status_code=403, detail="admin_read_only_mode")

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "safe_mode": runtime.admin_service.get_safe_mode(),
            "profile": runtime.policy_engine.profile.value,
            "version": __version__,
        }

    @app.get("/healthz")
    def healthz() -> dict:
        return health()

    @app.get("/status")
    def status() -> dict:
        return {
            "overview": runtime.admin_service.overview(),
            "runtime": runtime.admin_service.runtime_summary(),
        }

    @app.get("/providers")
    def providers() -> dict:
        return {"items": runtime.admin_service.providers()}

    @app.get("/agents")
    def agents() -> dict:
        return {
            "items": [
                {"agent_id": "orchestrator_agent", "enabled": True},
                {"agent_id": "planner_agent", "enabled": True},
                {"agent_id": "execution_agent", "enabled": True},
                {"agent_id": "memory_agent", "enabled": True},
                {"agent_id": "reply_agent", "enabled": True},
            ],
            "safe_mode": runtime.admin_service.get_safe_mode(),
        }

    @app.patch("/agents/{agent_id}")
    def patch_agent(agent_id: str, payload: AgentUpdateRequest, _=Depends(_require_admin_token)) -> dict:
        _assert_mutations_allowed()
        if agent_id != "runtime":
            raise HTTPException(status_code=400, detail="only_runtime_agent_patch_supported")
        if payload.safe_mode is not None:
            runtime.admin_service.update_safe_mode(bool(payload.safe_mode), actor="api")
        return {"agent_id": agent_id, "safe_mode": runtime.admin_service.get_safe_mode()}

    @app.get("/tasks")
    def tasks(
        status: str | None = Query(default=None),
        session_id: int | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict:
        return {"items": runtime.admin_service.list_tasks(limit=limit, status=status, session_id=session_id)}

    @app.get("/tasks/{task_id}/trace")
    def task_trace(task_id: int) -> dict:
        trace = runtime.admin_service.get_trace(task_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="task_trace_not_found")
        return trace

    @app.get("/memory/search")
    def memory_search(
        q: str = Query(default=""),
        session_id: int | None = Query(default=None),
        user_id: int | None = Query(default=None),
        limit: int = Query(default=20, ge=1, le=200),
    ) -> dict:
        return {"items": runtime.admin_service.memory_search(query=q, session_id=session_id, user_id=user_id, limit=limit)}

    @app.get("/users")
    def users(limit: int = Query(default=100, ge=1, le=500)) -> dict:
        return {"items": runtime.admin_service.list_users(limit=limit)}

    @app.get("/principals")
    def principals(channel: str | None = Query(default=None), limit: int = Query(default=200, ge=1, le=1000)) -> dict:
        return {"items": runtime.admin_service.list_principals(channel=channel, limit=limit)}

    @app.post("/principals/grants")
    def update_principal_grant(payload: PrincipalGrantUpdateRequest, _=Depends(_require_admin_token)) -> dict:
        _assert_mutations_allowed()
        row = runtime.admin_service.set_principal_grant(
            channel=payload.channel,
            external_id=payload.external_id,
            grant_type=payload.grant_type,
            allowed=payload.allowed,
            actor=payload.actor,
            display_name=payload.display_name,
        )
        return {
            "id": row.id,
            "grant_type": row.grant_type,
            "allowed": bool(row.is_allowed),
            "updated_by": row.updated_by,
            "updated_at": row.updated_at,
        }

    @app.get("/users/{user_id}/profile", response_model=UserProfileModel)
    def get_user_profile(user_id: int) -> UserProfileModel:
        row = runtime.admin_service.get_user_profile(user_id)
        if row is None:
            raise HTTPException(status_code=404, detail="user_not_found")
        return UserProfileModel(**row)

    @app.patch("/users/{user_id}/profile", response_model=UserProfileModel)
    def patch_user_profile(
        user_id: int,
        payload: UserProfileUpdateRequest,
        _=Depends(_require_admin_token),
    ) -> UserProfileModel:
        _assert_mutations_allowed()
        updated = runtime.admin_service.update_user_profile(
            user_id=user_id,
            display_name=payload.display_name,
            preferred_timezone=payload.preferred_timezone,
            city=payload.city,
            country=payload.country,
            profile_notes=payload.profile_notes,
        )
        return UserProfileModel(**updated)

    @app.get("/permissions/profile", response_model=PermissionProfileResponse)
    def get_permission_profile() -> PermissionProfileResponse:
        row = runtime.admin_service.get_or_create_permission_state()
        runtime.policy_engine.set_profile(PermissionProfile(row.current_profile))
        return PermissionProfileResponse(
            current_profile=PermissionProfile(row.current_profile),
            safe_mode=runtime.admin_service.get_safe_mode(),
            updated_by=row.updated_by,
            updated_at=row.updated_at,
        )

    @app.patch("/permissions/profile", response_model=PermissionProfileResponse)
    def patch_permission_profile(payload: PermissionProfileUpdateRequest, _=Depends(_require_admin_token)) -> PermissionProfileResponse:
        _assert_mutations_allowed()
        row = runtime.admin_service.update_profile(payload.profile, actor="api")
        runtime.policy_engine.set_profile(payload.profile)
        return PermissionProfileResponse(
            current_profile=PermissionProfile(row.current_profile),
            safe_mode=runtime.admin_service.get_safe_mode(),
            updated_by=row.updated_by,
            updated_at=row.updated_at,
        )

    @app.post("/runtime/apply")
    def runtime_apply(payload: RuntimeApplyRequest, _=Depends(_require_admin_token)) -> dict:
        _assert_mutations_allowed()
        actor = payload.actor or "api"
        if payload.safe_mode is not None:
            runtime.admin_service.update_safe_mode(payload.safe_mode, actor=actor)
        if payload.profile is not None:
            row = runtime.admin_service.update_profile(payload.profile, actor=actor)
            runtime.policy_engine.set_profile(PermissionProfile(row.current_profile))

        event_id = None
        if payload.request_restart:
            event = runtime.admin_service.request_control_event(
                event_type="restart_services",
                payload={"source": "api.runtime_apply"},
                actor=actor,
            )
            event_id = event.id

        return {
            "safe_mode": runtime.admin_service.get_safe_mode(),
            "profile": runtime.policy_engine.profile.value,
            "restart_requested": bool(payload.request_restart),
            "control_event_id": event_id,
        }

    @app.get("/usage")
    def usage() -> dict:
        return runtime.admin_service.usage_summary()

    @app.get("/diagnostics/failures")
    def diagnostics_failures(limit: int = Query(default=20, ge=1, le=200)) -> dict:
        return {"items": runtime.admin_service.failure_summary(limit=limit)}

    @app.get("/diagnostics/budgets")
    def diagnostics_budgets() -> dict:
        return runtime.admin_service.usage_summary()

    @app.get("/diagnostics/tool-quality")
    def diagnostics_tool_quality() -> dict:
        return runtime.admin_service.tool_retrieval_quality_summary()

    @app.get("/confirmations")
    def confirmations() -> dict:
        rows = runtime.admin_service.list_pending_confirmations()
        return {
            "items": [
                {
                    "id": r.id,
                    "task_id": r.task_id,
                    "session_id": r.session_id,
                    "action_type": r.action_type,
                    "action_summary": r.action_summary,
                    "status": r.status,
                    "created_at": r.created_at,
                    "expires_at": r.expires_at,
                    "decided_at": r.decided_at,
                    "decided_by": r.decided_by,
                }
                for r in rows
            ]
        }

    @app.post("/confirmations")
    def create_confirmation(payload: ConfirmationCreateRequest, _=Depends(_require_admin_token)) -> dict:
        _assert_mutations_allowed()
        row = runtime.admin_service.create_confirmation(
            action_type=payload.action_type,
            action_summary=payload.action_summary,
            payload=payload.payload,
            task_id=payload.task_id,
            session_id=payload.session_id,
            ttl_seconds=payload.ttl_seconds,
        )
        return {"id": row.id, "status": row.status, "expires_at": row.expires_at}

    @app.patch("/confirmations/{confirmation_id}")
    def decide_confirmation(
        confirmation_id: int,
        payload: ConfirmationDecisionRequest,
        _=Depends(_require_admin_token),
    ) -> dict:
        _assert_mutations_allowed()
        row = runtime.admin_service.decide_confirmation(
            confirmation_id=confirmation_id,
            decision=payload.decision,
            actor=payload.actor,
        )
        return {
            "id": row.id,
            "status": row.status,
            "decided_at": row.decided_at,
            "decided_by": row.decided_by,
        }

    return app


app = create_app()


def main() -> int:
    parser = base_parser("littlehive-api", "LittleHive operator API")
    parser.add_argument("--config", default=None, help="Config file path")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    api = create_app(config_path=args.config)
    uvicorn.run(api, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
