from __future__ import annotations

from littlehive.core.config import hardware_audit as hw


def test_hardware_audit_structured_without_gpu_info(monkeypatch):
    monkeypatch.setattr(hw, "_collect_nvidia_info", lambda: (None, "no gpu"))
    audit = hw.collect_hardware_audit()

    assert audit.os_name
    assert audit.python_version
    assert audit.cpu_logical_cores >= 1
    assert audit.nvidia is None
    assert "no gpu" in audit.warnings
