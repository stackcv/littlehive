from __future__ import annotations

from types import SimpleNamespace

from littlehive.apps import diagnostics_cli


class FakeRouter:
    def provider_status(self):
        return {
            "p1": {
                "health": True,
                "score": 100.0,
                "breaker": {"state": "closed"},
                "stats": {"failure": 0, "latency_ms": 10.0},
            }
        }

    def provider_scores(self):
        return {"p1": 100.0}


class FakeRuntime:
    def __init__(self):
        self.pipeline = SimpleNamespace(provider_router=FakeRouter())
        self.db_session_factory = lambda: None


def test_diag_provider_health_output(monkeypatch, capsys):
    monkeypatch.setattr("littlehive.apps.diagnostics_cli.build_telegram_runtime", lambda config_path=None: FakeRuntime())
    monkeypatch.setattr("littlehive.apps.diagnostics_cli.load_app_config", lambda instance_path=None: SimpleNamespace(runtime=SimpleNamespace(safe_mode=True), instance=SimpleNamespace(name="x"), environment="dev"))
    monkeypatch.setattr("sys.argv", ["littlehive-diag", "--provider-health"])
    rc = diagnostics_cli.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "provider-health" in out
    assert "breaker=closed" in out


def test_diag_failure_summary_output(monkeypatch, capsys):
    monkeypatch.setattr("littlehive.apps.diagnostics_cli.build_telegram_runtime", lambda config_path=None: FakeRuntime())
    monkeypatch.setattr("littlehive.apps.diagnostics_cli.load_app_config", lambda instance_path=None: SimpleNamespace(runtime=SimpleNamespace(safe_mode=True), instance=SimpleNamespace(name="x"), environment="dev"))
    monkeypatch.setattr(
        "littlehive.apps.diagnostics_cli.failure_summary",
        lambda db_session_factory, limit=10: [
            {
                "category": "provider",
                "component": "router",
                "error_type": "TimeoutError",
                "signature": "timeout",
                "count": 2,
                "recovered": 1,
                "last_strategy": "switch_provider",
                "last_seen": "2026-01-01T00:00:00Z",
            }
        ],
    )
    monkeypatch.setattr("sys.argv", ["littlehive-diag", "--failures"])
    rc = diagnostics_cli.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "failure-summary" in out
    assert "switch_provider" in out


def test_diag_budget_stats_handles_missing_data(monkeypatch, capsys):
    monkeypatch.setattr("littlehive.apps.diagnostics_cli.build_telegram_runtime", lambda config_path=None: FakeRuntime())
    monkeypatch.setattr("littlehive.apps.diagnostics_cli.load_app_config", lambda instance_path=None: SimpleNamespace(runtime=SimpleNamespace(safe_mode=True), instance=SimpleNamespace(name="x"), environment="dev"))
    monkeypatch.setattr(
        "littlehive.apps.diagnostics_cli.budget_stats",
        lambda db_session_factory: {
            "avg_estimated_prompt_tokens": 0.0,
            "trim_event_count": 0,
            "over_budget_incidents": 0,
            "trace_count": 0,
        },
    )
    monkeypatch.setattr("sys.argv", ["littlehive-diag", "--budget-stats"])
    rc = diagnostics_cli.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "budget-stats" in out
    assert "trace_count=0" in out


def test_diag_tool_quality_output(monkeypatch, capsys):
    monkeypatch.setattr("littlehive.apps.diagnostics_cli.build_telegram_runtime", lambda config_path=None: FakeRuntime())
    monkeypatch.setattr("littlehive.apps.diagnostics_cli.load_app_config", lambda instance_path=None: SimpleNamespace(runtime=SimpleNamespace(safe_mode=True), instance=SimpleNamespace(name="x"), environment="dev"))
    monkeypatch.setattr(
        "littlehive.apps.diagnostics_cli.tool_retrieval_quality_stats",
        lambda db_session_factory: {
            "total_tool_calls": 10,
            "ok_calls": 8,
            "blocked_calls": 1,
            "error_calls": 1,
            "waiting_confirmation_calls": 0,
            "success_rate": 0.8,
            "blocked_rate": 0.1,
            "error_rate": 0.1,
        },
    )
    monkeypatch.setattr("sys.argv", ["littlehive-diag", "--tool-quality"])
    rc = diagnostics_cli.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "tool-quality" in out
    assert "success_rate=0.8" in out
