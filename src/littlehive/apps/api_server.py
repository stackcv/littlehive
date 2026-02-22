from __future__ import annotations

from fastapi import FastAPI

from littlehive.cli import base_parser

app = FastAPI(title="LittleHive API", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


def main() -> int:
    parser = base_parser("littlehive-api", "LittleHive API stub")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.parse_args()
    print("api-stub-ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
