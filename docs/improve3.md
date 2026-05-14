结论：**作者确实做了不少实质性更新，不是只改 README；但修复还没有到“生产级”。**
我会把当前状态判断为：**v0.2 hardening beta**，有明显进步，但仍存在多个会导致线上错误、安全误判或 DeepSeek API 不兼容的关键问题。

我这次是按当前 GitHub main 分支公开代码重新审计的。由于当前执行环境无法直接 clone GitHub 并运行 pytest，所以没有完成真实本地动态测试；下面的“动态分析”是基于代码路径推演、官方 DeepSeek API 约束和仓库测试代码交叉核查。

---

# 1. 总体结论

## 1.1 作者已经修对/改进的部分

这次更新里，确实能看到几个实质进步：

| 项目                                  | 当前状态                                                              | 评价               |
| ----------------------------------- | ----------------------------------------------------------------- | ---------------- |
| 非流式 tool call 的 `reasoning_content` | 已开始完整保留                                                           | 这是最重要的正向修复之一     |
| 非流式 tool arguments 解析失败             | 不再直接吞成 `{}`，而是保留 raw string                                       | 有进步，但设计仍不理想      |
| thinking 模式下无效采样参数                  | 代码会移除并 warning                                                    | 方向正确             |
| 安全模块                                | 增加了 policy、SSRF、path sandbox、redaction、untrusted wrapper 等        | 有框架雏形            |
| tool output untrusted wrapper       | 已有实现路径                                                            | 好方向              |
| cache usage 字段                      | client 已支持 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` | 好方向              |
| 测试目录                                | 增加了大量测试文件                                                         | 有进步，但部分测试锁定了错误行为 |

README 当前宣称 v0.2.0 包含 production-grade security、Policy Engine、SSRF protection、path sandbox、secret redaction、preflight cost budgeting、per-tool timeout、620+ tests 等能力。仓库确实新增了不少对应模块和测试文件，但**实现质量和接入完整度还撑不起 production-grade 这个词**。([GitHub][1])

---

## 1.2 仍然严重的问题

当前最严重的问题有 8 个：

```text id="2qgi78"
1. strict tool calling 仍然基本没真正实现
2. thinking 参数与当前 DeepSeek 官方接口不完全匹配
3. runtime 仍会把 Reasoning Insights 注入 user message
4. streaming / batch 路径仍会把坏 JSON 变成 {}
5. PolicyEngine 存在，但没有可靠接入 ToolExecutor 主执行路径
6. timeout 仍是线程级 timeout，不是真正可中断执行
7. FIM 仍然用 special token 拼 prompt，而不是官方 prompt + suffix
8. balance 类型 bug 仍然存在，会直接 TypeError
```

我的当前评分：

| 维度                      |         当前评分 |
| ----------------------- | -----------: |
| 架构方向                    |         7/10 |
| 非流式 DeepSeek tool 协议    |       6.5/10 |
| streaming/batch tool 协议 |         4/10 |
| strict tools            |         2/10 |
| 安全执行                    |         5/10 |
| FIM 适配                  |         3/10 |
| cache/cost 可观测          |       5.5/10 |
| 生产可用性                   |       4.5/10 |
| 综合                      | **5.5–6/10** |

比上一版有进步，但仍然不能称为 production-grade。

---

# 2. P0 问题：必须优先修复

---

## P0-1：Strict tool calling 仍然没有真正实现

这是当前最严重的问题之一。

DeepSeek 官方 strict mode 要求：

```text id="hbfz48"
1. 使用 https://api.deepseek.com/beta
2. 每个 function 设置 strict: true
3. schema 需要满足 strict JSON Schema 约束
4. object schema 需要 required 与 additionalProperties: false
```

官方示例中 function 明确带有 `"strict": true`，schema 也包含 `required` 和 `additionalProperties: false`。([DeepSeek API Docs][2])

但当前 `ToolRegistry.to_deepseek_tools(strict=True)` 仍然没有真正使用 `strict` 参数。它只是导出：

```python id="8jf66i"
{
    "type": "function",
    "function": {
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.parameters,
    },
}
```

没有 `strict: true`，也没有 strict schema compiler。([GitHub][3])

更严重的是，当前 `tools/strict.py` 里的 strict checker 只把 `additionalProperties` 缺失当成 warning，而不是 error；并且没有检查 object 的所有 properties 是否都在 required 里。测试里甚至把一个缺少 `additionalProperties: false` 的 schema 判定为 valid。([GitHub][4])

### 影响

这意味着：

```text id="bxlkl2"
strict=True 很可能只是“名义 strict”
DeepSeek beta strict 校验不一定能通过
用户以为工具参数稳定，其实没有得到官方 strict 保证
README 中 strict/production 相关声明不可靠
```

### 必须修复

应新增 `DeepSeekStrictSchemaCompiler`：

```python id="13thln"
class DeepSeekStrictSchemaCompiler:
    def compile(self, schema: dict) -> dict:
        schema = copy.deepcopy(schema)
        self._remove_unsupported_keywords(schema)
        self._force_all_object_properties_required(schema)
        self._force_additional_properties_false(schema)
        self._validate(schema)
        return schema
```

`ToolRegistry.to_deepseek_tools(strict=True)` 必须输出：

```python id="8zx9ak"
{
    "type": "function",
    "function": {
        "name": tool.name,
        "description": tool.description,
        "parameters": strict_schema,
        "strict": True,
    },
}
```

并且 strict 模式必须自动使用：

```python id="5gpl95"
base_url = "https://api.deepseek.com/beta"
```

### 验收测试

```python id="jolm20"
def test_strict_tools_emit_strict_true():
    tools = registry.to_deepseek_tools(strict=True)
    assert tools[0]["function"]["strict"] is True


def test_strict_schema_requires_all_properties():
    schema = compiler.compile({
        "type": "object",
        "properties": {
            "city": {"type": "string"},
            "date": {"type": "string"},
        },
    })

    assert set(schema["required"]) == {"city", "date"}
    assert schema["additionalProperties"] is False
```

---

## P0-2：thinking 参数映射仍然不符合当前官方接口

DeepSeek 当前 thinking 文档使用：

```python id="o9j2cv"
extra_body={"thinking": {"type": "enabled"}}
reasoning_effort="high" | "max"
```

同时说明 thinking 模式下 `temperature`、`top_p`、`presence_penalty`、`frequency_penalty` 会被忽略。([DeepSeek API Docs][5])

当前代码在 `_apply_thinking_mode()` 里仍然会构造：

```python id="zcp632"
{"thinking": {"type": thinking_mode, "budget_tokens": 2048}}
```

而且测试还明确断言 `thinking_mode="max"` 会生成：

```python id="f10rsq"
{"thinking": {"type": "max"}}
```

这和官方当前接口不一致。([GitHub][6])

### 影响

这会导致：

```text id="ol8tx2"
1. max thinking 可能被错误传成 thinking.type=max
2. reasoning_effort 没有作为一等参数建模
3. 测试锁定了错误行为
4. 未来 API 兼容性风险很高
```

### 正确设计

应该改成：

```python id="5yo90m"
@dataclass
class ThinkingConfig:
    enabled: bool = True
    reasoning_effort: Literal["high", "max"] | None = None
```

请求参数应生成：

```python id="3x603s"
if config.enabled:
    extra_body["thinking"] = {"type": "enabled"}
    if config.reasoning_effort:
        params["reasoning_effort"] = config.reasoning_effort
else:
    extra_body["thinking"] = {"type": "disabled"}
```

禁止继续生成：

```python id="f148hp"
{"thinking": {"type": "max"}}
```

除非 DeepSeek 官方未来明确支持。

---

## P0-3：非流式 tool call 的 reasoning 保留修了，但仍有 Reasoning Insights 注入问题

作者确实修复了一个关键点：非流式 tool call 分支现在会完整保留 `response.reasoning_content`，并且注释也说明必须完整保留，不能压缩。([GitHub][6])

这是好的。

但是 runtime 仍然会在拿到 reasoning 后，把 `harvest_thoughts()` 结果作为新的 user message 插入：

```python id="hjqsz7"
messages.append({
    "role": "user",
    "content": f"[Reasoning Insights]\n{insight}",
})
```

对应代码路径仍然存在。([GitHub][6])

### 为什么仍然危险

这次更新后，它不一定直接破坏 `assistant(tool_calls)` 后紧跟 `tool` 的 adjacency；但它仍然有几个严重问题：

```text id="odn5c2"
1. 把模型自身 reasoning 洞察伪装成 user message，破坏消息时间线
2. 可能把内部推理摘要回灌给模型，污染后续上下文
3. 破坏 DeepSeek cache 前缀稳定性
4. 增加 reasoning 泄漏风险
5. 与官方“reasoning_content 作为 assistant 字段回传”的协议语义不一致
```

DeepSeek 官方要求 tool call 场景下 assistant message 应包含 `content`、`reasoning_content` 和 `tool_calls`，随后才是对应 tool messages。([DeepSeek API Docs][7])

### 正确做法

`harvest_thoughts()` 可以保留，但只能进入 trace/observability，不允许进入 messages：

```python id="v7lxgx"
trace.add_reasoning_summary(insight)
```

不要：

```python id="qd3zw2"
messages.append({"role": "user", "content": "[Reasoning Insights]..."})
```

### 应加测试

```python id="0sujco"
def test_reasoning_insights_not_injected_into_messages():
    result = runtime.chat("...", tools=[...], thinking=True)
    assert not any(
        msg["role"] == "user" and "[Reasoning Insights]" in msg["content"]
        for msg in runtime.messages
    )
```

---

## P0-4：没有真正的 DeepSeek protocol state machine

仓库现在有 `state.py`，里面定义了 `StepKind`、`RunState`、pending tool calls 等状态结构。([GitHub][8])

但它不是一个真正的 DeepSeek protocol validator。

缺失的是：

```text id="9v7911"
1. validate_deepseek_messages()
2. assistant tool_calls 必须紧跟 tool results 的检查
3. tool_call_id 顺序检查
4. thinking tool call 必须带 reasoning_content 的检查
5. 模型请求前统一 validate_before_model_request()
```

当前更像“运行状态记录”，不是“协议状态机”。

### 必须补

```python id="697xzh"
def validate_deepseek_messages(messages: list[dict]) -> None:
    for i, msg in enumerate(messages):
        if msg["role"] == "assistant" and msg.get("tool_calls"):
            if "reasoning_content" not in msg:
                raise DeepSeekProtocolError(...)

            for expected_id, next_msg in ...:
                if next_msg["role"] != "tool":
                    raise DeepSeekProtocolError(...)
                if next_msg["tool_call_id"] != expected_id:
                    raise DeepSeekProtocolError(...)
```

---

## P0-5：JSON arguments 修复只覆盖部分路径，streaming/batch 仍会吞成 `{}`

作者修了非流式 client 的一部分：现在 `client.py` 解析 tool call arguments 失败时，不再设置 `{}`，而是把 raw string 放到 `arguments` 字段里。([GitHub][9])

这是进步。

但当前 `ToolCall` 类型没有独立的 `raw_arguments` 和 `parse_error` 字段，而是把 `arguments` 定义成 `dict | str`。([GitHub][10])

这会带来 API 语义混乱：

```text id="0h6gvo"
arguments 是 dict 时表示已解析
arguments 是 str 时表示原始坏 JSON
parse_error 丢失
调用方必须猜 arguments 类型
runtime 可能重新 json.dumps，导致历史消息失真
```

更关键的是，streaming 和 batch 路径仍然有旧问题：

```python id="bkka71"
except JSONDecodeError:
    parsed_args = {}
```

streaming tool call end 路径和 fallback 路径仍会把坏 JSON 变 `{}`。([GitHub][6])

batch 本地工具执行路径也仍然在 JSON 解析失败时设置 `{}`。([GitHub][6])

### 影响

```text id="p3ham8"
1. 非流式看似修了，但 streaming/batch 仍会丢参数
2. repair pipeline 在这些路径拿不到 raw JSON
3. 工具可能以空参数执行，造成误行为
4. debug 时无法知道原始模型输出是什么
```

### 必须改成统一 ToolCall 模型

```python id="vfjp4w"
@dataclass
class ToolCall:
    id: str
    name: str
    raw_arguments: str
    arguments: dict[str, Any] | None
    parse_error: str | None
```

所有入口必须统一调用：

```python id="4a830e"
parse_tool_call(raw_tool_call) -> ToolCall
```

禁止任何地方再出现：

```python id="kr34g8"
except JSONDecodeError:
    parsed_args = {}
```

---

## P0-6：PolicyEngine 有了，但没有可靠接入 ToolExecutor 主路径

这是安全相关的最大问题。

仓库现在有 `PolicyEngine`，`authorize_with_context()` 也能检查：

```text id="mtzbz1"
dangerous_tools_enabled
max_risk
capabilities
requires_approval
```

这些设计方向是对的。([GitHub][11])

但是当前 `ToolExecutor` 的主执行路径里，没有看到强制调用 `PolicyEngine.authorize_with_context()` 的逻辑。它更多是在执行参数修复、coercion、timeout、调用函数、wrap 输出、记录 audit。最后 audit 里甚至直接写 `policy_decision="allowed"`。([GitHub][12])

`execute_batch()` 里如果工具没有 policy，还会默认构造一个 read-safe policy 并并发执行。([GitHub][12])

### 影响

README 可以说有 policy engine，但如果 executor 不强制执行，它就是“旁路安全模块”。

风险包括：

```text id="61e6jv"
1. 用户以为危险工具默认受控，实际可能直接执行
2. requires_approval 可能只是返回一个字段，而不是阻止执行
3. 无 policy 的工具被默认当成 safe read
4. capability/max_risk/dangerous_tools_enabled 没有成为统一执行门
```

### 必须修复

ToolExecutor 执行前必须：

```python id="qfmjpa"
decision = policy_engine.authorize_with_context(tool.policy, run_context)

if not decision.allowed:
    return ToolExecutionResult(
        ok=False,
        error=decision.reason,
        error_type="policy_denied",
    )
```

如果：

```python id="t7tp7j"
decision.requires_approval
```

则必须返回：

```python id="m65d3b"
HumanApprovalRequired
```

不能继续执行工具。

默认策略应该是：

```text id="re6d2m"
无 policy 的 user-defined tool => deny 或只能在 explicit_trusted=True 时执行
危险工具 => dangerous_tools_enabled=True + capability + max_risk 同时满足
```

---

## P0-7：Balance 类型 bug 仍未修

这个问题非常直接。

`BalanceInfo.total_balance` 仍然是 `str`。([GitHub][13])

但 agent 里仍然有：

```python id="oea7lq"
if bal.total_balance <= 0:
    ...
f"¥{bal.total_balance:.2f}"
```

也就是把字符串当数字比较和格式化。([GitHub][14])

### 结果

启用 balance check 时，仍然可能直接：

```text id="7yzi8n"
TypeError: '<=' not supported between instances of 'str' and 'int'
```

或格式化失败。

### 修复

```python id="23wzbc"
from decimal import Decimal

@dataclass
class BalanceInfo:
    total_balance: Decimal
    granted_balance: Decimal
    topped_up_balance: Decimal
```

解析 API 返回时：

```python id="b27i7i"
total_balance = Decimal(raw["total_balance"])
```

缓存 key 不应使用裸 API key，应改成：

```python id="al5vr4"
cache_key = sha256(api_key.encode()).hexdigest()
```

---

# 3. P1 问题：生产级前必须修

---

## P1-1：FIM 仍不符合官方调用方式

当前 FIM 模块已经把 base URL 设置到了 beta，这是好的。

但是它仍然在 `_build_fim_prompt()` 里手工拼：

```text id="g8vy2m"
<|fim_begin|>{prefix}<|fim_hole|>{suffix}<|fim_end|>
```

并把这个作为 prompt 传给 completions。

DeepSeek 官方 FIM 文档当前示例是：

```python id="4mko8t"
client.completions.create(
    model="deepseek-v4-pro",
    prompt=prefix,
    suffix=suffix,
    max_tokens=128,
)
```

并明确 FIM max tokens 为 4K，beta base URL。

当前代码也没有看到 `max_tokens <= 4096` 的硬限制。

### 修复

```python id="mk7gkt"
response = client.completions.create(
    model=model,
    prompt=prefix,
    suffix=suffix,
    max_tokens=min(max_tokens, 4096),
)
```

不要手工拼 special tokens，除非官方文档重新要求。

---

## P1-2：timeout 仍然不是真正的生产级 timeout

当前 ToolExecutor 的 timeout 是：

```python id="783k2r"
with ThreadPoolExecutor(max_workers=1) as executor:
    future = executor.submit(...)
    result = future.result(timeout=timeout)
```

这不是生产级工具 timeout。([GitHub][12])

原因：

```text id="h65mpn"
1. Python 线程无法被安全强杀
2. future.result(timeout=...) 超时后，底层函数可能继续运行
3. with ThreadPoolExecutor 退出时默认会等待线程结束
4. 对网络、文件、外部副作用工具不可靠
```

agent 层也有类似线程 timeout。([GitHub][14])

### 修复建议

工具 timeout 分三层：

| 工具类型                          | 执行方式                                 |
| ----------------------------- | ------------------------------------ |
| pure read-only quick function | thread 可接受                           |
| network/write/destructive     | subprocess + timeout                 |
| code_exec                     | container / sandbox                  |
| external API write            | idempotency key + no automatic retry |

最低限度也要：

```python id="7cndm4"
future.cancel()
executor.shutdown(wait=False, cancel_futures=True)
```

但这仍不能杀死正在运行的 Python 线程。生产级需要 process/container。

---

## P1-3：SSRF 防护有雏形，但不够强

当前 `validate_url()` 会检查 scheme、hostname、localhost、metadata host、allowed domains 和 private IP，这是好方向。

但 `_is_private_ip()` 只取 `socket.getaddrinfo(host, None)[0]` 的第一个解析结果。

这有几个问题：

```text id="r8y90s"
1. 多 A/AAAA 记录时，只检查第一个 IP
2. DNS round-robin / DNS rebinding 风险仍在
3. DNS 解析失败时返回 False，可能被视为安全
4. IPv6 私网 fc00::/7 没有完整覆盖
```

### 修复

```python id="rpg9sr"
infos = socket.getaddrinfo(host, None)

for info in infos:
    ip = ipaddress.ip_address(info[4][0])
    if is_private_or_metadata(ip):
        raise SSRFError(...)
```

DNS 解析失败应默认 deny，除非调用方明确允许 unresolved host。

---

## P1-4：tool argument repair 对危险工具的门控过弱

当前 executor 对 repaired arguments 有一些风险门控，但阈值是 `0.85`，且主要对某种 repair level 做限制。([GitHub][12])

后续 `coerce_arguments()` 如果改变了参数，也会把 `repaired=True`，但没有看到第二次高风险门控。([GitHub][12])

### 风险

例如 destructive tool 的参数从：

```text id="l73a5c"
/tmp/a
```

被 coercion 或 repair 成：

```text id="d6g5z3"
/prod/data
```

如果没有高置信度和人工确认，不能执行。

### 建议

危险工具只允许：

```text id="py1rfw"
1. 无修复 arguments
2. 纯语法修复且 confidence >= 0.95
3. 或人工确认
```

所有 coercion 后也必须重新 policy check。

---

## P1-5：cache metrics 修了一半，下游仍旧

client 已经兼容当前 DeepSeek cache usage 字段：

```text id="bb0qnl"
prompt_cache_hit_tokens
prompt_cache_miss_tokens
```

也兼容旧的 `prompt_tokens_details.cached_tokens`。([GitHub][9])

这是好修复。

但 agent 下游仍然主要读取：

```python id="qpxe2b"
prompt_tokens_details.cached_tokens
```

没有统一使用 hit/miss metrics 结构。([GitHub][14])

### 应改成统一模型

```python id="0xxjm7"
@dataclass
class CacheMetrics:
    hit_tokens: int
    miss_tokens: int

    @property
    def hit_ratio(self) -> float:
        ...
```

所有 cost、trace、report 统一用这个模型。

---

# 4. P2 问题：影响长期质量

---

## P2-1：README 仍然过度营销

README 当前开头就写：

```text id="c31b0x"
DeepSeek-native | Production-grade security | 620+ tests
```

并在 feature table 里写 CacheCompiler “90%+ hit”、Policy Engine、Sandboxed Filesystem、Threat Detection、Cost Guard 等。([GitHub][1])

但从当前代码看：

```text id="o3vmzx"
strict mode 没做实
policy 没强制接 executor
timeout 不是真 timeout
FIM 不符合官方方式
balance 仍有 TypeError
streaming/batch JSON 仍吞错
```

因此 README 的 production-grade 说法不成立。

建议改成：

```text id="7ce0yx"
Security hardening in progress
Policy primitives
Experimental sandbox
Best-effort SSRF protection
Cache telemetry
```

不要写：

```text id="gwg3n3"
production-grade
enterprise-grade
90%+ guaranteed hit
```

除非 CI/eval 报告能支撑。

---

## P2-2：默认模型仍然是 `deepseek-chat`

README quick start 仍然写：

```python id="g1ao90"
model="deepseek-chat"
```

([GitHub][1])

但当前 DeepSeek 官方 thinking/FIM 示例都已经使用 `deepseek-v4-pro`，并且官方文档已经围绕 V4 flash/pro 展开。([DeepSeek API Docs][5])

建议：

```python id="tji2tp"
model="deepseek-v4-flash"
```

reasoning 示例：

```python id="tdenaz"
model="deepseek-v4-pro"
```

---

## P2-3：测试数量增加，但部分测试在锁定错误行为

例如 thinking 测试断言：

```python id="felthp"
thinking_mode="max" -> {"thinking": {"type": "max"}}
```

这和官方当前接口不一致。([GitHub][15])

strict checker 测试也把缺少 `additionalProperties: false` 的 schema 判为 valid，这不符合 strict 目标。([GitHub][16])

### 建议

测试应该改成“锁定官方正确行为”，而不是“锁定当前实现”。

---

# 5. 作者这次修复的真实质量评估

## 5.1 修对了什么

### A. 非流式 reasoning preservation

这个确实是有效修复。当前 tool call 分支完整保留 `reasoning_content`，这比之前压缩回传好很多。([GitHub][6])

### B. 非流式 JSON raw string

client 不再把 malformed JSON 直接变 `{}`，这是正确方向。([GitHub][9])

### C. 安全基础模块

PolicyEngine、safe_join、validate_url、redaction、wrap_untrusted 都有实现雏形。([GitHub][11])

### D. cache hit/miss 兼容

client usage 字段支持了当前 DeepSeek 的 cache hit/miss token，这是好事。([GitHub][9])

---

## 5.2 修得不完整的地方

| 问题                          | 当前修复程度 | 评价                                        |
| --------------------------- | -----: | ----------------------------------------- |
| reasoning_content tool call |    70% | 非流式主路径修了，但缺 protocol state machine        |
| malformed JSON              |    45% | 非流式 client 修了，streaming/batch 没修          |
| strict tools                |    15% | 有 checker，但 registry 没 strict，checker 还太弱 |
| safety                      |    45% | 有模块，但执行主路径没有强制 gate                       |
| timeout                     |    25% | 有 timeout 参数，但不是可靠中断                      |
| FIM                         |    35% | beta URL 对了，payload 仍错                    |
| balance                     |     0% | 原 bug 仍在                                  |
| README 可信度                  |    40% | 声明仍超前                                     |

---

# 6. 建议的下一轮修复优先级

我建议作者不要继续加新功能，而是按下面顺序修。

---

## PR 1：Strict tools 真正落地

交付：

```text id="8b6lci"
1. ToolRegistry.to_deepseek_tools(strict=True) 输出 strict:true
2. DeepSeekStrictSchemaCompiler
3. required 全字段
4. additionalProperties=false
5. strict 使用 beta base URL
6. strict checker 把 schema 不合规作为 error
```

验收：

```text id="3irn4u"
strict=True 时生成的 tools 能通过本地 checker
测试覆盖 missing required、missing additionalProperties、unsupported keywords
```

---

## PR 2：ThinkingConfig 重构

交付：

```text id="ym3qqb"
1. 禁止 thinking.type=max
2. 使用 reasoning_effort=max
3. 移除 budget_tokens，除非官方支持
4. 更新测试
5. README 更新 V4 模型示例
```

---

## PR 3：Protocol state machine

交付：

```text id="9896qz"
1. validate_deepseek_messages()
2. assistant tool_calls 后必须紧跟 tool messages
3. tool_call_id 顺序检查
4. reasoning_content 必须完整保留
5. 删除 Reasoning Insights message 注入
6. insights 只进入 trace
```

---

## PR 4：统一 ToolCall raw arguments

交付：

```text id="euiobx"
1. ToolCall.raw_arguments
2. ToolCall.arguments
3. ToolCall.parse_error
4. 所有非流式/流式/batch 路径统一 parse
5. 禁止 JSONDecodeError -> {}
```

---

## PR 5：PolicyEngine 强制接入 ToolExecutor

交付：

```text id="2wx4c9"
1. executor.execute() 第一阶段执行 policy authorize
2. no policy 默认 deny 或 trusted-only
3. requires_approval 不得继续执行
4. repaired/coerced args 后重新 policy check
5. audit 记录真实 decision
```

---

## PR 6：FIM 官方化

交付：

```text id="0i0lpo"
1. beta base URL
2. prompt=prefix
3. suffix=suffix
4. max_tokens <= 4096
5. 删除 special token prompt builder
```

---

## PR 7：Balance Decimal 修复

交付：

```text id="zle5hp"
1. Decimal balance
2. agent 比较/格式化修复
3. cache key hash 化
4. 增加 balance check 测试
```

---

## PR 8：Timeout 与 sandbox 降级声明

交付：

```text id="c8polh"
1. README 中 per-tool timeout 改成 best-effort thread timeout
2. 对 write/network/destructive 工具引入 process timeout
3. code_exec 默认禁用
4. container sandbox 标记 experimental，除非真的完整实现
```

---

# 7. 当前是否可以生产使用？

我的判断：

```text id="v0o69i"
不能作为 production-grade agent runtime 使用。
可以作为 DeepSeek agent 框架的 hardening beta / 技术原型继续迭代。
```

可以用于：

```text id="dj2hju"
1. 学习 DeepSeek tool calling
2. 内部非关键 demo
3. 受控环境 PoC
4. 只使用 read-only 工具的小型实验
```

不建议用于：

```text id="8qydld"
1. 有写操作的生产 agent
2. 自动执行网络请求的 agent
3. 文件系统写入/删除 agent
4. 需要 strict tool calling 保证的系统
5. 需要 FIM 精准补全的生产代码工具
6. 依赖 balance/cost guard 的线上系统
```

---

# 8. 最终审计结论

作者这次更新是有价值的，方向也明显受到了之前问题的影响：

```text id="2fgg3k"
reasoning_content 保留开始修了
tool argument raw 保留开始修了
安全模块开始补了
cache usage 字段开始跟进了
测试开始增加了
```

但是现在的问题是：**很多能力停留在“模块存在”或“部分路径修复”，还没有形成端到端可靠闭环。**

最典型的例子：

```text id="3e6dkx"
有 PolicyEngine，但 ToolExecutor 没有强制 gate
有 strict checker，但 ToolRegistry 不输出 strict:true
有 JSON repair，但 streaming/batch 仍吞成 {}
有 timeout，但线程 timeout 不是真中断
有 FIM beta URL，但仍用错误 prompt 形式
```

所以我会给当前版本一句话评价：

> **SeekFlow v0.2.0 是一次真实的 hardening 更新，但还不是 production-grade；它已经从“有问题的原型”进化到“有潜力的安全强化 beta”，下一步必须从“功能存在”走向“关键路径强制正确”。**

如果作者把上述 P0/P1 全部修完，这个框架才有资格宣称：

```text id="3whhnc"
DeepSeek-native
safe by default
strict-tool-ready
production-minded
```

但现在还不能。

[1]: https://github.com/WYZAAACCC/SeekFlow "GitHub - WYZAAACCC/SeekFlow: DeepSeek-native agent framework with production-grade reliability · GitHub"
[2]: https://api-docs.deepseek.com/guides/tool_calls "Tool Calls | DeepSeek API Docs"
[3]: https://github.com/WYZAAACCC/SeekFlow/blob/main/src/seekflow/tools/registry.py "SeekFlow/src/seekflow/tools/registry.py at main · WYZAAACCC/SeekFlow · GitHub"
[4]: https://github.com/WYZAAACCC/SeekFlow/blob/main/src/seekflow/tools/strict.py "SeekFlow/src/seekflow/tools/strict.py at main · WYZAAACCC/SeekFlow · GitHub"
[5]: https://api-docs.deepseek.com/guides/thinking_mode "Thinking Mode | DeepSeek API Docs"
[6]: https://github.com/WYZAAACCC/SeekFlow/blob/main/src/seekflow/runtime.py "SeekFlow/src/seekflow/runtime.py at main · WYZAAACCC/SeekFlow · GitHub"
[7]: https://api-docs.deepseek.com/guides/fim_completion "FIM Completion (Beta) | DeepSeek API Docs"
[8]: https://github.com/WYZAAACCC/SeekFlow/blob/main/src/seekflow/state.py "SeekFlow/src/seekflow/state.py at main · WYZAAACCC/SeekFlow · GitHub"
[9]: https://github.com/WYZAAACCC/SeekFlow/blob/main/src/seekflow/client.py "SeekFlow/src/seekflow/client.py at main · WYZAAACCC/SeekFlow · GitHub"
[10]: https://github.com/WYZAAACCC/SeekFlow/blob/main/src/seekflow/types.py "SeekFlow/src/seekflow/types.py at main · WYZAAACCC/SeekFlow · GitHub"
[11]: https://github.com/WYZAAACCC/SeekFlow/blob/main/src/seekflow/policy.py "SeekFlow/src/seekflow/policy.py at main · WYZAAACCC/SeekFlow · GitHub"
[12]: https://github.com/WYZAAACCC/SeekFlow/blob/main/src/seekflow/tools/executor.py "SeekFlow/src/seekflow/tools/executor.py at main · WYZAAACCC/SeekFlow · GitHub"
[13]: https://github.com/WYZAAACCC/SeekFlow/blob/main/src/seekflow/balance.py "SeekFlow/src/seekflow/balance.py at main · WYZAAACCC/SeekFlow · GitHub"
[14]: https://github.com/WYZAAACCC/SeekFlow/blob/main/src/seekflow/agent/agent.py "SeekFlow/src/seekflow/agent/agent.py at main · WYZAAACCC/SeekFlow · GitHub"
[15]: https://github.com/WYZAAACCC/SeekFlow/blob/main/tests/test_thinking.py "SeekFlow/tests/test_thinking.py at main · WYZAAACCC/SeekFlow · GitHub"
[16]: https://github.com/WYZAAACCC/SeekFlow/blob/main/tests/test_strict_checker.py "SeekFlow/tests/test_strict_checker.py at main · WYZAAACCC/SeekFlow · GitHub"
