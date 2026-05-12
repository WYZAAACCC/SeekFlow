"""JSON repair for malformed tool call arguments."""
from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field


class JsonRepairResult(BaseModel):
    ok: bool
    value: dict | None = None
    original: str
    repaired: str | None = None
    error: str | None = None
    applied_rules: list[str] = Field(default_factory=list)


def repair_json_arguments(raw: str) -> JsonRepairResult:
    """Try to repair malformed JSON arguments from model output."""
    applied: list[str] = []
    working = raw

    # Rule 1: Strip markdown code block
    md_pattern = re.compile(r'```(?:json)?\s*\n?(.*?)\n?```', re.DOTALL)
    md_match = md_pattern.search(working)
    if md_match:
        working = md_match.group(1).strip()
        applied.append("strip_markdown_code_block")

    # Rule 2: Extract first { ... } JSON object
    json_match = re.search(r'\{.*\}', working, re.DOTALL)
    if json_match:
        extracted = json_match.group(0)
        # Check if there's trailing content that looks like JSON continuations
        # (e.g. truncated second object in array: {"arr": [{"a": 1}, {"b": 2)
        after = working[json_match.end():]
        if after.lstrip().startswith((',', '{', '[')):
            # Extend to end — close_missing_braces will fix truncation
            extracted = working[json_match.start():]
        if extracted != working:
            working = extracted
            applied.append("extract_json_object")

    # Rule 2.3: Convert Python function-call syntax to JSON
    # get_weather(city="Hangzhou") → {"city": "Hangzhou"}
    before_func = working
    working = _extract_function_call_kwargs(working)
    if working != before_func:
        applied.append("function_call_to_json")

    # Rule 2.5: Strip // line comments (only outside strings)
    before_comment = working
    working = _strip_comments(working)
    if working != before_comment:
        applied.append("strip_line_comments")

    # Rule 3: Python True/False/None → JSON true/false/null
    before_literal = working
    working = re.sub(r'\bTrue\b', 'true', working)
    working = re.sub(r'\bFalse\b', 'false', working)
    working = re.sub(r'\bNone\b', 'null', working)
    if working != before_literal:
        applied.append("python_literals_to_json")

    # Rule 4: Single quotes → double quotes (careful with nested quotes)
    before_quotes = working
    working = _replace_single_quotes(working)
    if working != before_quotes:
        applied.append("single_quotes_to_double")

    # Rule 5: Remove trailing commas before } or ]
    before_commas = working
    working = re.sub(r',\s*}', '}', working)
    working = re.sub(r',\s*]', ']', working)
    if working != before_commas:
        applied.append("remove_trailing_commas")

    # Rule 6: Close missing braces/brackets
    before_close = working
    working = _close_missing_braces(working)
    if working != before_close:
        applied.append("close_missing_braces")

    # Rule 7: Remove explanatory text before/after JSON
    # (already handled by extract_json_object if a JSON-like block was found)

    # Rule 8: Try json.loads
    try:
        value = json.loads(working)
        return JsonRepairResult(
            ok=True,
            value=value,
            original=raw,
            repaired=working,
            applied_rules=applied,
        )
    except json.JSONDecodeError as e:
        return JsonRepairResult(
            ok=False,
            value=None,
            original=raw,
            repaired=working,
            error=str(e),
            applied_rules=applied,
        )


def _replace_single_quotes(text: str) -> str:
    """Replace single quotes with double quotes in a JSON-like string.

    Tracks both single and double quote state so that single quotes
    inside double-quoted strings are preserved as-is.
    Handles \\' → ' (unescape single quote when converting to double quotes).
    """
    result = []
    in_single = False
    in_double = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_single:
            if ch == "\\" and i + 1 < len(text):
                nxt = text[i + 1]
                if nxt == "'":
                    # \\' → ' (no need to escape single quote in double-quoted JSON)
                    result.append("'")
                    i += 1
                elif nxt == "\\":
                    result.append("\\\\")
                    i += 1
                else:
                    result.append(ch)
                    i += 1
                    result.append(nxt)
            elif ch == "'":
                in_single = False
                result.append('"')
            elif ch == '"':
                # Double quote inside single-quoted string → escape for JSON
                result.append('\\"')
            else:
                result.append(ch)
        elif in_double:
            if ch == "\\" and i + 1 < len(text):
                result.append(ch)
                i += 1
                result.append(text[i])
            elif ch == '"':
                in_double = False
                result.append(ch)
            elif ch == "'":
                # Single quote inside double-quoted string: keep as-is
                result.append(ch)
            else:
                result.append(ch)
        else:
            if ch == "'":
                in_single = True
                result.append('"')
            elif ch == '"':
                in_double = True
                result.append(ch)
            elif ch == "\\" and i + 1 < len(text) and text[i + 1] == '"':
                # Stray \\" outside string → just "
                result.append('"')
                i += 1
            else:
                result.append(ch)
        i += 1

    return "".join(result)


def _close_missing_braces(text: str) -> str:
    """Close unclosed braces and brackets by tracking opening order on a stack.

    Uses LIFO stack so that closing delimiters are appended in the reverse
    order of their openings — e.g. { [ { → needs } ] } not ] } }.
    """
    stack: list[str] = []
    in_str = False
    str_char = None
    i = 0

    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\" and i + 1 < len(text):
                i += 1
            elif ch == str_char:
                in_str = False
                str_char = None
        else:
            if ch == '"' or ch == "'":
                in_str = True
                str_char = ch
            elif ch == '{':
                stack.append('}')
            elif ch == '[':
                stack.append(']')
            elif ch == '}' or ch == ']':
                if stack and stack[-1] == ch:
                    stack.pop()
                # else: stray close — ignore rather than letting depth go negative
        i += 1

    if not stack:
        return text

    # Close in reverse order (LIFO)
    closing = "".join(reversed(stack))
    return text + closing


def _strip_comments(text: str) -> str:
    """Strip // line comments that appear outside of strings.

    Preserves // inside string values like URLs (e.g. "http://example.com").
    """
    result = []
    in_str = False
    str_char = None
    i = 0
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\" and i + 1 < len(text):
                result.append(ch)
                i += 1
                result.append(text[i])
            elif ch == str_char:
                in_str = False
                str_char = None
                result.append(ch)
            else:
                result.append(ch)
        else:
            if ch == '"' or ch == "'":
                in_str = True
                str_char = ch
                result.append(ch)
            elif ch == '/' and i + 1 < len(text) and text[i + 1] == '/':
                # Found // outside string — skip to end of line
                while i < len(text) and text[i] != '\n':
                    i += 1
                # Keep the newline if present
                if i < len(text) and text[i] == '\n':
                    result.append('\n')
            else:
                result.append(ch)
        i += 1

    return "".join(result)


def _extract_function_call_kwargs(text: str) -> str:
    """Convert Python function-call syntax to a JSON object.

    get_weather(city="Beijing")           → {"city": "Beijing"}
    add(a=1, b=2)                         → {"a": 1, "b": 2}
    search(query="AI", limit=3)           → {"query": "AI", "limit": 3}
    get_weather(city="Beijing", unit="c") → {"city": "Beijing", "unit": "c"}

    Only applies when there is NO top-level { … } in the input.
    """
    # Bail out if we already have a JSON-like structure
    if "{" in text or "}" in text:
        return text

    # Must look like: identifier ( ... )
    if "(" not in text or not text.strip().endswith(")"):
        return text

    # Find the first ( — everything before it is the function name
    paren_idx = text.index("(")
    name = text[:paren_idx].strip()
    if not name or not name.replace("_", "").isalnum():
        return text

    kwargs_str = text[paren_idx + 1:-1].strip()
    if not kwargs_str:
        return text

    # Parse key=value pairs
    pairs = _split_kwargs(kwargs_str)
    json_parts = []
    for pair in pairs:
        eq_idx = pair.find("=")
        if eq_idx < 0:
            return text
        key = pair[:eq_idx].strip()
        val = pair[eq_idx + 1:].strip()

        if val.lower() in ("true", "false", "none", "null"):
            val = val.lower()
            if val == "none":
                val = "null"
        elif re.match(r'^-?\d+(\.\d+)?$', val):
            pass
        elif (val.startswith('"') and val.endswith('"')) or \
             (val.startswith("'") and val.endswith("'")):
            inner = val[1:-1]
            inner = inner.replace('\\', '\\\\').replace('"', '\\"')
            val = '"' + inner + '"'
        else:
            val = '"' + val + '"'

        json_parts.append(f'"{key}": {val}')

    return "{" + ", ".join(json_parts) + "}" if json_parts else text


def _split_kwargs(s: str) -> list[str]:
    """Split comma-separated kwargs respecting quote state."""
    if len(s) > 100_000:
        return [s]
    parts = []
    current: list[str] = []
    in_single = False
    in_double = False
    i = 0
    while i < len(s):
        ch = s[i]
        if in_single:
            current.append(ch)
            if ch == "\\" and i + 1 < len(s):
                i += 1
                current.append(s[i])
            elif ch == "'":
                in_single = False
        elif in_double:
            current.append(ch)
            if ch == "\\" and i + 1 < len(s):
                i += 1
                current.append(s[i])
            elif ch == '"':
                in_double = False
        else:
            if ch == "'":
                in_single = True
                current.append(ch)
            elif ch == '"':
                in_double = True
                current.append(ch)
            elif ch == ",":
                parts.append("".join(current).strip())
                current = []
                i += 1
                continue
            else:
                current.append(ch)
        i += 1

    if current:
        parts.append("".join(current).strip())

    return parts
