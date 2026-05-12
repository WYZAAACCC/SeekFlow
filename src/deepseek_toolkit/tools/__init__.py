"""Tool definition and schema generation."""
from deepseek_toolkit.tools.decorator import tool
from deepseek_toolkit.tools.registry import ToolRegistry
from deepseek_toolkit.tools.schema import function_to_parameters

__all__ = ["tool", "ToolRegistry", "function_to_parameters"]
