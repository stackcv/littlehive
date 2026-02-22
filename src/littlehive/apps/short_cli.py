from __future__ import annotations

import argparse
import sys

from littlehive.apps import reset as reset_app
from littlehive.apps import run as run_app


def main() -> int:
    parser = argparse.ArgumentParser(prog="lhive", description="LittleHive short command")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run LittleHive")
    run_parser.add_argument("args", nargs=argparse.REMAINDER)

    reset_parser = subparsers.add_parser("reset", help="Reset local LittleHive files")
    reset_parser.add_argument("args", nargs=argparse.REMAINDER)

    diag_parser = subparsers.add_parser("diag", help="Run diagnostics")
    diag_parser.add_argument("args", nargs=argparse.REMAINDER)

    args = parser.parse_args()

    if args.command == "run":
        sys.argv = ["littlehive-run", *args.args]
        return run_app.main()

    if args.command == "reset":
        sys.argv = ["littlehive-reset", *args.args]
        return reset_app.main()

    if args.command == "diag":
        from littlehive.apps import diagnostics_cli as diag_app

        sys.argv = ["littlehive-diag", *args.args]
        return diag_app.main()

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
