from __future__ import annotations

import os
from dataclasses import dataclass

from nicegui import ui

from littlehive.apps.runtime_support import build_operator_runtime
from littlehive.cli import base_parser
from littlehive.core.permissions.policy_engine import PermissionProfile


@dataclass(slots=True)
class DashboardState:
    admin_token: str
    read_only: bool


def _build_table(columns: list[dict], rows: list[dict]) -> None:
    ui.table(columns=columns, rows=rows, row_key=columns[0]["name"]).classes("w-full")


def _render_overview(runtime) -> None:
    overview = runtime.admin_service.overview()
    with ui.row().classes("w-full"):
        for key in [
            "version",
            "instance",
            "environment",
            "safe_mode",
            "active_tasks",
            "total_tasks",
            "uptime_seconds",
        ]:
            with ui.card().classes("min-w-[150px]"):
                ui.label(key.replace("_", " ").title()).classes("text-xs text-gray-500")
                ui.label(str(overview[key])).classes("text-lg")


def _render_providers(runtime) -> None:
    rows = runtime.admin_service.providers()
    _build_table(
        [
            {"name": "name", "label": "Provider", "field": "name"},
            {"name": "health", "label": "Health", "field": "health"},
            {"name": "breaker_state", "label": "Breaker", "field": "breaker_state"},
            {"name": "score", "label": "Score", "field": "score"},
            {"name": "failures", "label": "Failures", "field": "failures"},
            {"name": "latency_ms", "label": "Latency ms", "field": "latency_ms"},
        ],
        rows,
    )


def _render_tasks(runtime) -> None:
    rows = runtime.admin_service.list_tasks(limit=30)
    _build_table(
        [
            {"name": "task_id", "label": "Task", "field": "task_id"},
            {"name": "session_id", "label": "Session", "field": "session_id"},
            {"name": "status", "label": "Status", "field": "status"},
            {"name": "summary", "label": "Summary", "field": "summary"},
        ],
        rows,
    )
    with ui.row():
        task_input = ui.input("Task ID for trace", placeholder="e.g. 42")
        trace_out = ui.markdown("")

        def show_trace() -> None:
            try:
                tid = int(task_input.value)
            except Exception:  # noqa: BLE001
                trace_out.set_content("Invalid task ID")
                return
            trace = runtime.admin_service.get_trace(tid)
            trace_out.set_content(str(trace) if trace else "Trace not found")

        ui.button("Load trace", on_click=show_trace)


def _render_memory(runtime) -> None:
    with ui.row():
        q = ui.input("Query", placeholder="keyword")
        results = ui.column().classes("w-full")

        def run_search() -> None:
            results.clear()
            items = runtime.admin_service.memory_search(query=q.value or "", limit=25)
            if not items:
                with results:
                    ui.label("No memory rows")
                return
            with results:
                _build_table(
                    [
                        {"name": "id", "label": "ID", "field": "id"},
                        {"name": "session_id", "label": "Session", "field": "session_id"},
                        {"name": "card_type", "label": "Type", "field": "card_type"},
                        {"name": "snippet", "label": "Snippet", "field": "snippet"},
                    ],
                    items,
                )

        ui.button("Search", on_click=run_search)


def _render_permissions(runtime, state: DashboardState) -> None:
    row = runtime.admin_service.get_or_create_permission_state()
    ui.label(f"Current profile: {row.current_profile}")
    ui.label(f"Safe mode: {runtime.cfg.runtime.safe_mode}")
    ui.label(f"Read-only mode: {state.read_only}")

    profile_select = ui.select(
        [p.value for p in PermissionProfile],
        value=row.current_profile,
        label="Permission profile",
    )
    token_input = ui.input("Admin token", password=True, password_toggle_button=True).classes("w-80")

    def apply_profile() -> None:
        if state.read_only:
            ui.notify("read-only mode enabled", type="warning")
            return
        expected = state.admin_token
        if expected and token_input.value != expected:
            ui.notify("invalid admin token", type="negative")
            return
        updated = runtime.admin_service.update_profile(PermissionProfile(profile_select.value), actor="dashboard")
        runtime.policy_engine.set_profile(PermissionProfile(updated.current_profile))
        ui.notify(f"profile updated to {updated.current_profile}", type="positive")

    ui.button("Apply profile", on_click=apply_profile)


def _render_usage(runtime) -> None:
    b = runtime.admin_service.usage_summary()
    r = runtime.admin_service.runtime_summary()
    with ui.row().classes("w-full"):
        with ui.card():
            ui.label("Budget stats")
            ui.label(str(b))
        with ui.card():
            ui.label("Runtime stats")
            ui.label(str(r))


def _render_failures(runtime) -> None:
    rows = runtime.admin_service.failure_summary(limit=30)
    _build_table(
        [
            {"name": "category", "label": "Category", "field": "category"},
            {"name": "component", "label": "Component", "field": "component"},
            {"name": "error_type", "label": "Error", "field": "error_type"},
            {"name": "count", "label": "Count", "field": "count"},
            {"name": "recovered", "label": "Recovered", "field": "recovered"},
            {"name": "last_strategy", "label": "Recovery", "field": "last_strategy"},
        ],
        rows,
    )


def _render_confirmations(runtime, state: DashboardState) -> None:
    rows = runtime.admin_service.list_pending_confirmations()
    _build_table(
        [
            {"name": "id", "label": "ID", "field": "id"},
            {"name": "action_type", "label": "Action", "field": "action_type"},
            {"name": "status", "label": "Status", "field": "status"},
            {"name": "expires_at", "label": "Expires", "field": "expires_at"},
        ],
        [
            {
                "id": r.id,
                "action_type": r.action_type,
                "status": r.status,
                "expires_at": r.expires_at,
            }
            for r in rows
        ],
    )

    with ui.row():
        cid = ui.input("Confirmation ID")
        decision = ui.select(["confirm", "deny"], value="confirm")
        token_input = ui.input("Admin token", password=True, password_toggle_button=True)

        def act() -> None:
            if state.read_only:
                ui.notify("read-only mode enabled", type="warning")
                return
            if state.admin_token and token_input.value != state.admin_token:
                ui.notify("invalid admin token", type="negative")
                return
            try:
                row = runtime.admin_service.decide_confirmation(int(cid.value), decision.value, actor="dashboard")
                ui.notify(f"confirmation {row.id} -> {row.status}", type="positive")
            except Exception as exc:  # noqa: BLE001
                ui.notify(f"error: {exc}", type="negative")

        ui.button("Apply decision", on_click=act)


def build_dashboard(config_path: str | None, read_only: bool, admin_token_override: str | None) -> tuple[object, DashboardState]:
    runtime = build_operator_runtime(config_path=config_path)
    token = admin_token_override
    if token is None:
        token = os.getenv(runtime.cfg.admin_token_env, "")
    state = DashboardState(admin_token=token or "", read_only=read_only or bool(runtime.cfg.admin_read_only))

    @ui.page("/")
    def dashboard() -> None:
        ui.label("LittleHive Operator Dashboard").classes("text-2xl font-bold")
        with ui.tabs().classes("w-full") as tabs:
            t1 = ui.tab("Overview")
            t2 = ui.tab("Providers")
            t3 = ui.tab("Tasks")
            t4 = ui.tab("Traces")
            t5 = ui.tab("Memory")
            t6 = ui.tab("Permissions")
            t7 = ui.tab("Usage")
            t8 = ui.tab("Diagnostics")
            t9 = ui.tab("Confirmations")

        with ui.tab_panels(tabs, value=t1).classes("w-full"):
            with ui.tab_panel(t1):
                _render_overview(runtime)
            with ui.tab_panel(t2):
                _render_providers(runtime)
            with ui.tab_panel(t3):
                _render_tasks(runtime)
            with ui.tab_panel(t4):
                ui.markdown("Use **Tasks** tab to inspect traces by task id.")
            with ui.tab_panel(t5):
                _render_memory(runtime)
            with ui.tab_panel(t6):
                _render_permissions(runtime, state)
            with ui.tab_panel(t7):
                _render_usage(runtime)
            with ui.tab_panel(t8):
                _render_failures(runtime)
            with ui.tab_panel(t9):
                _render_confirmations(runtime, state)

    return runtime, state


def main() -> int:
    parser = base_parser("littlehive-dashboard", "LittleHive operator dashboard")
    parser.add_argument("--config", default=None, help="Config file path")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--admin-token", default=None)
    parser.add_argument("--read-only", action="store_true")
    parser.add_argument("--smoke", action="store_true", help="Run startup checks only and exit")
    args = parser.parse_args()

    runtime, state = build_dashboard(args.config, read_only=args.read_only, admin_token_override=args.admin_token)
    if args.smoke:
        print(
            "dashboard-smoke-ok "
            f"profile={runtime.policy_engine.profile.value} "
            f"safe_mode={runtime.cfg.runtime.safe_mode} read_only={state.read_only}"
        )
        return 0

    host = args.host or runtime.cfg.dashboard_host
    port = args.port or runtime.cfg.dashboard_port
    ui.run(host=host, port=port, reload=False, title="LittleHive Dashboard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
