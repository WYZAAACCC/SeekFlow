"""Example 2: JSON repair and argument coercion."""
from deepseek_toolkit.repair.json_repair import repair_json_arguments
from deepseek_toolkit.repair.coercion import coerce_arguments


def main():
    # Simulate malformed JSON from model output
    bad_json_cases = [
        "{'city': 'Hangzhou', 'days': 3}",           # single quotes
        '{"city": "Hangzhou", "days": 3,}',           # trailing comma
        "```json\n{\"city\": \"Beijing\"}\n```",       # markdown code block
        '{\"city\": \"Shanghai\", \"active\": true}',  # Python bool
        'The weather in {"city": "Shenzhen"} is nice',# JSON in text
    ]

    print("JSON Repair Examples:\n")
    for raw in bad_json_cases:
        result = repair_json_arguments(raw)
        print(f"  Input:  {raw}")
        if result.ok:
            print(f"  Output: {result.value}")
        else:
            print(f"  Output: FAILED - {result.applied_rules}")
        print(f"  Rules applied: {result.applied_rules}\n")

    # Coercion example
    schema = {
        "type": "object",
        "properties": {
            "count": {"type": "integer"},
            "temperature": {"type": "number"},
            "enabled": {"type": "boolean"},
        },
    }

    raw_args = {"count": "42", "temperature": "23.5", "enabled": "true"}
    coerced, notes = coerce_arguments(raw_args, schema)
    print("Coercion Example:")
    print(f"  Before: {raw_args}")
    print(f"  After:  {coerced}")
    print(f"  Notes:  {notes}")


if __name__ == "__main__":
    main()
