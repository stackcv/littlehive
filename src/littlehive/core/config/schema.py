from __future__ import annotations

from pydantic import BaseModel, Field


class InstanceConfig(BaseModel):
    name: str = "littlehive"


class RuntimeConfig(BaseModel):
    safe_mode: bool = True
    request_timeout_seconds: int = 30
    max_steps: int = 4
    retry_attempts: int = 2
    provider_retry_attempts: int = 2
    tool_retry_attempts: int = 2
    provider_timeout_seconds: int = 20
    breaker_failure_threshold: int = 3
    breaker_cool_down_seconds: int = 25
    reflexion_max_per_step: int = 1
    reflexion_max_per_task: int = 2


class ContextConfig(BaseModel):
    recent_turns: int = 4
    snippet_cap: int = 4
    preflight_enabled: bool = True
    max_input_tokens: int = 1200
    reserved_output_tokens: int = 256
    memory_top_k: int = 3


class TelemetryConfig(BaseModel):
    log_level: str = "INFO"
    json_logs: bool = True


class DatabaseConfig(BaseModel):
    url: str = "sqlite:///littlehive.db"


class ProviderConfig(BaseModel):
    enabled: bool = False
    base_url: str | None = None
    api_key_env: str | None = None
    model: str | None = None
    models: list[str] = Field(default_factory=list)
    timeout_seconds: int = 20


class ProvidersConfig(BaseModel):
    primary: str = "local_compatible"
    fallback_order: list[str] = Field(default_factory=lambda: ["local_compatible", "groq"])
    local_compatible: ProviderConfig = Field(default_factory=ProviderConfig)
    groq: ProviderConfig = Field(default_factory=ProviderConfig)


class TelegramChannelConfig(BaseModel):
    enabled: bool = False
    token_env: str = "LITTLEHIVE_TELEGRAM_TOKEN"
    owner_user_id: int | None = None
    allow_user_ids: list[int] = Field(default_factory=list)
    polling_timeout_seconds: int = 30


class ChannelsConfig(BaseModel):
    telegram: TelegramChannelConfig = Field(default_factory=TelegramChannelConfig)


class AppConfig(BaseModel):
    instance: InstanceConfig = Field(default_factory=InstanceConfig)
    timezone: str = "Asia/Kolkata"
    environment: str = "dev"
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
