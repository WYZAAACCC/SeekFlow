# Implement messages deep-copy in Runtime.chat() and embed_files_into_message

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** bug
**State:** ready-for-agent

## What to build

Two mutation bugs where user-provided data structures are modified in place:

1. **`ToolRuntime.chat()` / `chat_stream()`**: line 206 `working_messages = list(messages)` is a shallow copy. Nested dicts (message objects) are still shared with the caller's list. When the runtime appends assistant/tool messages or modifies content, the caller's original list is mutated. Fix: deep-copy the entire messages structure at entry using `copy.deepcopy()`.

2. **`embed_files_into_message()`**: line 96 `message["content"] = ...` directly mutates the input dict. If the caller reuses the same message dict across multiple calls, file content is embedded repeatedly, causing context bloat. Fix: return a new dict (`{**message, "content": new_content}`) instead of mutating. Update the single call site in `runtime.py` to use the returned dict.

3. **`_trim_messages()` / `repair_message_order()`**: verify these also operate on copies or are called only on the runtime's working copy.

**Performance note**: `copy.deepcopy()` on a messages list with ~50 messages of ~2KB each takes <1ms. Acceptable for production use. If profiling later shows issues with 1000+ message histories, a specialized `copy_message_list()` can be introduced — but not in this issue.

## Acceptance criteria

- [ ] `ToolRuntime.chat()` deep-copies input messages before any mutation
- [ ] `ToolRuntime.chat_stream()` deep-copies input messages before any mutation
- [ ] `embed_files_into_message()` returns a new dict instead of mutating input
- [ ] Calling `chat()` twice with the same messages list produces identical first-turn behavior (no leftover tool results from first call)
- [ ] Calling `embed_files_into_message(msg, files)` twice with the same msg → second call result same as first (no double embedding)
- [ ] Deep-copy overhead measured and documented (target: <5ms for typical 50-message list)
- [ ] Regression test: messages list unchanged after `chat()` completes
- [ ] Regression test: `embed_files_into_message()` does not modify input dict

## Blocked by

None — can start immediately.
