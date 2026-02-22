from __future__ import annotations

from littlehive.core.config.hardware_audit import HardwareAudit, NvidiaInfo
from littlehive.core.config.recommender import recommend_models
from littlehive.core.providers.health import ProviderCheckResult


def test_recommendation_rules_deterministic_for_mocked_inputs():
    hardware = HardwareAudit(
        collected_at_utc="2026-01-01T00:00:00Z",
        os_name="Darwin",
        os_version="",
        platform="",
        python_version="3.12.0",
        cpu_arch="arm64",
        cpu_logical_cores=8,
        total_ram_gb=16,
        disk_free_gb=100,
        is_apple_silicon=True,
        nvidia=NvidiaInfo(gpu_count=0, names=[], total_vram_gb=0),
        warnings=[],
    )
    results = {
        "local_compatible": ProviderCheckResult(provider="local_compatible", enabled=True, ok=True),
        "groq": ProviderCheckResult(provider="groq", enabled=True, ok=False, error="timeout"),
    }

    rec = recommend_models(
        hardware=hardware,
        provider_results=results,
        configured_local_models=["llama3.1:8b"],
        configured_groq_models=["llama-3.1-8b-instant"],
    )

    assert rec.mapping["memory"] == "llama3.1:8b"
    assert rec.mapping["orchestrator"] == "llama3.1:8b"
    assert rec.confidence == "high"
    assert any("Apple Silicon" in note for note in rec.notes)
