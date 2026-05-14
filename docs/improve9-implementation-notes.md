# improve9.md Implementation Notes

## Already Done (from improve8, no further changes needed)

These items from improve9.md were already fully implemented by the improve8
round and did not need additional changes:

| improve9 Section | Item | Status |
|---|---|---|
| 4.1 | ruff format (formatting-only commit) | Deferred — safe to run separately, no behavior change |
| 4.2 | Import smoke tests | Already done in `tests/test_import_smoke.py` |
| 5.2 | make_calculate with AST-safe eval | Already done, moved to `compute.py` in this round |
| 5.3 | path_params/url_params on builtin policies | Already done in improve8 |
| 8.2-8.3 | ToolExecutor input/output enforcement | Partially done — executor order is fixed; explicit enforcement functions (`_enforce_input_limit`, `_enforce_output_limit`) are a P2 refinement |
| 8.5 | Audit record fields (input_bytes, output_bytes, etc.) | Existing audit record covers core fields; extended fields are P2 |
| 10 | DeepSeekAdapter as single entry point | Already done — adapter.py exists with full normalization |
| 13 | ModelRegistry/Pricing/Usage/Budget | Already done — ModelRegistry with from_yaml, price_usage, resolve |
| 14 | JSON Output pipeline | Already done — build_json_output_messages + parse_json_output |
| 15.2 | GitHub Actions CI | Already done — `.github/workflows/ci.yml` exists |

## Deferred (architectural changes requiring more design)

| improve9 Section | Item | Reason |
|---|---|---|
| 9 | ExecutionBackend (ProcessExecutionBackend) | Requires multiprocessing architecture redesign. ThreadPoolExecutor is adequate for current use; ProcessExecutionBackend adds complexity that needs dedicated testing infrastructure. The existing sandbox (ProcessSandbox/ContainerSandbox) already covers code_exec isolation. |
| 10.4 | Remove _apply_thinking_mode() from runtime | Would require full refactor of runtime to adapter. The current coexistence (adapter + _apply_thinking_mode) is a safe transitional state. Full migration requires updating all call sites in agent. |
| 11.4 | chat_batch() adapter integration | Batch path is single-step only (documented). Full adapter integration needs batch-specific thinking config handling. |

## Not Applicable (items that don't match current codebase reality)

| improve9 Reference | Reason |
|---|---|
| "allow_filesystem(write=True) didn't register write_file" | Was true before improve8; now fixed |
| "builtins don't have path_params/url_params" | Was true before improve8; now all have them |
| "runtime file attachments don't pass workspace_root" | Was true before improve8; now wired via _workspace_root_or_error() |
| "PolicyEngine dict context is permissive" | Was true before improve9; now strict by default |
| "legacy agent/builtins has unsafe fetch_url/run_python/query_sql" | Now disabled — they raise RuntimeError directing to safe factories |

## Key Decisions Made in This Round

1. **PolicyEngine strict mode default**: `mode="strict"` is now the default. Dict context defaults to `dangerous_enabled=False`, `max_risk="read"`, `allowed_capabilities={"read"}`. Use `mode="compat"` for legacy behavior.

2. **Legacy builtins disabled**: `agent/builtins.py` `fetch_url`, `run_python`, `query_sql` now raise `RuntimeError` directing users to `seekflow.tools.builtins` safe factories. Safe utils (`parse_csv_str`, `extract_entities`, `classify_text`) are preserved.

3. **with_default_tools() simplified**: Always loads calculate + 3 safe text utils. No longer gates on `dangerous_tools=True`.

4. **allow_filesystem() semantics**: `read=True` registers `read_file` + `list_dir`. `write=True` registers `write_file`. Raises `ValueError` if neither is True.

5. **HTTP trust_env=False**: All hardened HTTP requests now disable environment proxy to prevent proxy-based SSRF.

6. **SQL validation**: Now uses tokenizer-based forbidden keywords (ATTACH/DETACH/INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/REPLACE/VACUUM) as first line of defense, with sqlite3 authorizer as second line.
