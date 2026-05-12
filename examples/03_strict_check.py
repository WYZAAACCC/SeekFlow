"""Example 3: Strict compatibility check."""
from deepseek_toolkit.tools.strict import check_strict_compatibility


def main():
    # Valid schema
    valid_tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather for a city",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "City name",
                        },
                    },
                    "required": ["city"],
                },
            },
        },
    ]

    result = check_strict_compatibility(valid_tools)
    print(f"Valid schema: ok={result.ok}")

    # Problematic schema (has anyOf)
    problematic_tools = [
        {
            "type": "function",
            "function": {
                "name": "bad_tool",
                "description": "This tool has issues",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "value": {
                            "anyOf": [
                                {"type": "string"},
                                {"type": "integer"},
                            ],
                        },
                    },
                },
            },
        },
    ]

    result = check_strict_compatibility(problematic_tools)
    print(f"\nProblematic schema: ok={result.ok}")
    for issue in result.issues:
        print(f"  [{issue.level}] {issue.path}: {issue.message}")


if __name__ == "__main__":
    main()
