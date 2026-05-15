"""Tool registry for managing registered tools."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from seekflow.errors import ToolSchemaError
from seekflow.types import ToolDefinition

if TYPE_CHECKING:
    from seekflow.tools.manifest import ToolManifest


class ToolRegistry:
    """Registry for local and MCP tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: Callable | ToolDefinition) -> ToolDefinition:
        """Register a tool. Accepts either a callable (auto-wrapped with @tool)
        or a pre-built ToolDefinition."""
        from seekflow.tools.decorator import _make_tool_definition

        if not isinstance(tool, ToolDefinition):
            td = _make_tool_definition(tool)
        else:
            td = tool

        if td.name in self._tools:
            raise ToolSchemaError(f"Tool '{td.name}' is already registered")
        self._tools[td.name] = td
        return td

    def register_from_manifest(
        self,
        manifest: "ToolManifest",
        *,
        strict: bool = True,
    ) -> ToolDefinition:
        """Register a tool from a ToolManifest.

        Pipeline: verify → compile → lint → register.

        For source="local": the manifest must have func set via entrypoint.
        For source!="local": func is None — execution goes through
        ExternalToolRunner (Phase C).
        """
        from seekflow.tools.manifest_verify import verify_manifest, compute_manifest_digest
        from seekflow.tools.policy_compiler import compile_policy
        from seekflow.tools.policy_linter import lint_policy, has_errors

        # 1. Verify integrity
        verify_manifest(manifest, strict=strict)

        # 2. Compile into ToolPolicy
        policy = compile_policy(manifest)

        # 3. Lint the compiled policy
        issues = lint_policy(policy, source=manifest.source)
        if has_errors(issues):
            error_msgs = "; ".join(
                f"[{i.code}] {i.message}" for i in issues if i.severity == "error"
            )
            raise ToolSchemaError(
                f"Tool '{manifest.name}' failed policy lint: {error_msgs}"
            )

        # 4. Build ToolDefinition
        td = ToolDefinition(
            name=manifest.name,
            description=manifest.description,
            parameters=manifest.input_schema,
            func=None,  # external tools have no Python callable
            source=manifest.source,
            metadata={
                "manifest_version": manifest.version,
                "manifest_digest": compute_manifest_digest(manifest),
                "manifest_source": manifest.source,
                "_manifest_data": manifest.model_dump(mode="json"),
                "lint_warnings": [
                    f"[{i.code}] {i.message}"
                    for i in issues if i.severity == "warning"
                ],
            },
            policy=policy,
        )

        return self.register(td)

    def register_from_manifest_file(
        self,
        path: str | Path,
        *,
        strict: bool = True,
    ) -> ToolDefinition:
        """Load a manifest from a file and register it."""
        from seekflow.tools.manifest_loader import load_manifest

        manifest = load_manifest(path)
        return self.register_from_manifest(manifest, strict=strict)

    def get(self, name: str) -> ToolDefinition:
        """Get a tool by name."""
        return self._tools[name]

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def list(self) -> list[ToolDefinition]:
        """List all registered tools."""
        return list(self._tools.values())

    def unregister(self, name: str) -> bool:
        """Remove a tool by name. Returns True if the tool was removed."""
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def get_by_source(self, source: str) -> list[ToolDefinition]:
        """List all tools from a given source ('local' or MCP server name)."""
        return [td for td in self._tools.values() if td.source == source]

    def to_deepseek_tools(self, strict: bool = False) -> list[dict]:
        """Export all tools in DeepSeek-compatible format.

        Tools are sorted by name for deterministic JSON serialization.
        This is CRITICAL for prompt cache stability — non-deterministic
        key ordering invalidates the DeepSeek byte-prefix cache.

        When *strict* is True, applies the DeepSeek Strict Schema Compiler
        and sets ``strict: true`` on each function.
        """
        if len(self._tools) > 128:
            raise ValueError("DeepSeek supports at most 128 tools")

        compiler = None
        if strict:
            from seekflow.deepseek.strict_schema import DeepSeekStrictSchemaCompiler
            compiler = DeepSeekStrictSchemaCompiler()

        import re as _re_name
        _NAME_RE = _re_name.compile(r"^[A-Za-z0-9_-]{1,64}$")

        tools = []
        for td in sorted(self._tools.values(), key=lambda t: t.name):
            if len(td.name) > 64:
                raise ValueError(f"Tool name too long for DeepSeek: {td.name}")
            if not _NAME_RE.fullmatch(td.name):
                raise ToolSchemaError(
                    f"Tool name '{td.name}' invalid for DeepSeek. "
                    "Use only letters, digits, underscores, and hyphens."
                )

            parameters = td.parameters
            if compiler is not None:
                parameters = compiler.compile(parameters)

            function = {
                "name": td.name,
                "description": td.description,
                "parameters": parameters,
            }
            if strict:
                function["strict"] = True

            tools.append({"type": "function", "function": function})
        return tools
