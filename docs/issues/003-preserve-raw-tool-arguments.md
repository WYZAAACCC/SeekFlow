# Preserve raw tool call arguments through Client layer into repair pipeline

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** bug
**State:** ready-for-agent

## What to build

`DeepSeekClient.chat()` line 99-103 currently attempts `json.loads(raw_args)` and on `JSONDecodeError` silently sets `parsed_args = {}`. This destroys the original malformed JSON, making downstream `ToolExecutor` repair impossible — the repair pipeline never sees the raw string it needs to fix.

The fix spans two layers:

**Client layer** (`client.py`): On `JSONDecodeError`, preserve the raw string. Instead of `parsed_args = {}`, store the raw string so the repair pipeline can receive it. `ToolCall.arguments` changes from `dict` to `dict | str`.

**ToolExecutor layer** (`tools/executor.py`): `execute()` already handles `isinstance(arguments, str)` by calling `_parse_arguments()` → `repair_json_arguments()`. This path should be exercised for all calls where the client couldn't parse, rather than receiving an already-empty dict.

The `chat_stream()` path in `client.py` already yields raw argument strings — the streaming `ToolCall` construction in `runtime.py` (line 517-521) already has a `json.JSONDecodeError → parsed_args = {}` fallback that must be similarly fixed.

## Acceptance criteria

- [ ] `DeepSeekClient.chat()` preserves raw `tc.function.arguments` string on `JSONDecodeError` instead of discarding to `{}`
- [ ] `ToolCall.arguments` type allows `dict | str`
- [ ] `ToolExecutor.execute()` receives the raw string and routes it through `repair_json_arguments()`
- [ ] Streaming path in `runtime.py` also preserves raw args on parse failure
- [ ] `repair_message_order` and `_trim_messages` handle `dict | str` arguments correctly
- [ ] Regression test: model returns `{"city": "Beijing"` (missing closing brace) → repair pipeline receives the raw string, repairs it, tool executes with `{"city": "Beijing"}`
- [ ] Regression test: model returns completely unparseable garbage → `_parse_arguments` returns `({}, False, [...])` and executor returns error result

## Blocked by

None — can start immediately.
