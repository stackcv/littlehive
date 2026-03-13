"""
Shell, file-system, and TTS tools for LittleHive.
All operations are gated by the governance layer in shell_governance.py.
"""

import json
import os
import subprocess

from littlehive.agent.config import get_config
from littlehive.tools.shell_governance import (
    classify_command,
    log_execution,
    validate_path,
    _get_workspace,
)

MAX_OUTPUT_CHARS = 2000
MAX_FILE_READ_CHARS = 3000

SHELL_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "exec_command",
            "description": (
                "Run a shell command inside the user's workspace folder. "
                "The command is validated against security rules before execution. "
                "Use for git operations, running scripts, installing packages, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to run.",
                    },
                    "working_dir": {
                        "type": "string",
                        "description": "Optional sub-directory within the workspace to run in. Defaults to workspace root.",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read the contents of a file inside the workspace folder. "
                "Returns up to 3000 characters of the file content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file (relative to workspace or absolute within workspace).",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Write or create a file inside the workspace folder. "
                "Creates parent directories automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file (relative to workspace or absolute within workspace).",
                    },
                    "content": {
                        "type": "string",
                        "description": "The content to write to the file.",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": (
                "List contents of a directory inside the workspace folder. "
                "Shows files and sub-directories with basic info."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path (relative to workspace or absolute within workspace). Defaults to workspace root.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "announce",
            "description": (
                "Speak text aloud on the user's computer using text-to-speech. "
                "Use when the user asks you to announce, say, or speak something."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text to speak aloud.",
                    }
                },
                "required": ["text"],
            },
        },
    },
]


def _resolve_workspace_path(path_arg: str, config: dict | None = None) -> str:
    """If *path_arg* is relative, resolve it relative to the workspace root."""
    workspace = _get_workspace(config)
    if os.path.isabs(path_arg):
        return path_arg
    return os.path.join(workspace, path_arg)


def exec_command(command: str, working_dir: str | None = None) -> str:
    config = get_config()
    workspace = _get_workspace(config)

    os.makedirs(workspace, exist_ok=True)

    tier, reason = classify_command(command, config)

    if tier == "blocked":
        log_execution(command, "denied", reason, working_dir or workspace)
        return json.dumps({"error": f"Command blocked: {reason}"})

    cwd = workspace
    if working_dir:
        cwd = _resolve_workspace_path(working_dir, config)
        ok, cwd, path_reason = validate_path(cwd, config)
        if not ok:
            log_execution(command, "denied", path_reason, working_dir)
            return json.dumps({"error": f"Working directory blocked: {path_reason}"})

    if not os.path.isdir(cwd):
        return json.dumps({"error": f"Working directory does not exist: {cwd}"})

    timeout = config.get("shell_max_timeout", 60)

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = (result.stdout or "")[:MAX_OUTPUT_CHARS]
        stderr = (result.stderr or "")[:MAX_OUTPUT_CHARS]
        status = "success" if result.returncode == 0 else "error"

        log_execution(command, status, stdout[:200] or stderr[:200], cwd)

        return json.dumps({
            "exit_code": result.returncode,
            "stdout": stdout,
            "stderr": stderr,
        })

    except subprocess.TimeoutExpired:
        log_execution(command, "timeout", f"Exceeded {timeout}s", cwd)
        return json.dumps({"error": f"Command timed out after {timeout} seconds."})
    except Exception as e:
        log_execution(command, "error", str(e), cwd)
        return json.dumps({"error": str(e)})


def read_file(path: str) -> str:
    config = get_config()
    resolved = _resolve_workspace_path(path, config)
    ok, resolved, reason = validate_path(resolved, config)
    if not ok:
        return json.dumps({"error": reason})

    if not os.path.exists(resolved):
        return json.dumps({"error": f"File not found: {resolved}"})
    if os.path.isdir(resolved):
        return json.dumps({"error": "Path is a directory, not a file. Use list_directory instead."})

    try:
        with open(resolved, "r", errors="replace") as f:
            content = f.read(MAX_FILE_READ_CHARS)
        truncated = os.path.getsize(resolved) > MAX_FILE_READ_CHARS
        result = {"path": resolved, "content": content}
        if truncated:
            result["note"] = f"File truncated to {MAX_FILE_READ_CHARS} chars."
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


def write_file(path: str, content: str) -> str:
    config = get_config()
    resolved = _resolve_workspace_path(path, config)
    ok, resolved, reason = validate_path(resolved, config)
    if not ok:
        return json.dumps({"error": reason})

    try:
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        with open(resolved, "w") as f:
            f.write(content)
        log_execution(f"write_file: {resolved}", "success", f"{len(content)} chars written")
        return json.dumps({"success": True, "path": resolved, "bytes_written": len(content)})
    except Exception as e:
        return json.dumps({"error": str(e)})


def list_directory(path: str = "") -> str:
    config = get_config()
    if not path:
        resolved = _get_workspace(config)
    else:
        resolved = _resolve_workspace_path(path, config)

    ok, resolved, reason = validate_path(resolved, config)
    if not ok:
        return json.dumps({"error": reason})

    if not os.path.isdir(resolved):
        return json.dumps({"error": f"Not a directory: {resolved}"})

    try:
        entries = []
        for name in sorted(os.listdir(resolved)):
            full = os.path.join(resolved, name)
            entry = {"name": name, "type": "dir" if os.path.isdir(full) else "file"}
            if entry["type"] == "file":
                try:
                    entry["size"] = os.path.getsize(full)
                except OSError:
                    pass
            entries.append(entry)
        return json.dumps({"path": resolved, "entries": entries})
    except Exception as e:
        return json.dumps({"error": str(e)})


def announce(text: str) -> str:
    config = get_config()
    engine = config.get("tts_engine", "say")

    if not text or not text.strip():
        return json.dumps({"error": "No text provided to announce."})

    safe_text = text.replace('"', '\\"').replace("'", "\\'")

    try:
        if engine == "say":
            subprocess.run(
                ["say", safe_text],
                timeout=30,
                capture_output=True,
            )
            return json.dumps({"success": True, "engine": "say", "text": text})
        else:
            return json.dumps({"error": f"TTS engine '{engine}' is not yet supported. Use 'say' (macOS built-in)."})
    except FileNotFoundError:
        return json.dumps({"error": "The 'say' command is not available. This feature requires macOS."})
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "TTS timed out."})
    except Exception as e:
        return json.dumps({"error": str(e)})


def execute_tool(tool_name: str, tool_args: dict) -> str:
    if tool_name == "exec_command":
        return exec_command(
            command=tool_args.get("command", ""),
            working_dir=tool_args.get("working_dir"),
        )
    elif tool_name == "read_file":
        return read_file(path=tool_args.get("path", ""))
    elif tool_name == "write_file":
        return write_file(
            path=tool_args.get("path", ""),
            content=tool_args.get("content", ""),
        )
    elif tool_name == "list_directory":
        return list_directory(path=tool_args.get("path", ""))
    elif tool_name == "announce":
        return announce(text=tool_args.get("text", ""))
    else:
        return json.dumps({"error": f"Unknown shell tool: {tool_name}"})
