from __future__ import annotations

import pytest

from littlehive.core.config.loader import load_app_config


def test_config_loader_merges_defaults_and_instance(tmp_path):
    defaults = tmp_path / "defaults.yaml"
    defaults.write_text(
        """
instance:
  name: littlehive
timezone: Asia/Kolkata
environment: dev
runtime:
  max_steps: 8
""".strip(),
        encoding="utf-8",
    )

    instance = tmp_path / "instance.yaml"
    instance.write_text(
        """
environment: prod
runtime:
  max_steps: 12
""".strip(),
        encoding="utf-8",
    )

    cfg = load_app_config(defaults_path=defaults, instance_path=instance)
    assert cfg.instance.name == "littlehive"
    assert cfg.environment == "prod"
    assert cfg.runtime.max_steps == 12


def test_config_loader_validation_error_is_clear(tmp_path):
    defaults = tmp_path / "defaults.yaml"
    defaults.write_text("runtime:\n  max_steps: bad", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid LittleHive configuration"):
        load_app_config(defaults_path=defaults)
