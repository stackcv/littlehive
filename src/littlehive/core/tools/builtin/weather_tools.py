from __future__ import annotations

import os

import httpx

from littlehive.core.tools.base import ToolCallContext, ToolMetadata


def _normalize_days(value: object) -> int:
    try:
        days = int(value)
    except Exception:  # noqa: BLE001
        days = 1
    return max(1, min(days, 3))


def register_weather_tools(
    registry,
    *,
    enabled: bool,
    provider: str = "weatherapi",
    api_key_env: str = "LITTLEHIVE_WEATHER_API_KEY",
    timeout_seconds: int = 10,
) -> None:
    def weather_get(_ctx: ToolCallContext, args: dict) -> dict:
        if not enabled:
            raise RuntimeError("weather tool not configured: tools.weather.enabled=false")

        query = str(args.get("location") or args.get("query") or "").strip()
        if not query:
            return {"status": "ignored", "reason": "missing_location"}

        backend = provider.strip().lower()
        if backend != "weatherapi":
            raise RuntimeError(f"unsupported weather provider: {provider}")

        api_key = os.getenv(api_key_env, "").strip()
        if not api_key:
            raise RuntimeError(f"weather tool not configured: missing {api_key_env}")

        days = _normalize_days(args.get("days", 1))

        with httpx.Client(timeout=float(timeout_seconds), follow_redirects=True) as client:
            resp = client.get(
                "https://api.weatherapi.com/v1/forecast.json",
                params={
                    "key": api_key,
                    "q": query,
                    "days": days,
                    "aqi": "no",
                    "alerts": "no",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        location = data.get("location") or {}
        current = data.get("current") or {}
        forecast_days = ((data.get("forecast") or {}).get("forecastday") or [])

        forecast = []
        for d in forecast_days[:days]:
            day = d.get("day") or {}
            condition = day.get("condition") or {}
            forecast.append(
                {
                    "date": d.get("date"),
                    "avg_temp_c": day.get("avgtemp_c"),
                    "max_temp_c": day.get("maxtemp_c"),
                    "min_temp_c": day.get("mintemp_c"),
                    "condition": condition.get("text", ""),
                    "chance_of_rain": day.get("daily_chance_of_rain"),
                }
            )

        return {
            "status": "ok",
            "source": "weatherapi",
            "location": {
                "name": location.get("name", ""),
                "region": location.get("region", ""),
                "country": location.get("country", ""),
                "localtime": location.get("localtime", ""),
            },
            "current": {
                "temp_c": current.get("temp_c"),
                "feelslike_c": current.get("feelslike_c"),
                "humidity": current.get("humidity"),
                "wind_kph": current.get("wind_kph"),
                "condition": (current.get("condition") or {}).get("text", ""),
            },
            "forecast": forecast,
        }

    registry.register(
        ToolMetadata(
            name="weather.get",
            version="1.0",
            risk_level="low",
            tags=["weather", "forecast", "temperature", "rain"],
            routing_summary="Get weather and forecast for a location using configured weather provider.",
            invocation_summary="weather.get(location, days=1) returns current conditions and forecast.",
            full_schema={
                "type": "object",
                "properties": {
                    "location": {"type": "string", "minLength": 1},
                    "days": {"type": "integer", "minimum": 1, "maximum": 3},
                    "query": {"type": "string"},
                },
                "required": ["location"],
            },
            examples=["weather.get(location='Bengaluru', days=1)"],
            timeout_sec=timeout_seconds,
            idempotent=True,
            permission_required="none",
        ),
        weather_get,
    )
