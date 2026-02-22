from __future__ import annotations

import os
import platform
import shutil
import sys
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class NvidiaInfo(BaseModel):
    gpu_count: int = 0
    names: list[str] = Field(default_factory=list)
    total_vram_gb: float = 0.0


class HardwareAudit(BaseModel):
    collected_at_utc: str
    os_name: str
    os_version: str
    platform: str
    python_version: str
    cpu_arch: str
    cpu_logical_cores: int
    cpu_physical_cores: int | None = None
    total_ram_gb: float | None = None
    disk_free_gb: float | None = None
    is_apple_silicon: bool = False
    nvidia: NvidiaInfo | None = None
    warnings: list[str] = Field(default_factory=list)


_GIB = 1024 * 1024 * 1024


def _ram_total_bytes() -> int | None:
    try:
        if hasattr(os, "sysconf") and "SC_PAGE_SIZE" in os.sysconf_names and "SC_PHYS_PAGES" in os.sysconf_names:
            return int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES"))
    except Exception:
        return None
    return None


def _physical_cores() -> int | None:
    # Keep dependency-free and best-effort.
    return None


def _collect_nvidia_info() -> tuple[NvidiaInfo | None, str | None]:
    try:
        import pynvml  # type: ignore
    except Exception:
        return None, "pynvml not installed; skipping NVIDIA detection"

    try:
        pynvml.nvmlInit()
        count = int(pynvml.nvmlDeviceGetCount())
        names: list[str] = []
        total = 0
        for i in range(count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8", errors="ignore")
            names.append(str(name))
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            total += int(mem.total)
        pynvml.nvmlShutdown()
        return NvidiaInfo(gpu_count=count, names=names, total_vram_gb=round(total / _GIB, 2)), None
    except Exception as exc:  # noqa: BLE001
        return None, f"NVIDIA detection failed: {exc}"


def collect_hardware_audit() -> HardwareAudit:
    warnings: list[str] = []
    total_ram = _ram_total_bytes()
    free_disk = shutil.disk_usage(".").free
    nvidia, nvidia_warning = _collect_nvidia_info()
    if nvidia_warning:
        warnings.append(nvidia_warning)

    machine = platform.machine().lower()
    is_apple_silicon = sys.platform == "darwin" and machine in {"arm64", "aarch64"}

    return HardwareAudit(
        collected_at_utc=datetime.now(timezone.utc).isoformat(),
        os_name=platform.system(),
        os_version=platform.version(),
        platform=platform.platform(),
        python_version=platform.python_version(),
        cpu_arch=platform.machine(),
        cpu_logical_cores=int(os.cpu_count() or 1),
        cpu_physical_cores=_physical_cores(),
        total_ram_gb=round(total_ram / _GIB, 2) if total_ram else None,
        disk_free_gb=round(free_disk / _GIB, 2),
        is_apple_silicon=is_apple_silicon,
        nvidia=nvidia,
        warnings=warnings,
    )


def render_hardware_summary(audit: HardwareAudit) -> str:
    gpu = "none"
    if audit.nvidia and audit.nvidia.gpu_count > 0:
        gpu = f"{audit.nvidia.gpu_count} NVIDIA GPU(s), total_vram_gb={audit.nvidia.total_vram_gb}"
    return (
        f"OS={audit.os_name} arch={audit.cpu_arch} py={audit.python_version} "
        f"cores={audit.cpu_logical_cores} ram_gb={audit.total_ram_gb} disk_free_gb={audit.disk_free_gb} "
        f"apple_silicon={audit.is_apple_silicon} gpu={gpu}"
    )


def hardware_audit_dict(audit: HardwareAudit) -> dict[str, Any]:
    return audit.model_dump()
