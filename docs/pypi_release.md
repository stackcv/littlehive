# PyPI Release (CI/CD via GitHub Actions)

This repository uses dedicated release workflows:
- CI (tests/lint/build smoke): `.github/workflows/ci.yml`
- CD (publish package): `.github/workflows/publish.yml`
- GitHub Release (notes + attached dist artifacts): `.github/workflows/release.yml`

## 1) One-time setup

### A. Create the package on PyPI
1. Sign in to PyPI.
2. Create the project by doing one manual upload once, or by first publish via trusted publisher (if allowed by your account flow).

### B. Configure Trusted Publisher (recommended)
In PyPI project settings, add a Trusted Publisher for this GitHub repo/workflow:
- Owner/repo: `stackcv/littlehive`
- Workflow file: `publish.yml`
- Environment name: `pypi`

Optional for TestPyPI:
- Add matching trusted publisher in TestPyPI
- Environment name: `testpypi`

### C. Configure GitHub Environments
In GitHub repo settings -> Environments:
- Create environment: `pypi`
- Create environment: `testpypi` (optional)
- Add protection rules if desired (required reviewers, branch/tag rules)

No PyPI API token secret is needed when using Trusted Publisher.

## 2) Normal release flow

1. Bump version in `pyproject.toml` and `src/littlehive/__init__.py`.
2. Commit and push.
3. Create and push tag matching version:

```bash
git tag v0.5.1
git push origin v0.5.1
```

4. GitHub Actions `publish` workflow builds, checks, and uploads to PyPI.
5. GitHub Actions `release` workflow creates a GitHub Release from the same tag and attaches wheel/sdist artifacts.

## 3) Manual publish options

Use GitHub Actions -> `publish` -> Run workflow:
- `repository = pypi` for production
- `repository = testpypi` for test index

## 4) Local preflight (recommended)

```bash
pip install -e ".[dev,telegram,ui]"
python -m build
twine check dist/*
```

## 5) Install examples

```bash
pip install littlehive
pip install "littlehive[full]"
```

## Notes
- The publish workflow enforces tag/version consistency (`vX.Y.Z` tag must match `project.version`).
- If publish fails with trust errors, verify Trusted Publisher mapping in PyPI/TestPyPI matches repo/workflow/environment exactly.
