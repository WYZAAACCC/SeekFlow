"""Example 1: Basic tool calling with @tool decorator."""
from deepseek_toolkit.tools.decorator import tool
from deepseek_toolkit.tools.registry import ToolRegistry


@tool
def add(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b


@tool(name="get_weather", description="Get current weather for a city")
def get_weather(city: str, unit: str = "celsius") -> dict:
    """Get weather data."""
    return {"city": city, "temperature": 22, "unit": unit, "condition": "sunny"}


def main():
    registry = ToolRegistry()
    registry.register(add)
    registry.register(get_weather)

    print(f"Registered {len(registry.list())} tools:")
    for td in registry.list():
        print(f"  - {td.name}: {td.description}")

    # Export to DeepSeek format
    print("\nDeepSeek tools schema:")
    import json
    print(json.dumps(registry.to_deepseek_tools(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
