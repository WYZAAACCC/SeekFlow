"""Manifest loader — load and validate ToolManifest from YAML/JSON/dict.

The loader is the entry point for registering external tools. It:
1. Parses the manifest file/bytes
2. Validates the manifest structure via Pydantic
3. Closes the input/output schemas (additionalProperties=False)
4. Returns a validated ToolManifest ready for verification and compilation
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from seekflow.tools.manifest import ToolManifest
from seekflow.tools.validation import close_object_schema


class ManifestLoadError(ValueError):
    """Raised when a manifest cannot be loaded or validated."""


def load_manifest_from_dict(data: dict[str, Any]) -> ToolManifest:
    """Load and validate a manifest from a dict."""
    try:
        manifest = ToolManifest.model_validate(data)
    except Exception as e:
        raise ManifestLoadError(f"Invalid manifest: {e}") from e

    # Close schemas: block hallucinated extra arguments
    if manifest.input_schema:
        manifest.input_schema = close_object_schema(manifest.input_schema)
    if manifest.output_schema:
        manifest.output_schema = close_object_schema(manifest.output_schema)

    return manifest


def load_manifest_from_yaml(path: str | Path) -> ToolManifest:
    """Load a manifest from a YAML file."""
    path = Path(path)
    if not path.exists():
        raise ManifestLoadError(f"Manifest file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ManifestLoadError(f"YAML parse error in {path}: {e}") from e
    if not isinstance(data, dict):
        raise ManifestLoadError(f"Manifest must be a mapping, got {type(data).__name__}")
    return load_manifest_from_dict(data)


def load_manifest_from_json(path: str | Path) -> ToolManifest:
    """Load a manifest from a JSON file."""
    path = Path(path)
    if not path.exists():
        raise ManifestLoadError(f"Manifest file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ManifestLoadError(f"JSON parse error in {path}: {e}") from e
    if not isinstance(data, dict):
        raise ManifestLoadError(f"Manifest must be a JSON object, got {type(data).__name__}")
    return load_manifest_from_dict(data)


def load_manifest(path: str | Path) -> ToolManifest:
    """Load a manifest, auto-detecting format from file extension."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        return load_manifest_from_yaml(path)
    elif suffix == ".json":
        return load_manifest_from_json(path)
    else:
        raise ManifestLoadError(
            f"Unknown manifest format: {suffix}. Expected .yaml, .yml, or .json"
        )
