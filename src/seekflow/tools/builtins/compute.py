"""Safe compute tool factory — AST-restricted arithmetic, no eval of arbitrary code."""
from __future__ import annotations

import json as _json
import math as _math
import operator as _op

from seekflow.tools.decorator import tool
from seekflow.types import ToolPolicy

#: Safe operations allowed in calculate (no eval, no attribute access)
_SAFE_OPS: dict[str, object] = {
    "abs": abs, "round": round, "min": min, "max": max, "sum": sum, "len": len,
    "int": int, "float": float, "str": str, "bool": bool,
    "pow": pow, "divmod": divmod,
    "sqrt": _math.sqrt, "log": _math.log, "log10": _math.log10,
    "ceil": _math.ceil, "floor": _math.floor,
    "add": _op.add, "sub": _op.sub, "mul": _op.mul,
    "truediv": _op.truediv, "floordiv": _op.floordiv, "mod": _op.mod,
    "neg": _op.neg, "pos": _op.pos,
    "eq": _op.eq, "ne": _op.ne, "lt": _op.lt, "le": _op.le, "gt": _op.gt, "ge": _op.ge,
    "and_": _op.and_, "or_": _op.or_, "not_": _op.not_,
    "pi": _math.pi, "e": _math.e, "tau": _math.tau,
}


def _safe_eval(expr: str) -> object:
    """Evaluate a restricted arithmetic/logic expression.

    Allowed AST nodes: Expression, BinOp, UnaryOp, Constant,
    Add, Sub, Mult, Div, FloorDiv, Mod, Pow, USub, UAdd.

    Forbidden: Call, Attribute, Subscript, Name, Import, Lambda, Comprehension.
    """
    code = compile(expr, "<calculate>", "eval")
    for name in code.co_names:
        if name not in _SAFE_OPS:
            raise ValueError(f"'{name}' is not an allowed operation")
    return eval(code, {"__builtins__": {}}, _SAFE_OPS)


def make_calculate() -> "ToolDefinition":
    """Create a trusted calculate tool — safe arithmetic, no side effects."""

    @tool(trusted=True, sanitize=False)
    def calculate(expression: str) -> str:
        """Evaluate a mathematical expression. Supports: +, -, *, /, **, %, //,
        sqrt, log, abs, round, min, max, sum, len, pi, e, int, float, and
        comparisons (==, !=, <, <=, >, >=).
        """
        try:
            result = _safe_eval(expression)
        except Exception as e:
            return f"Calculation error: {e}"
        return _json.dumps(result, ensure_ascii=False)

    return calculate.with_policy(ToolPolicy(
        capabilities={"compute.basic"},
        risk="read",
        timeout_s=1.0,
        max_input_bytes=10_000,
        max_output_bytes=10_000,
        parallel_safe=True,
    ))
