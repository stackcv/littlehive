import sys
import os
import signal
import subprocess
import shutil
import time
from littlehive import __version__
from littlehive.agent.paths import LITTLEHIVE_DIR, CONFIG_DIR, TOKEN_PATH, CREDENTIALS_PATH, ensure_paths
from littlehive.agent.config import get_config, save_config_value, DEFAULT_CONFIG

PID_FILE = os.path.join(LITTLEHIVE_DIR, "littlehive.pid")
LOG_FILE = os.path.join(LITTLEHIVE_DIR, "logs", "agent.log")

AVAILABLE_MODELS = [
    {
        "key": "1",
        "name": "Ministral 3B Lite",
        "path": "mlx-community/Ministral-3-3B-Instruct-2512-4bit",
        "ram": "8GB+",
    },
    {
        "key": "2",
        "name": "Ministral 8B",
        "path": "mlx-community/Ministral-3-8B-Instruct-2512-4bit",
        "ram": "8GB+",
    },
    {
        "key": "3",
        "name": "Ministral 14B",
        "path": "mlx-community/mistralai_Ministral-3-14B-Instruct-2512-MLX-MXFP4",
        "ram": "16GB+",
    },
]


def _prompt(label, default="", required=False):
    """Prompt user for input with optional default value."""
    if default:
        raw = input(f"  {label} [{default}]: ").strip()
        return raw if raw else default
    suffix = " (required): " if required else ": "
    while True:
        raw = input(f"  {label}{suffix}").strip()
        if raw or not required:
            return raw
        print("    This field is required.")


def _yes_no(label, default_yes=True):
    hint = "Y/n" if default_yes else "y/N"
    raw = input(f"  {label} [{hint}]: ").strip().lower()
    if not raw:
        return default_yes
    return raw in ("y", "yes")


def setup():
    """Interactive onboarding wizard."""
    ensure_paths()
    config = get_config()
    is_rerun = config.get("onboarded", False)

    print()
    if is_rerun:
        print("=" * 55)
        print("  LittleHive Setup  (re-configuration)")
        print("  Current values shown as defaults — press Enter to keep")
        print("=" * 55)
    else:
        print("=" * 55)
        print("  Welcome to LittleHive")
        print("  Your local-first AI executive assistant")
        print("=" * 55)
        print()
        print("  Let's get you set up. This takes about 2 minutes.")

    # ── Phase 1: Identity ────────────────────────────────────
    print()
    print("─── Identity ───────────────────────────────────────")
    print()

    user_name = _prompt(
        "Your name",
        default=config.get("user_name", DEFAULT_CONFIG["user_name"]),
        required=True,
    )
    agent_name = _prompt(
        "Name for your assistant",
        default=config.get("agent_name", DEFAULT_CONFIG["agent_name"]),
    )
    agent_title = _prompt(
        "Assistant's title",
        default=config.get("agent_title", DEFAULT_CONFIG["agent_title"]),
    )
    home_location = _prompt(
        "Your location (city, country, or both — e.g. 'London', 'India', 'Berlin, Germany')",
        default=config.get("home_location", ""),
    )

    save_config_value("user_name", user_name)
    save_config_value("agent_name", agent_name)
    save_config_value("agent_title", agent_title)
    save_config_value("home_location", home_location)

    # ── Phase 2: Integrations ────────────────────────────────
    print()
    print("─── Google Workspace (Gmail, Calendar, Tasks) ──────")
    print()

    has_token = os.path.exists(TOKEN_PATH)
    has_creds = os.path.exists(CREDENTIALS_PATH)

    if has_token:
        print("  Google is already connected.")
        if _yes_no("Re-authenticate?", default_yes=False):
            _run_google_auth()
    elif has_creds:
        print("  credentials.json found. Let's connect your Google account.")
        _run_google_auth()
    else:
        print("  LittleHive needs a Google Cloud OAuth client to access your")
        print("  email, calendar, and tasks.")
        print()
        if _yes_no("Do you have a credentials.json file ready?", default_yes=False):
            creds_path = input("  Path to credentials.json: ").strip()
            creds_path = os.path.expanduser(creds_path)
            if os.path.isfile(creds_path):
                shutil.copy2(creds_path, CREDENTIALS_PATH)
                print(f"  Copied to {CREDENTIALS_PATH}")
                _run_google_auth()
            else:
                print(f"  File not found: {creds_path}")
                print("  Skipping Google setup. You can re-run: lhive setup")
        else:
            print()
            print("  To set up Google integration later:")
            print("    1. Go to console.cloud.google.com")
            print("    2. Create a project and enable Gmail, Calendar, Tasks APIs")
            print("    3. Create OAuth 2.0 credentials (Desktop application)")
            print("    4. Download the JSON and re-run: lhive setup")
            print()

    # ── Telegram ──
    print()
    print("─── Telegram (optional) ────────────────────────────")
    print()

    existing_token = config.get("telegram_bot_token", "")
    if existing_token:
        masked = existing_token[:8] + "..." + existing_token[-4:] if len(existing_token) > 12 else "****"
        print(f"  Telegram bot token already set ({masked})")
        if _yes_no("Update it?", default_yes=False):
            token = _prompt("Bot token from @BotFather", required=True)
            save_config_value("telegram_bot_token", token)
            print("  Telegram configured. Send /start to your bot to link it.")
    else:
        if _yes_no("Connect a Telegram bot?", default_yes=False):
            token = _prompt("Bot token from @BotFather", required=True)
            save_config_value("telegram_bot_token", token)
            print("  Telegram configured. Send /start to your bot to link it.")
        else:
            print("  Skipped. You can add this later via the dashboard.")

    # ── Phase 3: Preferences ─────────────────────────────────
    print()
    print("─── Preferences ────────────────────────────────────")
    print()

    # Model selection
    print("  AI Model (choose based on your Mac's RAM):")
    print()
    current_model = config.get("model_path", DEFAULT_CONFIG["model_path"])
    for m in AVAILABLE_MODELS:
        marker = " <-- current" if m["path"] == current_model else ""
        print(f"    {m['key']}. {m['name']}  ({m['ram']} RAM){marker}")
    print()

    model_choice = input("  Selection [keep current]: ").strip()
    if model_choice in [m["key"] for m in AVAILABLE_MODELS]:
        selected = next(m for m in AVAILABLE_MODELS if m["key"] == model_choice)
        save_config_value("model_path", selected["path"])
        print(f"  Model set to {selected['name']}")
    else:
        print("  Keeping current model.")

    # DnD
    print()
    dnd_start = config.get("dnd_start", DEFAULT_CONFIG["dnd_start"])
    dnd_end = config.get("dnd_end", DEFAULT_CONFIG["dnd_end"])
    print("  Do Not Disturb hours (agent won't send proactive notifications):")
    dnd_start_input = input(f"  DnD start hour (0-23) [{dnd_start}]: ").strip()
    dnd_end_input = input(f"  DnD end hour (0-23) [{dnd_end}]: ").strip()

    if dnd_start_input:
        try:
            save_config_value("dnd_start", int(dnd_start_input))
        except ValueError:
            print("  Invalid hour, keeping current.")
    if dnd_end_input:
        try:
            save_config_value("dnd_end", int(dnd_end_input))
        except ValueError:
            print("  Invalid hour, keeping current.")

    # ── Finalize ─────────────────────────────────────────────
    save_config_value("onboarded", True)

    print()
    print("─── Setup Complete ─────────────────────────────────")
    print()
    final_config = get_config()
    print(f"  User:       {final_config.get('user_name')}")
    print(f"  Assistant:  {final_config.get('agent_name')} ({final_config.get('agent_title')})")
    print(f"  Location:   {final_config.get('home_location') or '(not set)'}")
    print(f"  Google:     {'Connected' if os.path.exists(TOKEN_PATH) else 'Not connected'}")
    tg = final_config.get("telegram_bot_token", "")
    print(f"  Telegram:   {'Configured' if tg else 'Not configured'}")
    model_name = next(
        (m["name"] for m in AVAILABLE_MODELS if m["path"] == final_config.get("model_path")),
        final_config.get("model_path", "Unknown"),
    )
    print(f"  Model:      {model_name}")
    print(f"  DnD:        {final_config.get('dnd_start', 23)}:00 - {final_config.get('dnd_end', 7)}:00")
    print()
    print(f"  Config saved to: {os.path.join(CONFIG_DIR, 'config.json')}")
    print()

    if _yes_no("Start the agent now?"):
        start()
    else:
        print("  Run 'lhive start' when you're ready.")
        print()


def _run_google_auth():
    """Run the Google OAuth flow interactively."""
    print("  Opening browser for Google sign-in...")
    try:
        from littlehive.tools.google_auth import get_credentials
        creds = get_credentials()
        if creds and creds.valid:
            print("  Google connected successfully.")
        else:
            print("  Google authentication failed. You can retry with: lhive auth google")
    except Exception as e:
        print(f"  Google authentication error: {e}")
        print("  You can retry later with: lhive auth google")


def auth_google():
    """Standalone Google re-authentication."""
    ensure_paths()
    if not os.path.exists(CREDENTIALS_PATH):
        print(f"credentials.json not found at {CREDENTIALS_PATH}")
        print("Place your Google OAuth client file there and try again.")
        sys.exit(1)
    if os.path.exists(TOKEN_PATH):
        os.remove(TOKEN_PATH)
    _run_google_auth()


def status():
    """Show agent status and configuration summary."""
    ensure_paths()
    config = get_config()
    pid = get_pid()
    running = is_running(pid)

    print()
    print("─── LittleHive Status ──────────────────────────────")
    print()
    print(f"  Agent:      {'Running (PID: ' + str(pid) + ')' if running else 'Stopped'}")
    print(f"  Onboarded:  {'Yes' if config.get('onboarded') else 'No — run: lhive setup'}")
    print(f"  User:       {config.get('user_name', '(not set)')}")
    print(f"  Assistant:  {config.get('agent_name', '(not set)')} ({config.get('agent_title', '')})")
    print(f"  Location:   {config.get('home_location') or '(not set)'}")
    print(f"  Google:     {'Connected' if os.path.exists(TOKEN_PATH) else 'Not connected'}")
    tg = config.get("telegram_bot_token", "")
    print(f"  Telegram:   {'Configured' if tg else 'Not configured'}")
    model_name = next(
        (m["name"] for m in AVAILABLE_MODELS if m["path"] == config.get("model_path")),
        config.get("model_path", "Unknown"),
    )
    print(f"  Model:      {model_name}")
    print(f"  DnD:        {config.get('dnd_start', 23)}:00 - {config.get('dnd_end', 7)}:00")
    print("  Dashboard:  http://localhost:8080")
    print(f"  Logs:       {LOG_FILE}")
    print()


def get_pid():
    if os.path.exists(PID_FILE):
        with open(PID_FILE, "r") as f:
            try:
                return int(f.read().strip())
            except ValueError:
                return None
    return None


def is_running(pid):
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def start():
    config = get_config()
    if not config.get("onboarded", False):
        print("LittleHive has not been set up yet.")
        print("Run: lhive setup")
        sys.exit(1)

    pid = get_pid()
    if is_running(pid):
        print(f"Agent is already running (PID: {pid}).")
        return

    ensure_paths()
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    log_size = os.path.getsize(LOG_FILE) if os.path.exists(LOG_FILE) else 0

    with open(LOG_FILE, "a") as log_out:
        process = subprocess.Popen(
            [sys.executable, "-m", "littlehive.agent.start_agent"],
            stdout=log_out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    with open(PID_FILE, "w") as f:
        f.write(str(process.pid))

    sys.stdout.write("Starting LittleHive agent in the background...\n")

    chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    i = 0
    current_status = "Initializing..."

    with open(LOG_FILE, "r") as f:
        f.seek(log_size)
        while True:
            line = f.readline()
            if line:
                line = line.strip()
                if "Initializing Core Brain & loading model" in line:
                    current_status = (
                        "Loading AI Model (this may take a moment)"
                    )
                elif "Fetching" in line and "huggingface" in line:
                    current_status = (
                        "Downloading AI Model (first time only, may take a few minutes)"
                    )
                elif "Pre-warming prompt cache" in line:
                    current_status = "Warming up neural cache for fast responses"
                elif "Starting Web Dashboard" in line:
                    current_status = "Starting local servers"
                elif "All senses active" in line:
                    sys.stdout.write(
                        "\r\033[K  LittleHive is fully awake and ready!\n"
                    )
                    print(f"  Agent running in background (PID: {process.pid})")
                    print(f"  Logs: {LOG_FILE}")
                    print("  Dashboard: http://localhost:8080")
                    print()
                    break
            else:
                if process.poll() is not None:
                    sys.stdout.write(
                        "\r\033[K  Agent process died unexpectedly. Check logs.\n"
                    )
                    sys.exit(1)

                sys.stdout.write(
                    f"\r\033[K\033[96m{chars[i % len(chars)]}\033[0m {current_status}"
                )
                sys.stdout.flush()
                time.sleep(0.1)
                i += 1


def stop():
    pid = get_pid()
    if not is_running(pid):
        print("Agent is not currently running.")
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
        return

    print(f"Stopping agent (PID: {pid})...")
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(10):
            if not is_running(pid):
                break
            time.sleep(0.5)

        if is_running(pid):
            print("Process didn't stop gracefully. Force killing...")
            os.kill(pid, signal.SIGKILL)
    except OSError as e:
        print(f"Error stopping process: {e}")

    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)
    print("  Agent stopped.")


def version():
    """Print current version."""
    print(f"LittleHive v{__version__}")


def update():
    """Check for updates and upgrade from PyPI."""
    print(f"  Current version: {__version__}")
    print("  Checking for updates...")

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "index", "versions", "littlehive"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--dry-run", "--upgrade", "littlehive"],
                capture_output=True, text=True, timeout=30,
            )
            if "already satisfied" in result.stdout.lower() or "already up-to-date" in result.stdout.lower():
                print(f"  Already on the latest version ({__version__}).")
                return
            elif result.returncode != 0 and "no matching distribution" in result.stderr.lower():
                print("  Package not found on PyPI. Are you running from a local install?")
                return
        else:
            output = result.stdout.strip()
            if output:
                import re
                versions = re.findall(r"[\d]+\.[\d]+\.[\d]+", output)
                if versions:
                    latest = versions[0]
                    if latest == __version__:
                        print(f"  Already on the latest version ({__version__}).")
                        return
                    print(f"  New version available: {latest}")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    print("  Upgrading...")
    upgrade = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "littlehive"],
        capture_output=True, text=True,
    )
    if upgrade.returncode == 0:
        print("  Updated successfully! Restart with: lhive restart")
    else:
        print(f"  Update failed: {upgrade.stderr.strip()}")


def main():
    if len(sys.argv) < 2:
        print(f"LittleHive v{__version__}")
        print()
        print("Usage: lhive <command>")
        print()
        print("Commands:")
        print("  setup          Interactive setup wizard (run this first)")
        print("  start          Start the agent")
        print("  stop           Stop the agent")
        print("  restart        Restart the agent")
        print("  status         Show agent status and configuration")
        print("  update         Check for and install updates from PyPI")
        print("  version        Show current version")
        print("  auth google    Re-run Google OAuth flow")
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "setup":
        setup()
    elif cmd == "start":
        start()
    elif cmd == "stop":
        stop()
    elif cmd == "restart":
        stop()
        time.sleep(1)
        start()
    elif cmd == "status":
        status()
    elif cmd == "update":
        update()
    elif cmd == "version" or cmd == "--version" or cmd == "-v":
        version()
    elif cmd == "auth":
        if len(sys.argv) >= 3 and sys.argv[2].lower() == "google":
            auth_google()
        else:
            print("Usage: lhive auth google")
            sys.exit(1)
    else:
        print(f"Unknown command: {cmd}")
        print("Run 'lhive' without arguments to see available commands.")
        sys.exit(1)


if __name__ == "__main__":
    main()
