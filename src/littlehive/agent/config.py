import os
import json

from littlehive.agent.logger_setup import logger
from littlehive.agent.paths import CONFIG_PATH

DEFAULT_CONFIG = {
    "onboarded": False,
    "telegram_bot_token": "",
    "proactive_polling_minutes": 30,
    "fast_polling_seconds": 30,
    "agent_name": "Roxy",
    "agent_title": "Executive Staff",
    "user_name": "John Doe",
    "home_location": "",
    "temperature": 0.1,
    "model_path": "mlx-community/mistralai_Ministral-3-14B-Instruct-2512-MLX-MXFP4",
    "dnd_start": 23,
    "dnd_end": 7,
}

_cached_config = None
_cached_mtime = 0.0


def get_config():
    """
    Returns the current config dict. Uses mtime-based caching so the file is
    only re-read from disk when it has actually been modified — giving hot-reload
    semantics without constant I/O.
    """
    global _cached_config, _cached_mtime

    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        _cached_config = dict(DEFAULT_CONFIG)
        _cached_mtime = os.path.getmtime(CONFIG_PATH)
        return _cached_config

    current_mtime = os.path.getmtime(CONFIG_PATH)
    if _cached_config is not None and current_mtime == _cached_mtime:
        return _cached_config

    try:
        with open(CONFIG_PATH, "r") as f:
            user_config = json.load(f)
        updated = False
        for k, v in DEFAULT_CONFIG.items():
            if k not in user_config:
                user_config[k] = v
                updated = True
        if updated:
            with open(CONFIG_PATH, "w") as f:
                json.dump(user_config, f, indent=4)
            current_mtime = os.path.getmtime(CONFIG_PATH)
        _cached_config = user_config
        _cached_mtime = current_mtime
        return _cached_config
    except Exception:
        return dict(DEFAULT_CONFIG)


def save_config_value(key, value):
    """Persist a single key-value pair to the config file and update the cache."""
    global _cached_config, _cached_mtime
    try:
        with open(CONFIG_PATH, "r") as f:
            config = json.load(f)
        config[key] = value
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=4)
        _cached_config = config
        _cached_mtime = os.path.getmtime(CONFIG_PATH)
    except Exception as e:
        logger.error(f"Failed to save config value '{key}': {e}")
