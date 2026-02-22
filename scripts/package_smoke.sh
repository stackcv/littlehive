#!/usr/bin/env bash
set -euo pipefail

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

littlehive-onboard --help >/dev/null
littlehive-api --help >/dev/null
littlehive-telegram --help >/dev/null
littlehive-diag --help >/dev/null
littlehive-dashboard --help >/dev/null
littlehive-supervisor --help >/dev/null

littlehive-diag --validate-config || true
littlehive-dashboard --smoke >/dev/null

python -m build >/dev/null
twine check dist/* >/dev/null

echo "package-smoke-ok"
