# PyPI Release Prep (Manual)

## Build artifacts
```bash
python -m build
```

## Validate metadata
```bash
twine check dist/*
```

## Optional TestPyPI publish
```bash
twine upload --repository testpypi dist/*
```

## Production publish
```bash
twine upload dist/*
```

Notes:
- Use API tokens from your PyPI account.
- Confirm `README.md` renders correctly on PyPI.
- Ensure tagged release matches package version.
