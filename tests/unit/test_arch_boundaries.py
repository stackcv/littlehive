from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_agents_do_not_import_provider_adapters_directly():
    disallowed: list[str] = []
    for py_file in (ROOT / "src/littlehive/core/agents").rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        if "openai_compatible" in content or "groq_adapter" in content:
            disallowed.append(str(py_file))
    assert disallowed == [], f"Agent imported provider adapter directly: {disallowed}"


def test_agents_do_not_call_tools_directly_except_via_executor():
    disallowed: list[str] = []
    for py_file in (ROOT / "src/littlehive/core/agents").rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        if "memory.search" in content or "task.create" in content:
            if "tool_executor" not in content:
                disallowed.append(str(py_file))
    assert disallowed == [], f"Agent executed tools without executor: {disallowed}"


def test_telegram_adapter_does_not_use_http_clients_directly():
    disallowed: list[str] = []
    for py_file in (ROOT / "src/littlehive/channels/telegram").rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        if "httpx." in content or "requests." in content:
            disallowed.append(str(py_file))
    assert disallowed == [], f"Telegram adapter made direct HTTP provider calls: {disallowed}"
