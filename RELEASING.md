# Release Process

## Prerequisites

1. PyPI project configured for [Trusted Publishing](https://docs.pypi.org/trusted-publists/) with this GitHub repo.
2. GitHub Environment `pypi` created with trusted-publisher protection.

## Steps

```bash
# 1. Bump version
#    Edit pyproject.toml: version = "X.Y.Z"
#    Edit src/seekflow/__init__.py: __version__ = "X.Y.Z"

# 2. Tag
git tag -a vX.Y.Z -m "vX.Y.Z: <summary>"
git push origin vX.Y.Z

# 3. Create GitHub Release
gh release create vX.Y.Z --title "vX.Y.Z" --notes "<release notes>"

# 4. GitHub Actions publishes to PyPI automatically via Trusted Publishing
#    (triggered by the release event in .github/workflows/publish.yml)

# 5. Verify
pip install seekflow==X.Y.Z
python -c "from seekflow import tool; print('OK')"
```

## Trusted Publishing Setup (one-time)

1. Go to PyPI project settings → Publishing → Add Trusted Publisher
2. Owner: `WYZAAACCC`, Repository: `SeekFlow`, Workflow: `publish.yml`
3. Create GitHub Environment `pypi` in repo Settings → Environments
4. Add protection rule: required reviewers (optional)
