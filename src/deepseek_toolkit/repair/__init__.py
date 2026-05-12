"""Tool argument repair and coercion."""
from deepseek_toolkit.repair.coercion import coerce_arguments
from deepseek_toolkit.repair.json_repair import JsonRepairResult, repair_json_arguments

__all__ = ["repair_json_arguments", "JsonRepairResult", "coerce_arguments"]
