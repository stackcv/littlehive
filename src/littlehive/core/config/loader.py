from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from littlehive.core.config.schema import AppConfig


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    if content is None:
        return {}
    if not isinstance(content, dict):
        raise ValueError(f"Config file must contain a mapping: {path}")
    return content


def load_app_config(
    defaults_path: str | Path = "config/defaults.yaml",
    instance_path: str | Path | None = None,
) -> AppConfig:
    defaults = _load_yaml(Path(defaults_path))

    explicit_instance = instance_path or os.getenv("LITTLEHIVE_CONFIG_FILE")
    instance = _load_yaml(Path(explicit_instance)) if explicit_instance else {}

    merged = _deep_merge(defaults, instance)

    env_timezone = os.getenv("LITTLEHIVE_TIMEZONE")
    if env_timezone:
        merged["timezone"] = env_timezone

    env_environment = os.getenv("LITTLEHIVE_ENVIRONMENT")
    if env_environment:
        merged["environment"] = env_environment

    try:
        return AppConfig.model_validate(merged)
    except ValidationError as exc:
        raise ValueError(f"Invalid LittleHive configuration: {exc}") from exc
