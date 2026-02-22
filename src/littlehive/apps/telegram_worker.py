from __future__ import annotations

import asyncio
import os

from littlehive.channels.telegram.adapter import build_telegram_runtime
from littlehive.channels.telegram.handlers import TelegramHandlers
from littlehive.cli import base_parser
from littlehive.core.config.loader import load_app_config


def _require_telegram_lib():
    from telegram.ext import Application, MessageHandler, filters  # noqa: PLC0415

    return Application, MessageHandler, filters


async def _run_polling(config_path: str | None) -> int:
    cfg = load_app_config(instance_path=config_path)
    if not cfg.channels.telegram.enabled:
        print("telegram channel disabled in config")
        return 1

    token = os.getenv(cfg.channels.telegram.token_env, "")
    if not token:
        print(f"missing token in env: {cfg.channels.telegram.token_env}")
        return 1

    runtime = build_telegram_runtime(config_path=config_path)
    handlers = TelegramHandlers(runtime)

    Application, MessageHandler, filters = _require_telegram_lib()
    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_update))
    app.add_handler(MessageHandler(filters.COMMAND, handlers.handle_update))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(timeout=cfg.channels.telegram.polling_timeout_seconds)
    print("telegram-worker-running")
    try:
        while True:
            await asyncio.sleep(1)
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


def main() -> int:
    parser = base_parser("littlehive-telegram", "LittleHive Telegram worker")
    parser.add_argument("--config", default=None, help="Config file path")
    parser.add_argument("--once", action="store_true", help="Run startup checks and exit")
    args = parser.parse_args()

    cfg = load_app_config(instance_path=args.config)
    if args.once:
        runtime = build_telegram_runtime(config_path=args.config)
        print(
            f"telegram-worker-ready enabled={cfg.channels.telegram.enabled} "
            f"allowed_users={len(runtime.auth.allowed_user_ids)}"
        )
        return 0

    return asyncio.run(_run_polling(args.config))


if __name__ == "__main__":
    raise SystemExit(main())
