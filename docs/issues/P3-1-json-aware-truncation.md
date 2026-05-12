# P3-1: JSON-aware 截断算法 + 截断元信息

**状态**: `ready-for-agent`
**优先级**: P3
**类型**: AFK

## Parent

[P3: 工具结果智能截断](../prd/P3-intelligent-tool-result-truncation.md)

## What to build

实现一个结构感知的 JSON 截断算法，替代当前暴力 `result[:max_result_chars]` 截断。

核心设计：
- `TruncationStrategy` 枚举：`SIMPLE`（当前行为，纯字符截断）、`JSON_AWARE`（JSON 结构保留）、`PRIORITY`（字段优先级）
- JSON-aware 算法：
  1. 尝试 `json.loads()` 解析结果
  2. 非 JSON 或解析失败 → fallback 到 SIMPLE
  3. 如果是 dict：遍历顶层字段，按顺序序列化并计入字符预算
  4. 遇到数组字段且预算不足：保留前 N 个完整元素，标记截断
  5. 遇到嵌套对象且预算严重不足：替换为 `"..."` 标记
  6. 确保输出是合法 JSON（括号配对检查）
- 截断元信息：输出末尾追加 `_truncation` 字段（dict 类型），包含 `truncated: bool`、`original_chars: int`、`kept_chars: int`、`truncated_fields: list[str]`（如 `["results[3:]", "metadata.description"]`）、`items_kept: int`、`items_total: int`
- 列表结果（非 dict）外包裹为 `{"results": [...], "_truncation": {...}}`
- 预算计算需扣除 `_truncation` 字段自身占用的字符数

## Acceptance criteria

- [ ] 50KB JSON 结果截断到 8KB，输出仍是合法的 JSON
- [ ] 数组字段 `results` 保留前 N 个完整元素，不会从中切断
- [ ] 截断后的 `_truncation` 字段准确报告被截断的字段和数量
- [ ] 非 JSON 纯文本结果走 SIMPLE 模式，行为与当前一致
- [ ] 空对象 `{}` 和纯数组 `[]` 正确处理
- [ ] 截断后总字符数不超过 `max_result_chars`
- [ ] 性能：解析+截断 50KB JSON 耗时 < 5ms

## Blocked by

None - can start immediately

## Test suggestions

- 各类 JSON 结构（扁平、深层嵌套、大数组、混合）的截断测试
- 边界：恰好等于 max_result_chars、空结果、超大单字段
- 参考 `tests/test_tool_executor.py` 的 `max_result_chars` 测试
