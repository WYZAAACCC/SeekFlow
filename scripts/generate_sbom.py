#!/usr/bin/env python3
"""Generate a CycloneDX-compatible SBOM for SeekFlow.

Usage: python scripts/generate_sbom.py [--output sbom.json]

Requires: pip install cyclonedx-bom (optional — falls back to basic JSON)
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def generate_basic_sbom() -> dict:
    """Generate a basic SBOM from pip freeze output."""
    result = subprocess.run(
        [sys.executable, "-m", "pip", "freeze", "--path", str(ROOT / "src")],
        capture_output=True, text=True,
    )

    packages = []
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-e"):
            continue
        if "==" in line:
            name, version = line.split("==", 1)
        elif "@" in line:
            name = line.split("@")[0].strip()
            version = "unknown"
        else:
            name = line
            version = "unknown"

        packages.append({
            "name": name,
            "version": version,
            "purl": f"pkg:pypi/{name}@{version}",
        })

    # Add seekflow itself
    try:
        pyproject = json.loads(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8")
            if False else "{}"  # TOML needs tomli
        )
    except Exception:
        import tomllib if sys.version_info >= (3, 11) else None
        if sys.version_info >= (3, 11):
            import tomllib
            pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        else:
            pyproject = {}

    version = pyproject.get("project", {}).get("version", "0.3.7")

    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{_random_uuid()}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "library",
                "name": "seekflow",
                "version": version,
                "purl": f"pkg:pypi/seekflow@{version}",
            }
        },
        "components": [
            {
                "type": "library",
                "name": p["name"],
                "version": p["version"],
                "purl": p["purl"],
            }
            for p in sorted(packages, key=lambda x: x["name"])
        ],
    }

    return sbom


def _random_uuid() -> str:
    import uuid
    return uuid.uuid4().hex


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate SeekFlow SBOM")
    parser.add_argument("--output", "-o", default=None, help="Output file (stdout if omitted)")
    args = parser.parse_args()

    sbom = generate_basic_sbom()
    output = json.dumps(sbom, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"SBOM written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
