from __future__ import annotations

import subprocess
import sys


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


def test_cli_help_and_dashboard_smoke():
    cmds = [
        [sys.executable, "-m", "littlehive.apps.onboarding_cli", "--help"],
        [sys.executable, "-m", "littlehive.apps.api_server", "--help"],
        [sys.executable, "-m", "littlehive.apps.telegram_worker", "--help"],
        [sys.executable, "-m", "littlehive.apps.diagnostics_cli", "--help"],
        [sys.executable, "-m", "littlehive.apps.dashboard", "--help"],
        [sys.executable, "-m", "littlehive.apps.supervisor", "--help"],
    ]
    for cmd in cmds:
        proc = _run(cmd)
        assert proc.returncode == 0, proc.stderr

    smoke = _run([sys.executable, "-m", "littlehive.apps.dashboard", "--smoke"])
    assert smoke.returncode == 0, smoke.stderr
    assert "dashboard-smoke-ok" in smoke.stdout
