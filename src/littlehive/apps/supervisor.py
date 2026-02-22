from __future__ import annotations

import signal
import time

from littlehive.cli import base_parser
from littlehive.core.config.loader import load_app_config
from littlehive.core.telemetry.logging import get_logger


def main() -> int:
    parser = base_parser("littlehive-supervisor", "LittleHive supervisor skeleton")
    parser.add_argument("--config", default=None, help="Config file path")
    parser.add_argument("--once", action="store_true", help="Run one heartbeat and exit")
    parser.add_argument("--interval", type=int, default=5, help="Heartbeat interval seconds")
    args = parser.parse_args()

    cfg = load_app_config(instance_path=args.config)
    logger = get_logger("littlehive.supervisor")

    running = True

    def _stop(_sig, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    def heartbeat() -> None:
        logger.info(
            "supervisor_heartbeat",
            safe_mode=cfg.runtime.safe_mode,
            interval_seconds=args.interval,
            status="ok",
        )
        print("supervisor-heartbeat-ok")

    if args.once:
        heartbeat()
        return 0

    while running:
        heartbeat()
        time.sleep(max(1, args.interval))

    print("supervisor-shutdown")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
