from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import yaml

from littlehive.core.config.hardware_audit import collect_hardware_audit, render_hardware_summary
from littlehive.core.config.loader import load_app_config
from littlehive.core.config.recommender import ModelRecommendation, recommend_models
from littlehive.core.providers.health import ProviderCheckResult, check_configured_providers


@dataclass(slots=True)
class OnboardingAnswers:
    instance_name: str = "littlehive-local"
    timezone: str = "Asia/Kolkata"
    environment: str = "prod"
    config_path: str = "config/instance.yaml"
    env_path: str = ".env"
    enable_telegram: bool = False
    telegram_token_env: str = "TELEGRAM_BOT_TOKEN"
    telegram_allowed_ids: list[int] | None = None
    telegram_owner_id: int | None = None
    enable_local_provider: bool = True
    local_base_url: str = "http://localhost:8001/v1"
    local_api_key_env: str = "LITTLEHIVE_LOCAL_PROVIDER_KEY"
    local_models: list[str] | None = None
    enable_groq: bool = False
    groq_api_key_env: str = "LITTLEHIVE_GROQ_API_KEY"
    groq_models: list[str] | None = None
    safe_mode: bool = True
    max_steps: int = 4
    step_timeout_seconds: int = 30
    recent_turn_limit: int = 4
    max_memory_snippets: int = 4

    def __post_init__(self) -> None:
        if self.telegram_allowed_ids is None:
            self.telegram_allowed_ids = []
        if self.local_models is None:
            self.local_models = ["llama3.1:8b"]
        if self.groq_models is None:
            self.groq_models = ["llama-3.1-8b-instant"]


@dataclass(slots=True)
class OnboardingResult:
    config_path: str
    env_path: str
    provider_results: dict[str, ProviderCheckResult]
    recommendation: ModelRecommendation
    hardware_summary: str


def _parse_bool(value: str, default: bool) -> bool:
    value = value.strip().lower()
    if not value:
        return default
    return value in {"y", "yes", "1", "true", "t"}


def parse_id_list(raw: str) -> list[int]:
    raw = raw.strip()
    if not raw:
        return []
    ids: list[int] = []
    for chunk in raw.split(","):
        v = chunk.strip()
        if not v:
            continue
        if not v.isdigit():
            raise ValueError(f"Invalid Telegram ID '{v}': must be numeric")
        ids.append(int(v))
    return ids


def _parse_models(raw: str, default: list[str]) -> list[str]:
    raw = raw.strip()
    if not raw:
        return list(default)
    return [m.strip() for m in raw.split(",") if m.strip()]


def _should_overwrite(path: Path, *, force: bool, input_func: Callable[[str], str]) -> bool:
    if not path.exists():
        return True
    if force:
        return True
    reply = input_func(f"{path} exists. Overwrite? [y/N]: ")
    return _parse_bool(reply, False)


def _build_config(answers: OnboardingAnswers) -> dict:
    return {
        "instance": {"name": answers.instance_name},
        "timezone": answers.timezone,
        "environment": answers.environment,
        "runtime": {
            "safe_mode": answers.safe_mode,
            "request_timeout_seconds": answers.step_timeout_seconds,
            "max_steps": answers.max_steps,
        },
        "context": {
            "recent_turns": answers.recent_turn_limit,
            "snippet_cap": answers.max_memory_snippets,
            "preflight_enabled": True,
            "memory_top_k": answers.max_memory_snippets,
        },
        "providers": {
            "primary": "local_compatible" if answers.enable_local_provider else "groq",
            "fallback_order": ["local_compatible", "groq"],
            "local_compatible": {
                "enabled": answers.enable_local_provider,
                "base_url": answers.local_base_url,
                "api_key_env": answers.local_api_key_env,
                "model": answers.local_models[0] if answers.local_models else None,
                "models": answers.local_models,
            },
            "groq": {
                "enabled": answers.enable_groq,
                "api_key_env": answers.groq_api_key_env,
                "model": answers.groq_models[0] if answers.groq_models else None,
                "models": answers.groq_models,
            },
        },
        "channels": {
            "telegram": {
                "enabled": answers.enable_telegram,
                "token_env": answers.telegram_token_env,
                "owner_user_id": answers.telegram_owner_id,
                "allow_user_ids": answers.telegram_allowed_ids,
            }
        },
    }


def _build_env_lines(answers: OnboardingAnswers) -> list[str]:
    lines = [
        f"# LittleHive onboarding generated at {datetime.now(timezone.utc).isoformat()}",
        "",
        "# Config",
        f"LITTLEHIVE_CONFIG_FILE={answers.config_path}",
    ]
    if answers.enable_telegram:
        lines += ["", "# Telegram", f"{answers.telegram_token_env}="]
    if answers.enable_local_provider:
        lines += ["", "# Local provider", f"{answers.local_api_key_env}="]
    if answers.enable_groq:
        lines += ["", "# Groq", f"{answers.groq_api_key_env}="]
    return lines


def generate_config_and_env(
    answers: OnboardingAnswers,
    *,
    force: bool,
    input_func: Callable[[str], str],
    output_func: Callable[[str], None],
) -> tuple[Path, Path]:
    config_path = Path(answers.config_path)
    env_path = Path(answers.env_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if not _should_overwrite(config_path, force=force, input_func=input_func):
        raise RuntimeError(f"Refused to overwrite existing file: {config_path}")
    if not _should_overwrite(env_path, force=force, input_func=input_func):
        raise RuntimeError(f"Refused to overwrite existing file: {env_path}")

    config_data = _build_config(answers)
    config_path.write_text(yaml.safe_dump(config_data, sort_keys=False), encoding="utf-8")
    env_path.write_text("\n".join(_build_env_lines(answers)) + "\n", encoding="utf-8")

    # Validate generated config immediately.
    load_app_config(instance_path=config_path)

    output_func(f"Generated config: {config_path}")
    output_func(f"Generated env template: {env_path}")
    return config_path, env_path


def collect_interactive_answers(input_func: Callable[[str], str], output_func: Callable[[str], None]) -> OnboardingAnswers:
    tz_default = os.getenv("TZ", "Asia/Kolkata")
    output_func("LittleHive onboarding")

    instance_name = input_func("Instance name [littlehive-local]: ").strip() or "littlehive-local"
    timezone = input_func(f"Timezone [{tz_default}]: ").strip() or tz_default
    environment = input_func("Environment [prod]: ").strip() or "prod"
    config_path = input_func("Config output path [config/instance.yaml]: ").strip() or "config/instance.yaml"
    env_path = input_func("Env output path [.env]: ").strip() or ".env"

    enable_telegram = _parse_bool(input_func("Enable Telegram? [y/N]: "), False)
    telegram_token_env = "TELEGRAM_BOT_TOKEN"
    telegram_allowed_ids: list[int] = []
    telegram_owner_id: int | None = None
    if enable_telegram:
        telegram_token_env = (
            input_func("Telegram token environment variable name [TELEGRAM_BOT_TOKEN]: ").strip() or "TELEGRAM_BOT_TOKEN"
        )
        ids_raw = input_func("Allowed Telegram user IDs (comma-separated): ")
        telegram_allowed_ids = parse_id_list(ids_raw)
        owner_raw = input_func("Owner Telegram user ID (optional): ").strip()
        telegram_owner_id = int(owner_raw) if owner_raw else None

    enable_local_provider = _parse_bool(input_func("Enable local OpenAI-compatible provider? [Y/n]: "), True)
    local_base_url = "http://localhost:8001/v1"
    local_api_key_env = "LITTLEHIVE_LOCAL_PROVIDER_KEY"
    local_models = ["llama3.1:8b"]
    if enable_local_provider:
        local_base_url = input_func("Local provider base URL [http://localhost:8001/v1]: ").strip() or local_base_url
        local_api_key_env = input_func("Local provider API key env var [LITTLEHIVE_LOCAL_PROVIDER_KEY]: ").strip() or local_api_key_env
        local_models = _parse_models(
            input_func("Local model IDs (comma-separated) [llama3.1:8b]: "),
            default=local_models,
        )

    enable_groq = _parse_bool(input_func("Enable Groq provider? [y/N]: "), False)
    groq_api_key_env = "LITTLEHIVE_GROQ_API_KEY"
    groq_models = ["llama-3.1-8b-instant"]
    if enable_groq:
        groq_api_key_env = input_func("Groq API key env var [LITTLEHIVE_GROQ_API_KEY]: ").strip() or groq_api_key_env
        groq_models = _parse_models(
            input_func("Groq model IDs (comma-separated) [llama-3.1-8b-instant]: "),
            default=groq_models,
        )

    safe_mode = _parse_bool(input_func("Enable safe mode? [Y/n]: "), True)
    max_steps = int((input_func("Max steps per task [4]: ").strip() or "4"))
    step_timeout = int((input_func("Step timeout seconds [30]: ").strip() or "30"))
    recent_turn_limit = int((input_func("Recent turn limit [4]: ").strip() or "4"))
    max_memory_snippets = int((input_func("Max memory snippets [4]: ").strip() or "4"))

    return OnboardingAnswers(
        instance_name=instance_name,
        timezone=timezone,
        environment=environment,
        config_path=config_path,
        env_path=env_path,
        enable_telegram=enable_telegram,
        telegram_token_env=telegram_token_env,
        telegram_allowed_ids=telegram_allowed_ids,
        telegram_owner_id=telegram_owner_id,
        enable_local_provider=enable_local_provider,
        local_base_url=local_base_url,
        local_api_key_env=local_api_key_env,
        local_models=local_models,
        enable_groq=enable_groq,
        groq_api_key_env=groq_api_key_env,
        groq_models=groq_models,
        safe_mode=safe_mode,
        max_steps=max_steps,
        step_timeout_seconds=step_timeout,
        recent_turn_limit=recent_turn_limit,
        max_memory_snippets=max_memory_snippets,
    )


def run_onboarding(
    *,
    answers: OnboardingAnswers,
    force: bool,
    skip_provider_tests: bool,
    output_func: Callable[[str], None],
    input_func: Callable[[str], str],
    allow_no_provider_success: bool = False,
) -> OnboardingResult:
    config_path, env_path = generate_config_and_env(
        answers,
        force=force,
        input_func=input_func,
        output_func=output_func,
    )

    cfg = load_app_config(instance_path=config_path)
    hardware = collect_hardware_audit()
    provider_results = check_configured_providers(cfg, skip_tests=skip_provider_tests)
    recommendation = recommend_models(
        hardware=hardware,
        provider_results=provider_results,
        configured_local_models=cfg.providers.local_compatible.models,
        configured_groq_models=cfg.providers.groq.models,
    )

    if not allow_no_provider_success and not skip_provider_tests:
        if not any(r.ok for r in provider_results.values() if r.enabled):
            raise RuntimeError("No enabled providers passed connectivity test; rerun with --skip-provider-tests to proceed.")

    return OnboardingResult(
        config_path=str(config_path),
        env_path=str(env_path),
        provider_results=provider_results,
        recommendation=recommendation,
        hardware_summary=render_hardware_summary(hardware),
    )
