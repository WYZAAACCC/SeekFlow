"""Tests for @tool decorator and schema generation."""
from typing import Literal, Optional

from pydantic import BaseModel

from seekflow.tools.decorator import tool
from seekflow.types import ToolDefinition


class TestToolDecorator:
    def test_basic_decorator(self):
        @tool
        def add(a: int, b: int) -> int:
            """Add two integers."""
            return a + b

        assert isinstance(add, ToolDefinition)
        assert add.name == "add"
        assert add.description == "Add two integers."

    def test_decorator_preserves_callable(self):
        @tool
        def greet(name: str) -> str:
            return f"Hello {name}"

        assert callable(greet.func)
        result = greet.func("World")
        assert result == "Hello World"

    def test_custom_name_and_description(self):
        @tool(name="weather_query", description="Query city weather")
        def get_weather(city: str) -> str:
            return f"{city}: sunny"

        assert get_weather.name == "weather_query"
        assert get_weather.description == "Query city weather"

    def test_no_docstring_uses_function_name(self):
        @tool
        def f(x: int) -> int:
            return x

        assert f.name == "f"
        assert f.description == ""


class TestSchemaGeneration:
    def test_str_type(self):
        @tool
        def echo(text: str) -> str:
            return text

        params = echo.parameters
        assert params["properties"]["text"]["type"] == "string"

    def test_int_type(self):
        @tool
        def inc(n: int) -> int:
            return n + 1

        params = inc.parameters
        assert params["properties"]["n"]["type"] == "integer"

    def test_float_type(self):
        @tool
        def half(x: float) -> float:
            return x / 2

        params = half.parameters
        assert params["properties"]["x"]["type"] == "number"

    def test_bool_type(self):
        @tool
        def toggle(flag: bool) -> bool:
            return not flag

        params = toggle.parameters
        assert params["properties"]["flag"]["type"] == "boolean"

    def test_list_str_type(self):
        @tool
        def join_items(items: list[str]) -> str:
            return ", ".join(items)

        params = join_items.parameters
        prop = params["properties"]["items"]
        assert prop["type"] == "array"
        assert prop["items"]["type"] == "string"

    def test_required_fields(self):
        @tool
        def add(a: int, b: int) -> int:
            return a + b

        params = add.parameters
        assert set(params["required"]) == {"a", "b"}

    def test_optional_not_in_required(self):
        @tool
        def greet(name: str, title: Optional[str] = None) -> str:
            return f"Hello {name}"

        params = greet.parameters
        assert "title" not in params.get("required", [])

    def test_default_value_not_in_required(self):
        @tool
        def greet(name: str, greeting: str = "Hello") -> str:
            return f"{greeting} {name}"

        params = greet.parameters
        assert "greeting" not in params.get("required", [])

    def test_literal_to_enum(self):
        @tool
        def set_mode(mode: Literal["a", "b", "c"]) -> str:
            return mode

        params = set_mode.parameters
        assert params["properties"]["mode"]["enum"] == ["a", "b", "c"]

    def test_parameters_is_object(self):
        @tool
        def add(a: int, b: int) -> int:
            return a + b

        assert add.parameters["type"] == "object"

    def test_pydantic_model_parameter(self):
        class Address(BaseModel):
            city: str
            zip_code: str

        @tool
        def lookup(address: Address) -> str:
            return f"{address.city} {address.zip_code}"

        params = lookup.parameters
        prop = params["properties"]["address"]
        assert prop["type"] == "object"
        assert "city" in prop["properties"]
        assert prop["properties"]["city"]["type"] == "string"


class TestToolPolicy:
    """ToolPolicy model — capability, risk, timeout, safety metadata."""

    def test_default_policy_has_safe_defaults(self):
        from seekflow.types import ToolPolicy

        p = ToolPolicy()
        assert p.risk == "read"
        assert p.timeout_s == 30.0
        assert p.max_input_bytes == 1_000_000
        assert p.max_output_bytes == 100_000
        assert p.parallel_safe is False
        assert p.requires_approval is False
        assert p.capabilities == set()
        assert p.allowed_domains == set()
        assert p.workspace_root is None

    def test_risk_values_are_constrained(self):
        from seekflow.types import ToolPolicy

        p = ToolPolicy(risk="read")
        assert p.risk == "read"

        for risk in ("write", "network", "code_exec", "destructive"):
            p2 = ToolPolicy(risk=risk)
            assert p2.risk == risk

    def test_invalid_risk_raises(self):
        import pytest
        from pydantic import ValidationError
        from seekflow.types import ToolPolicy

        with pytest.raises(ValidationError):
            ToolPolicy(risk="invalid_risk")

    def test_policy_in_tool_definition(self):
        from seekflow.types import ToolPolicy, ToolDefinition

        policy = ToolPolicy(
            capabilities={"filesystem.read"},
            risk="read",
            timeout_s=2.0,
            workspace_root=None,
        )
        td = ToolDefinition(
            name="read_file",
            description="Read a file",
            parameters={"type": "object", "properties": {}},
            policy=policy,
        )
        assert td.policy is not None
        assert td.policy.capabilities == {"filesystem.read"}
        assert td.policy.risk == "read"
        assert td.policy.timeout_s == 2.0

    def test_with_policy_builder(self):
        from seekflow.types import ToolPolicy, ToolDefinition

        td = ToolDefinition(
            name="web_fetch",
            description="Fetch a URL",
            parameters={"type": "object", "properties": {}},
        )
        p = ToolPolicy(risk="network", allowed_domains={"example.com"})
        td = td.with_policy(p)
        assert td.policy == p
        assert td.policy.allowed_domains == {"example.com"}

    def test_tool_definition_without_policy_has_none(self):
        from seekflow.types import ToolDefinition

        td = ToolDefinition(
            name="simple_tool",
            description="A simple tool",
            parameters={"type": "object", "properties": {}},
        )
        assert td.policy is None
