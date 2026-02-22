from __future__ import annotations

from pydantic import BaseModel, Field


class InstanceConfig(BaseModel):
    name: str = "littlehive"


class RuntimeConfig(BaseModel):
    request_timeout_seconds: int = 30
    max_steps: int = 8


class ContextConfig(BaseModel):
    recent_turns: int = 8
    snippet_cap: int = 6
    preflight_enabled: bool = True


class TelemetryConfig(BaseModel):
    log_level: str = "INFO"
    json_logs: bool = True


class DatabaseConfig(BaseModel):
    url: str = "sqlite:///littlehive.db"


class AppConfig(BaseModel):
    instance: InstanceConfig = Field(default_factory=InstanceConfig)
    timezone: str = "Asia/Kolkata"
    environment: str = "dev"
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    providers: dict = Field(default_factory=dict)
    channels: dict = Field(default_factory=dict)
