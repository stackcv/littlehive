# PyPI Release (CI/CD via GitHub Actions)

## Workflows

- **CI** (`.github/workflows/ci.yml`): Runs on every push/PR — lints, builds, CLI smoke test, version consistency check.
- **Publish** (`.github/workflows/publish.yml`): Triggered by `v*` tags — builds, verifies version match, publishes to PyPI, creates GitHub Release with auto-generated notes.

## One-time Setup

### A. PyPI Trusted Publisher
In PyPI project settings, add a Trusted Publisher:
- Owner/repo: `stackcv/littlehive`
- Workflow file: `publish.yml`
- Environment name: `pypi`

Optional for TestPyPI:
- Add matching trusted publisher in TestPyPI
- Environment name: `testpypi`

### B. GitHub Environments
In GitHub repo settings → Environments:
- Create environment: `pypi`
- Create environment: `testpypi` (optional)

No PyPI API token secret is needed when using Trusted Publisher.

## Release Flow

### Automated (recommended)

```bash
./scripts/release.sh 0.7.0
```

The script:
1. Validates version format (X.Y.Z)
2. Checks for uncommitted changes
3. Updates `pyproject.toml` and `src/littlehive/__init__.py`
4. Builds package and runs `twine check`
5. Commits, tags `v0.7.0`, and pushes

GitHub Actions then:
1. Runs CI (lint, build, version check)
2. Verifies tag matches `pyproject.toml` version
3. Publishes to PyPI via Trusted Publisher
4. Creates GitHub Release with changelog and attached artifacts

### Manual Alternative

```bash
# 1. Update versions
# Edit pyproject.toml version = "0.7.0"
# Edit src/littlehive/__init__.py __version__ = "0.7.0"

# 2. Commit and push
git add pyproject.toml src/littlehive/__init__.py
git commit -m "release: v0.7.0"
git push

# 3. Create and push tag
git tag v0.7.0
git push origin v0.7.0
```

### Manual Dispatch
Use GitHub Actions → `publish` → Run workflow:
- `repository = pypi` for production
- `repository = testpypi` for test index

## Local Preflight

```bash
python -m build
twine check dist/*
```

## Notes
- The publish workflow enforces tag/version consistency — `vX.Y.Z` tag must match `project.version`.
- CI checks that `pyproject.toml` and `__init__.py` versions are in sync.
- If publish fails with trust errors, verify Trusted Publisher mapping in PyPI matches repo/workflow/environment exactly.
