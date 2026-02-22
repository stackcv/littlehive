from __future__ import annotations

from littlehive.cli import base_parser
from littlehive.core.config.loader import load_app_config


def main() -> int:
    parser = base_parser("littlehive-onboard", "LittleHive onboarding CLI")
    parser.add_argument("--config", default=None, help="Config file path")
    parser.parse_args()
    cfg = load_app_config()
    print(f"onboard-ready instance={cfg.instance.name} env={cfg.environment}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
