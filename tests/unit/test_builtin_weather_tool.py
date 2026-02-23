from __future__ import annotations

from littlehive.core.telemetry.logging import get_logger
from littlehive.core.tools.base import ToolCallContext
from littlehive.core.tools.builtin.weather_tools import register_weather_tools
from littlehive.core.tools.executor import ToolExecutor
from littlehive.core.tools.registry import ToolRegistry


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, *args, **kwargs):
        _ = (args, kwargs)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        _ = (exc_type, exc, tb)
        return False

    def get(self, url: str, params: dict):
        _ = params
        if "weatherapi" in url:
            return _FakeResponse(
                {
                    "location": {"name": "San Francisco", "region": "CA", "country": "USA", "localtime": "2026-02-23 11:00"},
                    "current": {
                        "temp_c": 18,
                        "feelslike_c": 17,
                        "humidity": 60,
                        "wind_kph": 14,
                        "condition": {"text": "Partly cloudy"},
                    },
                    "forecast": {
                        "forecastday": [
                            {
                                "date": "2026-02-23",
                                "day": {
                                    "avgtemp_c": 18,
                                    "maxtemp_c": 20,
                                    "mintemp_c": 14,
                                    "condition": {"text": "Partly cloudy"},
                                    "daily_chance_of_rain": 20,
                                },
                            }
                        ]
                    },
                }
            )
        raise AssertionError(f"unexpected url: {url}")


def test_weather_tool_uses_provider(monkeypatch):
    monkeypatch.setattr("littlehive.core.tools.builtin.weather_tools.httpx.Client", _FakeClient)
    monkeypatch.setenv("LITTLEHIVE_WEATHER_API_KEY", "test-key")

    registry = ToolRegistry()
    register_weather_tools(registry, enabled=True, provider="weatherapi", api_key_env="LITTLEHIVE_WEATHER_API_KEY", timeout_seconds=5)
    ex = ToolExecutor(registry=registry, logger=get_logger("test.weather.get"))
    ctx = ToolCallContext(session_db_id=1, user_db_id=1, task_id=1, trace_id="w2")

    out = ex.execute("weather.get", ctx, {"location": "San Francisco"})
    assert out["status"] == "ok"
    assert out["location"]["name"] == "San Francisco"
    assert out["current"]["temp_c"] == 18
