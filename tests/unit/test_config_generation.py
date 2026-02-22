from __future__ import annotations

from pathlib import Path

from littlehive.core.config.loader import load_app_config
from littlehive.core.config.onboarding import OnboardingAnswers, generate_config_and_env


def test_config_generation_writes_yaml_without_secrets(tmp_path):
    answers = OnboardingAnswers(
        config_path=str(tmp_path / "instance.yaml"),
        env_path=str(tmp_path / ".env.local"),
        enable_telegram=True,
        telegram_token_env="TELEGRAM_BOT_TOKEN",
        telegram_allowed_ids=[123],
        enable_local_provider=True,
        local_api_key_env="LOCAL_KEY",
        enable_groq=True,
        groq_api_key_env="GROQ_KEY",
    )

    config_path, env_path = generate_config_and_env(
        answers,
        force=True,
        input_func=lambda _: "y",
        output_func=lambda _: None,
    )

    text = Path(config_path).read_text(encoding="utf-8")
    env_text = Path(env_path).read_text(encoding="utf-8")

    assert "LOCAL_KEY" in text
    assert "GROQ_KEY" in text
    assert "Bearer" not in text
    assert "TELEGRAM_BOT_TOKEN=" in env_text
    assert "LOCAL_KEY=" in env_text


def test_generated_config_validates_with_loader(tmp_path):
    answers = OnboardingAnswers(
        config_path=str(tmp_path / "instance.yaml"),
        env_path=str(tmp_path / ".env"),
        enable_local_provider=False,
        enable_groq=False,
    )
    generate_config_and_env(
        answers,
        force=True,
        input_func=lambda _: "y",
        output_func=lambda _: None,
    )

    cfg = load_app_config(instance_path=tmp_path / "instance.yaml")
    assert cfg.instance.name == "littlehive-local"
