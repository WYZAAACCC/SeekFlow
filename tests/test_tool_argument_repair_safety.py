"""Test tool argument repair safety thresholds."""
from seekflow.repair.json_repair import repair_json_arguments
from seekflow.tools.executor import DANGEROUS_REPAIR_CONFIDENCE_THRESHOLD


def test_repair_confidence_threshold_consistent():
    """The dangerous repair threshold must be exactly 0.95 — not 0.85 anywhere."""
    assert DANGEROUS_REPAIR_CONFIDENCE_THRESHOLD == 0.95, (
        f"DANGEROUS_REPAIR_CONFIDENCE_THRESHOLD is {DANGEROUS_REPAIR_CONFIDENCE_THRESHOLD}, expected 0.95"
    )


def test_valid_json_has_high_confidence():
    result = repair_json_arguments('{"a": 1}')
    assert result.ok
    assert result.confidence == 1.0
    assert result.repair_level == 0


def test_repaired_json_has_lower_confidence():
    result = repair_json_arguments("{'a': 1,}")
    assert result.ok
    assert result.confidence < 1.0


def test_unrepairable_json_fails():
    result = repair_json_arguments("not json at all!!!")
    assert not result.ok


def test_markdown_code_block_repair():
    result = repair_json_arguments('```json\n{"a": 1}\n```')
    assert result.ok
    assert result.value == {"a": 1}
    assert "strip_markdown_code_block" in result.applied_rules


def test_single_quotes_repaired():
    result = repair_json_arguments("{'a': 'hello'}")
    assert result.ok
    assert result.value == {"a": "hello"}


def test_trailing_comma_repaired():
    result = repair_json_arguments('{"a": 1,}')
    assert result.ok
    assert result.value == {"a": 1}


def test_python_literals_repaired():
    result = repair_json_arguments('{"flag": True, "val": None}')
    assert result.ok
    assert result.value == {"flag": True, "val": None}
