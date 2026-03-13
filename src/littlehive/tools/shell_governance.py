"""
Shell Governance Layer — enforces security policies in Python code,
independent of LLM behavior.  The LLM can attempt anything; this module
decides what actually executes.
"""

import os
import re
import shlex
import sqlite3

from littlehive.agent.config import get_config
from littlehive.agent.logger_setup import logger
from littlehive.agent.paths import DB_PATH

# ── Dangerous patterns that are ALWAYS blocked regardless of tier lists ──

_BLOCKED_PATTERNS = [
    re.compile(r"\brm\s+.*-\s*[^\s]*r[^\s]*f", re.IGNORECASE),  # rm -rf, rm -fr
    re.compile(r"\brm\s+-rf\b", re.IGNORECASE),
    re.compile(r"\bsudo\b"),
    re.compile(r"\bsu\b\s"),
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bdd\b\s+if="),
    re.compile(r"\bfdisk\b"),
    re.compile(r"\bformat\b"),
    re.compile(r"\bchmod\s+777\b"),
    re.compile(r"\bchown\b"),
    re.compile(r"\bsystemctl\b"),
    re.compile(r"\blaunchctl\b"),
    re.compile(r"\bexport\s+PATH="),
    re.compile(r"\beval\b"),
    re.compile(r"\bsource\b"),
    re.compile(r">\s*/etc/"),
    re.compile(r">\s*/usr/"),
    re.compile(r">\s*/System/"),
    re.compile(r">\s*~/\.ssh/"),
    re.compile(r">\s*~/\.gnupg/"),
]

# Paths that are never writable, even inside the workspace
_PROTECTED_PATH_FRAGMENTS = [
    "/.ssh/", "/.gnupg/", "/.littlehive/config/",
]


def _get_workspace(config: dict | None = None) -> str:
    """Return the resolved, absolute workspace path."""
    if config is None:
        config = get_config()
    raw = config.get("shell_workspace", "~/littlehive-workspace")
    return os.path.realpath(os.path.expanduser(raw))


def validate_path(path: str, config: dict | None = None) -> tuple[bool, str, str]:
    """Check that *path* resolves to somewhere inside the workspace.

    Returns (allowed, resolved_path, reason).
    """
    if config is None:
        config = get_config()

    workspace = _get_workspace(config)
    resolved = os.path.realpath(os.path.expanduser(path))

    for frag in _PROTECTED_PATH_FRAGMENTS:
        if frag in resolved:
            return False, resolved, f"Path contains protected fragment: {frag}"

    if not resolved.startswith(workspace + os.sep) and resolved != workspace:
        return False, resolved, (
            f"Path '{resolved}' is outside the allowed workspace '{workspace}'"
        )

    return True, resolved, "ok"


def classify_command(command: str, config: dict | None = None) -> tuple[str, str]:
    """Classify a shell command into a governance tier.

    Returns (tier, reason) where tier is one of:
        "allowed"  – execute silently
        "logged"   – execute and write to audit log
        "blocked"  – refuse execution
    """
    if config is None:
        config = get_config()

    for pat in _BLOCKED_PATTERNS:
        if pat.search(command):
            return "blocked", f"Command matches blocked pattern: {pat.pattern}"

    blocked_list = config.get("shell_blocked_commands", [])
    for bc in blocked_list:
        if bc and bc in command:
            return "blocked", f"Command contains blocked token: '{bc}'"

    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()

    base_cmd = os.path.basename(tokens[0]) if tokens else ""

    allowed_list = config.get("shell_allowed_commands", [])
    for ac in allowed_list:
        if ac == base_cmd or command.startswith(ac):
            return "allowed", f"Matches allowed entry: '{ac}'"

    logged_list = config.get("shell_logged_commands", [])
    for lc in logged_list:
        if lc == base_cmd or command.startswith(lc):
            return "logged", f"Matches logged entry: '{lc}'"

    return "blocked", (
        f"Command '{base_cmd}' is not in any allow/logged list — blocked by default"
    )


def log_execution(command: str, status: str, output_summary: str = "",
                  working_dir: str = "") -> None:
    """Write an entry to the shell_audit_log table."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='shell_audit_log'"
        )
        if not cursor.fetchone():
            conn.close()
            return
        cursor.execute(
            "INSERT INTO shell_audit_log (command, working_dir, status, output_summary) "
            "VALUES (?, ?, ?, ?)",
            (command, working_dir, status, (output_summary or "")[:500]),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug(f"[ShellGovernance] Audit log write failed: {e}")
