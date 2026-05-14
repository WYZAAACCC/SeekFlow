# Force `tool_choice=none` on penultimate step for final synthesis

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** bug
**State:** ready-for-agent

## What to build

When `ToolRuntime.chat()` reaches `max_steps`, it currently returns `"ToolRuntime stopped because max_steps was reached."` — discarding all tool results accumulated and producing no answer for the user. This is a poor user experience: the model should synthesize a final answer from available data before the budget runs out.

Implement a two-phase early-stop strategy within the state machine (issue #14):

1. **Penultimate step warning** (`steps_remaining == 2`): inject a prompt telling the model "You have 2 turns remaining. Assess if data is sufficient. If so, begin synthesis next turn."

2. **Final step enforcement** (`steps_remaining == 1`): set `tool_choice="none"` in the API call parameters. This forces the model to produce a text response instead of more tool calls. The prompt says "This is your last turn. Provide a final answer based on available data. Do not call tools."

3. **Behavior when tool_choice="none" conflicts with the model**: if the model returns `finish_reason="stop"` with no content, the final synthesis prompt is re-sent once. If it still fails, return the best available content with a note about incomplete synthesis.

4. **Remove existing Chinese-language reminder messages**: the two user-message injections containing "你只剩最后一轮回复机会了" and "你还有 N 轮回复机会" that appear near the end of the main chat loop when `steps_remaining` falls to 1 or 2 — these are replaced by the structured strategy above. The new approach uses `tool_choice` at the API level rather than relying on prompt engineering alone.

## Acceptance criteria

- [ ] When `steps_remaining == 1`, the model call uses `tool_choice="none"`
- [ ] When `steps_remaining == 2`, a synthesis reminder prompt is injected
- [ ] Model forced to `tool_choice="none"` produces a text response (no tool calls)
- [ ] If model returns empty content with tool_choice="none", a single retry is attempted
- [ ] Old Chinese reminder strings removed
- [ ] `max_steps` exhausted with tool results available → final output is a synthesis, not "stopped"
- [ ] `max_steps` exhausted with no tool results → returns best available answer
- [ ] Regression test: 3-step run with model that always calls tools → at step 2, tool_choice="none" kicks in, model returns text answer

## Blocked by

- Issue #14 (state machine — final synthesis logic lives in the PREPARE phase)
