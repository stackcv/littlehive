from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from littlehive.cli import base_parser
from littlehive.core.config.loader import load_app_config
from littlehive.core.config.onboarding import collect_interactive_answers, run_onboarding


def _resolve_config_path(cli_config: str | None) -> Path:
    explicit = cli_config or os.getenv("LITTLEHIVE_CONFIG_FILE")
    if explicit:
        return Path(explicit)
    return Path("config/instance.yaml")


def _load_env_file(path: Path) -> dict[str, str]:
    loaded: dict[str, str] = {}
    if not path.exists():
        return loaded
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        loaded[key.strip()] = value.strip().strip('"').strip("'")
    return loaded


def _upsert_env_file(path: Path, key: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    found = False
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()

    for i, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        current_key = stripped.split("=", 1)[0].replace("export ", "").strip()
        if current_key == key:
            lines[i] = f"{key}={value}"
            found = True

    if not found:
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(f"{key}={value}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_onboarding_if_needed(
    config_path: Path,
    env_file: Path,
    *,
    force: bool,
    skip_provider_tests: bool,
) -> tuple[Path, Path]:
    if config_path.exists() and not force:
        return config_path, env_file

    print("No runtime config found. Starting interactive onboarding.")
    answers = collect_interactive_answers(input, print)
    answers.config_path = str(config_path)
    answers.env_path = str(env_file)

    result = run_onboarding(
        answers=answers,
        force=force,
        skip_provider_tests=skip_provider_tests,
        output_func=print,
        input_func=input,
        allow_no_provider_success=True,
    )
    print(f"Onboarding complete. config={result.config_path} env={result.env_path}")
    return Path(result.config_path), Path(result.env_path)


def _prepare_runtime_env(env_file: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update(_load_env_file(env_file))
    return env


def _spawn(name: str, cmd: list[str], env: dict[str, str]) -> subprocess.Popen:
    print(f"Starting {name}: {' '.join(cmd)}")
    return subprocess.Popen(cmd, env=env)


def _shutdown(children: list[tuple[str, subprocess.Popen]]) -> None:
    for _, proc in children:
        if proc.poll() is None:
            proc.terminate()

    deadline = time.time() + 8
    while time.time() < deadline:
        if all(proc.poll() is not None for _, proc in children):
            return
        time.sleep(0.25)

    for _, proc in children:
        if proc.poll() is None:
            proc.kill()


def main() -> int:
    parser = base_parser("littlehive-run", "LittleHive user-friendly orchestrator")
    parser.add_argument("--config", default=None, help="Config file path")
    parser.add_argument("--env-file", default=".env", help="Env file path")
    parser.add_argument("--force-onboard", action="store_true", help="Force onboarding even if config exists")
    parser.add_argument("--skip-provider-tests", action="store_true", help="Skip provider tests during onboarding")

    parser.add_argument("--no-api", action="store_true")
    parser.add_argument("--no-dashboard", action="store_true")
    parser.add_argument("--no-telegram", action="store_true")
    parser.add_argument("--no-supervisor", action="store_true")

    parser.add_argument("--api-host", default="127.0.0.1")
    parser.add_argument("--api-port", type=int, default=8080)
    parser.add_argument("--dashboard-host", default=None)
    parser.add_argument("--dashboard-port", type=int, default=None)
    parser.add_argument("--no-open-browser", action="store_true")
    parser.add_argument("--supervisor-interval", type=int, default=5)
    args = parser.parse_args()

    config_path = _resolve_config_path(args.config)
    env_file = Path(args.env_file)

    try:
        config_path, env_file = _run_onboarding_if_needed(
            config_path,
            env_file,
            force=args.force_onboard,
            skip_provider_tests=args.skip_provider_tests,
        )
    except KeyboardInterrupt:
        print("Onboarding cancelled.")
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"Onboarding failed: {exc}")
        return 1

    env = _prepare_runtime_env(env_file)
    env["LITTLEHIVE_CONFIG_FILE"] = str(config_path)

    try:
        cfg = load_app_config(instance_path=config_path)
    except Exception as exc:  # noqa: BLE001
        print(f"Invalid config: {exc}")
        return 1

    dashboard_host = args.dashboard_host or cfg.dashboard_host
    dashboard_port = args.dashboard_port or cfg.dashboard_port

    start_api = not args.no_api
    start_dashboard = not args.no_dashboard
    start_supervisor = not args.no_supervisor

    start_telegram = False
    if not args.no_telegram and cfg.channels.telegram.enabled:
        token_env = cfg.channels.telegram.token_env
        token_value = env.get(token_env, "").strip()
        if not token_value:
            token_value = input(f"Telegram token not set ({token_env}). Paste token (or leave blank to skip Telegram): ").strip()
            if token_value:
                env[token_env] = token_value
                _upsert_env_file(env_file, token_env, token_value)
                print(f"Saved {token_env} in {env_file}")

        if token_value:
            start_telegram = True
        else:
            print("Telegram is enabled in config but token is missing; skipping Telegram worker.")

    children: list[tuple[str, subprocess.Popen]] = []

    if start_api:
        children.append(
            (
                "api",
                _spawn(
                    "api",
                    [
                        sys.executable,
                        "-m",
                        "littlehive.apps.api_server",
                        "--config",
                        str(config_path),
                        "--host",
                        args.api_host,
                        "--port",
                        str(args.api_port),
                    ],
                    env,
                ),
            )
        )

    if start_dashboard:
        children.append(
            (
                "dashboard",
                _spawn(
                    "dashboard",
                    [
                        sys.executable,
                        "-m",
                        "littlehive.apps.dashboard",
                        "--config",
                        str(config_path),
                        "--host",
                        dashboard_host,
                        "--port",
                        str(dashboard_port),
                    ],
                    env,
                ),
            )
        )
        url = f"http://{dashboard_host}:{dashboard_port}"
        print(f"Dashboard URL: {url}")
        if not args.no_open_browser:
            try:
                webbrowser.open(url)
            except Exception:  # noqa: BLE001
                pass

    if start_telegram:
        children.append(
            (
                "telegram",
                _spawn(
                    "telegram",
                    [sys.executable, "-m", "littlehive.apps.telegram_worker", "--config", str(config_path)],
                    env,
                ),
            )
        )

    if start_supervisor:
        children.append(
            (
                "supervisor",
                _spawn(
                    "supervisor",
                    [
                        sys.executable,
                        "-m",
                        "littlehive.apps.supervisor",
                        "--config",
                        str(config_path),
                        "--interval",
                        str(args.supervisor_interval),
                    ],
                    env,
                ),
            )
        )

    if not children:
        print("Nothing to run. Re-enable at least one service.")
        return 1

    print("LittleHive is running. Press Ctrl+C to stop all services.")

    interrupted = False

    def _handle_signal(_sig, _frame):
        nonlocal interrupted
        interrupted = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    exit_code = 0
    try:
        while True:
            if interrupted:
                break

            for name, proc in children:
                code = proc.poll()
                if code is not None:
                    print(f"Service exited: {name} (code={code}). Stopping remaining services.")
                    exit_code = code if code != 0 else 1
                    interrupted = True
                    break

            if interrupted:
                break

            time.sleep(0.5)
    finally:
        _shutdown(children)

    if exit_code == 0 and interrupted:
        return 130
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
