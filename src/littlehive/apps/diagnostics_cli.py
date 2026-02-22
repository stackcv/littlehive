from __future__ import annotations

from littlehive.cli import base_parser
from littlehive.core.orchestrator.task_loop import run_dummy_task_pipeline


def main() -> int:
    parser = base_parser("littlehive-diag", "LittleHive diagnostics CLI")
    parser.add_argument("--dummy-task", action="store_true", help="Run dummy task pipeline")
    args = parser.parse_args()
    if args.dummy_task:
        result = run_dummy_task_pipeline()
        print(f"diag-dummy-result={result.status}")
    else:
        print("diag-ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
