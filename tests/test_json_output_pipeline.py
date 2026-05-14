"""Test JSON Output pipeline."""
import pytest
from pydantic import BaseModel
from seekflow.deepseek.json_output import (
    build_json_output_messages,
    parse_json_output,
    StructuredOutputError,
)


class TestModel(BaseModel):
    name: str
    score: int


def test_json_output_sets_response_format():
    messages = build_json_output_messages(
        user_prompt="Extract name and score",
        schema=TestModel,
    )
    assert messages[0]["role"] == "system"
    assert "json" in messages[0]["content"].lower()
    assert "name" in messages[0]["content"]


def test_json_prompt_contains_json_word_and_example():
    example = {"name": "Alice", "score": 95}
    messages = build_json_output_messages(
        user_prompt="Extract",
        schema=TestModel,
        example=example,
    )
    assert "json" in messages[0]["content"].lower()
    assert "Alice" in messages[0]["content"]


def test_parse_json_output_valid():
    result = parse_json_output('{"name": "Bob", "score": 80}', TestModel)
    assert result.name == "Bob"
    assert result.score == 80


def test_parse_json_output_invalid_json():
    with pytest.raises(StructuredOutputError):
        parse_json_output("not json", TestModel)


def test_parse_json_output_empty_content():
    with pytest.raises(StructuredOutputError):
        parse_json_output("", TestModel)


def test_parse_json_output_schema_mismatch():
    with pytest.raises(StructuredOutputError):
        parse_json_output('{"wrong_field": 1}', TestModel)
