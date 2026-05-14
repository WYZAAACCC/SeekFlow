# Build Prompt Cache Compiler: byte-level prefix analysis, cache ROI, invalidation tracking

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** enhancement
**State:** ready-for-agent

## What to build

Extend `seekflow.cache` with proactive cache compilation — analyzing the system prompt and tool schemas at the byte level to maximize DeepSeek prompt cache hit rate.

**`CacheCompiler`**:
```python
compiled = seekflow.compile_prompt(
    system=SYSTEM_PROMPT,
    tools=tools,
    cache_strategy="max_prefix_stability",
)
```

**Features:**

1. **Byte-level prefix analysis**: the compiler serializes the system prompt + tool schemas and computes the exact byte-prefix DeepSeek will use for cache matching. It identifies:
   - The exact byte range that forms the cacheable prefix
   - Which bytes are "hot" (matched in previous requests)
   - Which bytes are "cold" (never cached because they follow dynamic content)

2. **Tool schema canonicalizer** (extend `ToolRegistry.to_deepseek_tools()`): produce canonical JSON with sorted keys, consistent whitespace, and deterministic ordering. This already exists but is deepened — the compiler verifies canonical output is byte-identical across calls.

3. **Cache hit predictor**: given a messages list, predicts whether the prefix will match. Returns `CachePrediction(hit: bool, confidence: float, matched_bytes: int, total_prefix_bytes: int)`.

4. **Cache invalidation reason**: when a cache miss is detected, the compiler analyzes what changed. Returns `InvalidationReason(field: str, before_hash: str, after_hash: str, byte_offset: int)`. Example: "system prompt changed at byte 142: 'v2.0' → 'v2.1'".

5. **Cache ROI statistics** (in `CacheStabilizer`): track cumulative savings from cache hits. `cache_roi()` returns `{total_saved_cny, total_requests, hit_rate, avg_savings_per_request}`.

6. **Session prefix lock**: `compiled.lock()` returns a `CompiledPrefix` that can be passed to `Agent(compiled_prompt=compiled)`. The agent guarantees it will not modify the locked prefix bytes — any dynamic content is appended AFTER the prefix boundary.

**API**:
```python
compiler = CacheCompiler()
compiled = compiler.compile(system_prompt, tools_schema, strategy="max_prefix_stability")
# compiled.prefix_bytes, compiled.prefix_hash, compiled.cacheable_byte_range
# compiled.tool_schemas_canonical  # verified byte-stable
# compiled.invalidation_watchlist  # fields that would invalidate if changed

agent = Agent(compiled_prompt=compiled)
result = agent.run(task)
print(agent.cache_stats)  # includes ROI data
```

## Acceptance criteria

- [ ] `CacheCompiler.compile()` produces deterministic byte output for same input
- [ ] Tool schema canonicalizer verified byte-identical across 100 iterations
- [ ] `CachePrediction` correctly identifies when prefix will hit vs miss
- [ ] `InvalidationReason` identifies the exact byte offset and field that changed
- [ ] `cache_roi()` returns accurate cumulative savings in CNY
- [ ] `CompiledPrefix.lock()` prevents Agent from modifying locked bytes
- [ ] `Agent(compiled_prompt=compiled)` integration works end to end
- [ ] Unit test: same input twice → identical prefix_bytes and prefix_hash
- [ ] Unit test: system prompt changed → invalidation reason pinpoints byte offset
- [ ] Unit test: tool added → invalidation reason identifies tool schema change
- [ ] Unit test: dynamic content appended after prefix → cache prediction "hit"

## Blocked by

None — can start immediately. Builds on existing `CacheStabilizer` and `CacheSentinel`.
