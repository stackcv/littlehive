from __future__ import annotations

from littlehive.cli import base_parser


def main() -> int:
    parser = base_parser("littlehive-telegram", "LittleHive Telegram worker stub")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    parser.parse_args()
    print("telegram-worker-stub-ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
