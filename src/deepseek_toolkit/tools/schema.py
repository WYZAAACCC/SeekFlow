"""Convert Python function signatures to JSON Schema."""
import enum
import inspect
from typing import Any, Literal, Optional, Union, get_args, get_origin

from pydantic import BaseModel

_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    dict: "object",
    list: "array",
    set: "array",
}


def _python_type_to_json_schema(py_type: type) -> dict[str, Any]:
    """Convert a Python type annotation to a JSON Schema property."""
    origin = get_origin(py_type)
    args = get_args(py_type)

    # Handle list[X], set[X]
    if origin in (list, set):
        item_type = args[0] if args else str
        schema = {
            "type": "array",
            "items": _python_type_to_json_schema(item_type),
        }
        if origin is set:
            schema["uniqueItems"] = True
        return schema

    # Handle tuple[X, Y, ...]
    if origin is tuple:
        if args:
            return {
                "type": "array",
                "prefixItems": [_python_type_to_json_schema(a) for a in args],
            }
        return {"type": "array"}

    # Handle Union[X, Y] (non-Optional — produces anyOf)
    if origin is Union:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _python_type_to_json_schema(non_none[0])
        return {"anyOf": [_python_type_to_json_schema(a) for a in non_none]}

    # Handle Literal["a", "b"]
    if origin is Literal:
        return {"enum": list(args)}

    # Handle Enum subclasses
    if isinstance(py_type, type) and issubclass(py_type, enum.Enum):
        values = [e.value for e in py_type]
        # Infer JSON type from first enum value
        val_types = {type(v) for v in values}
        if val_types <= {str}:
            return {"type": "string", "enum": values}
        elif val_types <= {int}:
            return {"type": "integer", "enum": values}
        else:
            return {"enum": values}

    # Handle Pydantic models
    if isinstance(py_type, type) and issubclass(py_type, BaseModel):
        return _pydantic_model_to_schema(py_type)

    # Handle basic types
    json_type = _TYPE_MAP.get(py_type)
    if json_type:
        return {"type": json_type}

    return {"type": "string"}


def _pydantic_model_to_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Convert a Pydantic model to a JSON Schema object."""
    properties = {}
    required = []
    for field_name, field_info in model.model_fields.items():
        annotation = field_info.annotation
        if annotation is not None:
            properties[field_name] = _python_type_to_json_schema(annotation)
        if field_info.is_required():
            required.append(field_name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def function_to_parameters(func) -> dict[str, Any]:
    """Extract JSON Schema parameters from a function's signature."""
    sig = inspect.signature(func)
    properties = {}
    required = []

    for name, param in sig.parameters.items():
        annotation = param.annotation
        if annotation is inspect.Parameter.empty:
            properties[name] = {"type": "string"}
        else:
            origin = get_origin(annotation)
            args = get_args(annotation)
            is_optional = origin in (Optional, type(None)) or (
                origin is not None and type(None) in args
            )

            if is_optional and args:
                inner_type = next((a for a in args if a is not type(None)), str)
                properties[name] = _python_type_to_json_schema(inner_type)
            else:
                properties[name] = _python_type_to_json_schema(annotation)

        # Required: no default value and not Optional
        if param.default is inspect.Parameter.empty and not is_optional:
            required.append(name)

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema
