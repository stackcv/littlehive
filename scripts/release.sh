#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/release.sh <version>

Example:
  scripts/release.sh 0.5.3

What it does:
  1) Validates clean git state and version format
  2) Updates version in pyproject.toml and src/littlehive/__init__.py
  3) Builds package and runs twine metadata check
  4) Commits version bump
  5) Creates git tag v<version>
  6) Pushes current branch and tag to origin

Note:
  PyPI publish is handled by .github/workflows/publish.yml after tag push.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -ne 1 ]]; then
  usage
  exit $(( $# == 1 ? 0 : 1 ))
fi

NEW_VERSION="$1"
if ! [[ "$NEW_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "error: version must look like X.Y.Z (got: $NEW_VERSION)" >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "error: not inside a git repository" >&2
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "error: working tree is not clean. commit/stash changes first." >&2
  git status --short
  exit 1
fi

if git rev-parse "v$NEW_VERSION" >/dev/null 2>&1; then
  echo "error: local tag v$NEW_VERSION already exists" >&2
  exit 1
fi

if git ls-remote --exit-code --tags origin "refs/tags/v$NEW_VERSION" >/dev/null 2>&1; then
  echo "error: remote tag v$NEW_VERSION already exists on origin" >&2
  exit 1
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
CURRENT_VERSION="$(python - <<'PY'
import tomllib
from pathlib import Path

p = Path("pyproject.toml")
print(tomllib.loads(p.read_text(encoding="utf-8"))["project"]["version"])
PY
)"

if [[ "$CURRENT_VERSION" == "$NEW_VERSION" ]]; then
  echo "error: version is already $NEW_VERSION" >&2
  exit 1
fi

echo "Updating version: $CURRENT_VERSION -> $NEW_VERSION"
perl -i -pe 's/^version = ".*"/version = "'"$NEW_VERSION"'"/' pyproject.toml
perl -i -pe 's/^__version__ = ".*"/__version__ = "'"$NEW_VERSION"'"/' src/littlehive/__init__.py

echo "Running packaging checks"
rm -rf dist build *.egg-info
python -m build
python -m twine check dist/*

echo "Committing and tagging"
git add pyproject.toml src/littlehive/__init__.py
git commit -m "Bump version to $NEW_VERSION"
git tag "v$NEW_VERSION"

echo "Pushing branch and tag"
git push origin "$CURRENT_BRANCH"
git push origin "v$NEW_VERSION"

echo "Release kicked off for v$NEW_VERSION"
echo "- PyPI publish workflow: .github/workflows/publish.yml"
echo "- GitHub Release workflow: .github/workflows/release.yml"
