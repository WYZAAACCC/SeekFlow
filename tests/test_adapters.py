"""Tests for ecosystem adapters."""

from deepseek_toolkit.tools.decorator import tool
from deepseek_toolkit.tools.registry import ToolRegistry


class TestOpenAIAdapter:
    def test_to_openai_tools_format(self):
        """Output should be OpenAI-compatible tools format."""
        from deepseek_toolkit.adapters.openai_compatible import to_openai_tools

        registry = ToolRegistry()

        @tool
        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b

        registry.register(add)
        tools = to_openai_tools(registry)

        assert len(tools) == 1
        assert tools[0]["type"] == "function"
        assert tools[0]["function"]["name"] == "add"
        assert tools[0]["function"]["description"] == "Add two numbers."
        assert "parameters" in tools[0]["function"]

    def test_to_openai_tools_strict(self):
        """Strict flag should be accepted."""
        from deepseek_toolkit.adapters.openai_compatible import to_openai_tools

        registry = ToolRegistry()

        @tool
        def ping() -> str:
            """Ping."""
            return "pong"

        registry.register(ping)
        tools = to_openai_tools(registry, strict=True)

        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "ping"

    def test_to_openai_tools_empty_registry(self):
        """Empty registry returns empty list."""
        from deepseek_toolkit.adapters.openai_compatible import to_openai_tools

        registry = ToolRegistry()
        tools = to_openai_tools(registry)
        assert tools == []


class TestLangChainAdapter:
    def test_export_langchain_tool_schemas(self):
        """Should work without LangChain installed."""
        from deepseek_toolkit.adapters.langchain import export_langchain_tool_schemas

        registry = ToolRegistry()

        @tool
        def search(query: str) -> str:
            """Search for something."""
            return f"Results for {query}"

        registry.register(search)
        schemas = export_langchain_tool_schemas(registry)

        assert len(schemas) == 1
        assert schemas[0]["name"] == "search"
        assert schemas[0]["description"] == "Search for something."

    def test_export_langchain_no_langchain_installed(self):
        """Should not raise even if langchain is not installed."""
        from deepseek_toolkit.adapters.langchain import export_langchain_tool_schemas

        registry = ToolRegistry()
        schemas = export_langchain_tool_schemas(registry)
        assert schemas == []


class TestPydanticAIAdapter:
    def test_export_pydantic_ai_tool_schemas(self):
        """Should work without PydanticAI installed."""
        from deepseek_toolkit.adapters.pydantic_ai import export_pydantic_ai_tool_schemas

        registry = ToolRegistry()

        @tool
        def get_user(user_id: int) -> dict:
            """Get user by ID."""
            return {"id": user_id, "name": "test"}

        registry.register(get_user)
        schemas = export_pydantic_ai_tool_schemas(registry)

        assert len(schemas) == 1
        assert schemas[0]["name"] == "get_user"
        assert schemas[0]["parameters"]["type"] == "object"

    def test_export_pydantic_ai_no_package(self):
        """Should not raise even if pydantic_ai is not installed."""
        from deepseek_toolkit.adapters.pydantic_ai import export_pydantic_ai_tool_schemas

        registry = ToolRegistry()
        schemas = export_pydantic_ai_tool_schemas(registry)
        assert schemas == []
