from __future__ import annotations

from pydantic import BaseModel, Field

from littlehive.core.config.hardware_audit import HardwareAudit
from littlehive.core.providers.health import ProviderCheckResult


class ModelRecommendation(BaseModel):
    mapping: dict[str, str]
    warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    confidence: str = "medium"


def _first_model(models: list[str], fallback: str) -> str:
    return models[0] if models else fallback


def recommend_models(
    *,
    hardware: HardwareAudit,
    provider_results: dict[str, ProviderCheckResult],
    configured_local_models: list[str],
    configured_groq_models: list[str],
) -> ModelRecommendation:
    local_result = provider_results.get("local_compatible")
    groq_result = provider_results.get("groq")
    local_ok = bool(local_result and local_result.ok)
    groq_ok = bool(groq_result and groq_result.ok)
    local_enabled = bool(local_result and local_result.enabled)
    groq_enabled = bool(groq_result and groq_result.enabled)

    local_model = _first_model(configured_local_models, "local-small-model")
    groq_model = _first_model(configured_groq_models, "groq-fast-model")

    mapping = {
        "orchestrator": groq_model if groq_ok else local_model,
        "planner": groq_model if groq_ok else local_model,
        "execution": groq_model if groq_ok else local_model,
        "memory": local_model if local_enabled else (groq_model if groq_enabled else local_model),
        "reply": local_model if local_enabled else (groq_model if groq_enabled else local_model),
    }

    warnings: list[str] = []
    notes: list[str] = []

    if not local_ok and not groq_ok:
        warnings.append("No configured providers passed connectivity checks.")

    weak_markers = ("1b", "2b", "3b", "mini", "tiny")
    if any(marker in mapping["orchestrator"].lower() for marker in weak_markers):
        warnings.append("Orchestrator model may be too small for robust planning quality.")

    if hardware.is_apple_silicon and (hardware.total_ram_gb or 0) < 24:
        notes.append("Apple Silicon with moderate RAM: prefer small/quantized local models for worker roles.")

    if hardware.nvidia and hardware.nvidia.total_vram_gb >= 16:
        notes.append("Detected higher NVIDIA VRAM; larger local worker models may be feasible.")

    confidence = "high" if (local_ok or groq_ok) else "low"

    return ModelRecommendation(mapping=mapping, warnings=warnings, notes=notes, confidence=confidence)
