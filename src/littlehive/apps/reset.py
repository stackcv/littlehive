from __future__ import annotations

from pathlib import Path

from littlehive.cli import base_parser
from littlehive.core.config.loader import load_app_config


def _resolve_config_path(cli_config: str | None) -> Path:
    if cli_config:
        return Path(cli_config)
    return Path("config/instance.yaml")


def _sqlite_path_from_url(url: str) -> Path | None:
    if not url.startswith("sqlite:///"):
        return None
    raw = url[len("sqlite:///") :]
    if not raw:
        return None
    return Path(raw)


def _confirm(prompt: str) -> bool:
    value = input(prompt).strip().lower()
    return value in {"y", "yes"}


def main() -> int:
    parser = base_parser("littlehive-reset", "Reset local LittleHive runtime files")
    parser.add_argument("--config", default=None, help="Config file path")
    parser.add_argument("--env-file", default=".env", help="Env file path")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    config_path = _resolve_config_path(args.config)
    env_file = Path(args.env_file)

    paths: list[Path] = [config_path, env_file]

    db_path = Path("littlehive.db")
    if config_path.exists():
        try:
            cfg = load_app_config(instance_path=config_path)
            resolved = _sqlite_path_from_url(cfg.database.url)
            if resolved is not None:
                db_path = resolved
        except Exception:
            pass
    paths.append(db_path)

    unique_paths: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        rp = path.resolve()
        if rp not in seen:
            seen.add(rp)
            unique_paths.append(path)

    print("Reset will remove these files if present:")
    for path in unique_paths:
        print(f"- {path}")

    if not args.yes and not _confirm("Proceed? [y/N]: "):
        print("Reset cancelled.")
        return 1

    removed = 0
    for path in unique_paths:
        if path.exists() and path.is_file():
            path.unlink()
            removed += 1
            print(f"removed: {path}")
        else:
            print(f"skip (not found): {path}")

    if config_path.parent.exists() and config_path.parent.is_dir():
        try:
            config_path.parent.rmdir()
            print(f"removed empty dir: {config_path.parent}")
        except OSError:
            pass

    print(f"Reset complete. removed_files={removed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
