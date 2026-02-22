from __future__ import annotations

from littlehive.apps import diagnostics_cli, onboarding_cli


def test_onboarding_non_interactive_generates_files(tmp_path, monkeypatch):
    config_path = tmp_path / "instance.yaml"
    env_path = tmp_path / ".env"
    argv = [
        "littlehive-onboard",
        "--non-interactive",
        "--force",
        "--allow-no-provider-success",
        "--config-output",
        str(config_path),
        "--env-output",
        str(env_path),
        "--enable-local-provider",
    ]
    monkeypatch.setattr("sys.argv", argv)
    rc = onboarding_cli.main()
    assert rc == 0
    assert config_path.exists()
    assert env_path.exists()


def test_diagnostics_cli_reads_generated_config(tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "instance.yaml"
    env_path = tmp_path / ".env"

    monkeypatch.setattr(
        "sys.argv",
        [
            "littlehive-onboard",
            "--non-interactive",
            "--force",
            "--allow-no-provider-success",
            "--config-output",
            str(config_path),
            "--env-output",
            str(env_path),
            "--enable-local-provider",
        ],
    )
    assert onboarding_cli.main() == 0

    monkeypatch.setenv("LITTLEHIVE_CONFIG_FILE", str(config_path))
    monkeypatch.setattr(
        "sys.argv",
        [
            "littlehive-diag",
            "--validate-config",
            "--hardware",
            "--check-providers",
            "--recommend-models",
            "--skip-provider-tests",
        ],
    )
    rc = diagnostics_cli.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "config-valid" in out
    assert "hardware-summary" in out
    assert "provider-checks" in out
    assert "recommendation" in out


def test_provider_check_timeout_handled_gracefully(monkeypatch):
    from littlehive.core.config.loader import load_app_config
    from littlehive.core.providers.health import check_configured_providers
    import httpx

    cfg = load_app_config()
    cfg.providers.local_compatible.enabled = True
    cfg.providers.local_compatible.base_url = "http://127.0.0.1:9"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, *args, **kwargs):
            raise httpx.TimeoutException("timeout")

    monkeypatch.setattr("littlehive.core.providers.health.httpx.Client", FakeClient)
    result = check_configured_providers(cfg, skip_tests=False)
    assert result["local_compatible"].ok is False
    assert "timeout" in (result["local_compatible"].error or "")
