"""Verify that pyproject.toml, seekflow.__version__, and README are aligned."""
import pathlib
import re
import sys

import seekflow


def test_version_consistency():
    if sys.version_info >= (3, 11):
        import tomllib
        pyproject = pathlib.Path(__file__).parent.parent / "pyproject.toml"
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        project_version = data["project"]["version"]
        assert seekflow.__version__ == project_version, (
            f"seekflow.__version__={seekflow.__version__} != "
            f"pyproject.toml={project_version}"
        )

    readme = pathlib.Path(__file__).parent.parent / "README.md"
    text = readme.read_text(encoding="utf-8")
    match = re.search(r"SeekFlow v(\d+\.\d+\.\d+)", text)
    if match:
        readme_version = match.group(1)
        assert seekflow.__version__ == readme_version, (
            f"seekflow.__version__={seekflow.__version__} != "
            f"README.md v{readme_version}"
        )
