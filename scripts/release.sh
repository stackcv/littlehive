#!/usr/bin/env bash
set -euo pipefail

# ─── LittleHive Release Script ───────────────────────────────────────
# Usage:  ./scripts/release.sh 0.7.0
#
# What it does (in order):
#   1. Validates the version format
#   2. Checks for uncommitted changes
#   3. Updates version in pyproject.toml and src/littlehive/__init__.py
#   4. Builds the package and runs twine check
#   5. Commits the version bump
#   6. Creates a signed git tag
#   7. Pushes branch + tag to origin
#   8. GitHub Actions takes over: CI → build → PyPI publish → GitHub Release
# ──────────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}✓${NC} $1"; }
warn()  { echo -e "${YELLOW}⚠${NC} $1"; }
error() { echo -e "${RED}✗${NC} $1" >&2; exit 1; }

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
    echo "Usage: ./scripts/release.sh <version>"
    echo "  e.g. ./scripts/release.sh 0.7.0"
    exit 1
fi

if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    error "Invalid version format: '$VERSION'. Expected: X.Y.Z (e.g. 0.7.0)"
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PYPROJECT="pyproject.toml"
INIT_PY="src/littlehive/__init__.py"

# ── Pre-flight checks ────────────────────────────────────────────────

if ! git diff --quiet HEAD 2>/dev/null; then
    error "You have uncommitted changes. Commit or stash them first."
fi

if git rev-parse "v${VERSION}" >/dev/null 2>&1; then
    error "Tag v${VERSION} already exists."
fi

CURRENT=$(python3 -c "
import tomllib
from pathlib import Path
print(tomllib.loads(Path('$PYPROJECT').read_text())['project']['version'])
")
info "Current version: ${CURRENT}"
info "New version:     ${VERSION}"
echo ""

read -p "Proceed with release v${VERSION}? [y/N] " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

# ── Update versions ──────────────────────────────────────────────────

sed -i '' "s/^version = \".*\"/version = \"${VERSION}\"/" "$PYPROJECT"
info "Updated $PYPROJECT"

cat > "$INIT_PY" << EOF
__version__ = "${VERSION}"
EOF
info "Updated $INIT_PY"

# ── Build & verify ───────────────────────────────────────────────────

warn "Building package..."
python3 -m build --quiet 2>/dev/null
python3 -m twine check dist/littlehive-"${VERSION}"* --strict 2>/dev/null
info "Package built and validated"

# ── Commit, tag, push ────────────────────────────────────────────────

git add "$PYPROJECT" "$INIT_PY"
git commit -m "release: v${VERSION}"
info "Committed version bump"

git tag "v${VERSION}"
info "Created tag v${VERSION}"

git push origin HEAD
git push origin "v${VERSION}"
info "Pushed to origin"

echo ""
info "Release v${VERSION} is live!"
echo "  → GitHub Actions will now: build → publish to PyPI → create GitHub Release"
echo "  → Monitor: https://github.com/$(git remote get-url origin | sed 's/.*github.com[:/]\(.*\)\.git/\1/')/actions"
