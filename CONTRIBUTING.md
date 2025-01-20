

```markdown:CONTRIBUTING.md
# Contributing to jobsparser

## Publishing to PyPI

1. Install build tools:
```bash
pip install build twine
```

2. Build the package:
```bash
python -m build
```
This creates distribution files in the `dist/` directory.

3. Upload to PyPI:
```bash
python -m twine upload dist/*
```

You'll need:
- A PyPI account
- An API token from PyPI (create at https://pypi.org/manage/account/token/)

### Authentication

Best practice is to store credentials in `~/.pypirc`:
```ini
[pypi]
username = __token__
password = your-api-token-here
```

Alternatively, enter credentials when prompted by twine.

### Version Updates

1. Update version in `pyproject.toml`
2. Build and upload as above
```
