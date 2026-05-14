# Remove semantic message injection from repair_message_order

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** bug
**State:** ready-for-agent

## What to build

`_runtime_base.py:repair_message_order()` currently does two things:
1. **Protocol-required fixes**: remove orphaned tool messages (tool messages without a preceding assistant message with tool_calls), remove non-user/non-system messages at the start of the list
2. **Semantic injection**: inserts `{"role": "user", "content": "Please continue."}` when the first non-system message is not a `user` role (line 84), and appends it when no user message exists (line 87)

The semantic injection is problematic: inserting "Please continue." into the message list can alter task semantics, trigger unintended model behavior, and is an implicit prompt modification that the caller doesn't expect.

Fix:
- Keep protocol-required fixes (orphaned tool message removal, role ordering)
- Replace "Please continue." with the minimum API-required message: `{"role": "user", "content": ""}` (empty content) — or restructure the messages to satisfy the API constraint without adding semantic content
- If the messages array genuinely has no user message, raise a clear `ValueError` rather than silently injecting text

## Acceptance criteria

- [ ] `repair_message_order()` does NOT inject "Please continue." or any other semantic instruction
- [ ] Orphaned tool messages (tool without preceding assistant with tool_calls) are still removed
- [ ] If no user message exists after system message, raises `ValueError` with clear message
- [ ] Empty user content is acceptable as a protocol fix (API requires a user message)
- [ ] All existing call sites (`_trim_messages`, `append_only_compress`) updated if needed
- [ ] Regression test: messages `[system, assistant(content="hi")]` → the assistant message is kept or a ValueError is raised (not silently mutated with "Please continue.")
- [ ] Regression test: messages with valid structure are not modified

## Blocked by

None — can start immediately.
