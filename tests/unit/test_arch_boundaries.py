from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_provider_router_boundary_only_in_provider_module():
    disallowed_hits: list[str] = []
    for py_file in (ROOT / "src/littlehive").rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        if "from littlehive.core.providers" in content or "littlehive.core.providers" in content:
            if "src/littlehive/core/providers/" not in str(py_file).replace("\\", "/"):
                if py_file.name != "test_arch_boundaries.py":
                    disallowed_hits.append(str(py_file))

    assert disallowed_hits == [], f"Provider module imported outside boundary: {disallowed_hits}"
