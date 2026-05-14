# Implement JSON repair confidence scoring with dangerous-tool level gating

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** bug
**State:** ready-for-agent

## What to build

Extend `repair_json_arguments()` with a confidence score and integrate repair-level gating into `ToolExecutor` based on tool risk.

**Repair levels:**

| Level | Method | Confidence | When allowed |
|-------|--------|-----------|--------------|
| 0 | `json.loads` succeeds | 1.0 | Always |
| 1 | Safe syntactic repair (quotes, trailing commas, braces, comments, Python literals) | 0.85–0.99 | Read-only tools only |
| 2 | Model re-emission — ask model to output valid JSON | N/A | Any (expensive) |
| 3 | Human approval / fail-closed | N/A | Dangerous when Level 1 fails |

**Confidence scoring for Level 1 repair**: compute a score based on:
- How many rules were applied (fewer = higher confidence)
- Whether the repaired JSON parses to a dict (not list/string/number — dict is what tool calls expect)
- Whether all expected schema keys are present in the result
- Whether `_close_missing_braces` was needed (truncation = low confidence)

**Dangerous-tool gating in `ToolExecutor._parse_arguments()`**:
```python
risk = (tool_def.policy.risk if tool_def.policy else "read")
if isinstance(arguments, str):
    repair_result = repair_json_arguments(arguments)
    if repair_result.ok:
        if repair_result.level == 0:  # native parse
            return repair_result.value, True, []
        if repair_result.level == 1 and risk == "read":  # safe repair for reads
            return repair_result.value, True, repair_result.applied_rules
        if repair_result.level == 1 and risk != "read":  # repair for dangerous — deny
            return {}, False, ["repair_denied_for_dangerous_tool"]
    # Level 2: trigger model re-emission
```

**Model re-emission (Level 2)**: when repair Level 1 fails or is denied for a dangerous tool, the `ToolExecutor` returns an error that signals the runtime to re-prompt the model with the specific JSON parse error, asking for corrected arguments. The runtime handles this as a special tool-call-retry cycle.

## Acceptance criteria

- [ ] `repair_json_arguments()` returns `confidence: float` (0.0–1.0) in `JsonRepairResult`
- [ ] Native `json.loads` success → confidence=1.0, level=0
- [ ] Single fix (e.g., trailing comma only) → confidence >= 0.9
- [ ] Multiple fixes + brace closing → confidence < 0.85
- [ ] Read tool (risk="read"): Level 1 repair → tool executes with repaired args
- [ ] Dangerous tool (risk="code_exec"/"destructive"): Level 1 repair → denied, error returned
- [ ] Dangerous tool + Level 0 repair (native parse) → allowed (model output was valid JSON)
- [ ] Model re-emission signal returned when repair is denied for dangerous tool
- [ ] Regression test: `{"code": "print(1)"` on read tool → repaired, executes
- [ ] Regression test: `{"code": "print(1)"` on code_exec tool → repair denied
- [ ] Regression test: `{"query": "SELECT * FROM users"}` on database.read → Level 0, allowed

## Blocked by

None — can start immediately. (Issue #11 provides ToolPolicy.risk which gates behavior.)
