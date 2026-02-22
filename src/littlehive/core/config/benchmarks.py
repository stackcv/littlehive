"""Phase 1.5 benchmark placeholders for future persisted benchmarking support."""

from __future__ import annotations

from pathlib import Path


def benchmark_results_path(base_dir: str = "diagnostics") -> Path:
    return Path(base_dir) / "benchmark_results.json"
