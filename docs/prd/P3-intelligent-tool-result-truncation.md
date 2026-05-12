# P3: 工具结果智能截断

## Problem Statement

当前 `ToolExecutor` 的 `max_result_chars` 参数使用**暴力截断**：超过阈值的字符串结果直接切掉尾部，拼上一条固定提示。

问题场景：
1. **截断丢关键信息**：工具返回 50KB JSON，关键字段在末尾 → 暴力截断后模型拿到残缺数据，给出错误回答
2. **无结构感知**：截断可能在 JSON 中间切断，导致下一轮 JSON 修复管线尝试修复一个残缺 JSON
3. **无优先级**：所有字段一视同仁，但 `temperature` 比 `metadata.created_at` 更重要
4. **无容量感知**：截断提示 `[truncated: original 50000 chars]` 没有告诉模型"哪部分被丢了"

## Solution

三层改进：

**第一层：JSON 结构保留截断**
- 如果是 JSON 格式，解析后按路径截断而非按字符位置
- 截断深层嵌套数组（如 `results` 数组只保留前 N 项），保留顶层字段完整
- 截断后保证输出仍是合法 JSON

**第二层：字段优先级标注**
- `@tool` 装饰器支持 `keep_fields: list[str]` 参数，标记优先保留的字段路径
- 截断时优先满足 keep_fields 的完整性，剩余空间分配给其他字段
- 例如：`@tool(keep_fields=["temperature", "condition"])` 保证天气和状况字段不被截断

**第三层：智能截断提示**
- 截断后的结果附带结构化元信息：截断了哪些字段、原数据量、保留比例
- 模型可以根据这些信息判断是否需要二次调用（如"results 只显示了前 3 条，需要更多吗？"）

## User Stories

1. 作为一个调用返回大数据量工具的用户（如知识库搜索返回 200 条结果），我希望 `results` 数组保留前 N 条而非从中断开，这样模型至少能看到完整的前几条结果。
2. 作为一个工具定义者，我可以在 `@tool(keep_fields=["temperature", "humidity"])` 中标记关键字段，确保这些字段在截断时被优先保留。
3. 作为一个调用者，当工具结果被截断时，我希望截断后的输出仍是合法 JSON，不会因为被从中切断而导致下一轮 JSON 修复管线误判。
4. 作为一个调用者，截断提示中我希望看到"被截断了哪些字段、原数据量"，这样模型可以判断信息的完整性并决定是否需要补充调用。
5. 作为一个使用非 JSON 返回值的用户（纯文本或数字），我希望截断行为保持简单（纯字符截断 + 提示），不引入不必要的复杂度。

## Implementation Decisions

### 模块划分

- **新增模块：`TruncationStrategy`** — 枚举：`"simple"`（纯字符截断，现有行为）、`"json_aware"`（JSON 结构感知）、`"priority"`（字段优先级）。
- **修改模块：`ToolExecutor._maybe_truncate()`** — 根据 `TruncationStrategy` 选择截断逻辑。接收 `ToolDefinition` 以获取 `keep_fields`。
- **修改模块：`@tool` 装饰器** — 增加 `keep_fields: list[str] | None = None` 参数，存入 `ToolDefinition.metadata`。

### JSON 感知截断算法

```
输入: JSON dict, max_chars, keep_fields
1. 先序列化 keep_fields 指定的字段（如有），计入预算
2. 遍历顶层字段，按顺序序列化并计入预算
3. 遇到数组字段时，如果预算不足，保留前 N 个元素（保证元素完整），标记截断
4. 遇到嵌套对象字段时，如果预算严重不足，整个字段替换为 "..." 标记
5. 确保输出是合法的 JSON（括号配对）
```

### 截断元信息

```json
{
    "data": {...实际数据...},
    "_truncation": {
        "truncated": true,
        "original_chars": 50000,
        "kept_chars": 8000,
        "truncated_fields": ["results[3:]", "metadata.description"],
        "items_kept": 3,
        "items_total": 200
    }
}
```

## Testing Decisions

### 测试原则
- 测试截断后 JSON 合法性（`json.loads()` 可解析）
- 测试 keep_fields 优先级
- 测试边界：空对象、纯数组、深度嵌套、超大单字段
- 测试不同 truncation 策略的切换

### 测试模块
- `TruncationStrategy.json_aware` 单元测试：各类 JSON 结构 + 不同阈值
- `TruncationStrategy.priority` 单元测试：keep_fields 生效性
- `ToolExecutor` 集成测试：注入不同策略，验证截断结果
- `@tool(keep_fields=...)` 参数传递测试

### 参考先例
- `tests/test_tool_executor.py` 的 `max_result_chars` 相关测试
- `tests/test_tool_schema.py` 的 `@tool` 装饰器参数测试

## Out of Scope

- JSON Schema 驱动的自动优先级推断（如根据必填字段自动设置 keep_fields）
- 二进制结果处理
- 流式截断（streaming truncation）
- 截断策略的运行时动态切换
- 结果的压缩/摘要化（用 LLM 摘要替代截断）

## Further Notes

- `json_aware` 策略性能敏感——每次工具执行后都需要解析 JSON。对于简单纯文本结果（非 JSON），应快速 fallback 到 simple 模式。
- 截断后的 `_truncation` 字段会增加 JSON 体积（~200 chars），需要在预算计算中考虑。
- 工具返回列表（非 dict）时，`_truncation` 应外包裹为 `{"results": [...], "_truncation": {...}}`。
