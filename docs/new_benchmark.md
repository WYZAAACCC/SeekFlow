下面这份我按“**可以直接复制给 Claude Code 执行**”的标准来写。它不是一份普通建议，而是一份完整的工程落地说明书：目标、架构、目录、文件、工具、fixture repo、测试、评分、Runner、验收标准、分阶段提交顺序都给出来。

先给结论：**不要再继续用“更复杂的报告型任务”证明 thinking。** 最新 README 已经很清楚地暴露了这一点：当前 6 场景里，三类 extreme reasoning 场景——三难困境、因果追踪、谈判僵局——所有框架几乎都在 8.8–8.9 之间，README 也直接写明 “v4-pro 裸推理已足够强，thinking 模式未带来质量增益，仅增加延迟”。([GitHub][1])
所以真正能证明 thinking 的场景必须从“写报告”转成“**执行型工程闭环任务**”：读代码、定位跨文件 bug、修改代码、运行测试、失败后复盘修正、通过隐藏测试、不能破坏安全策略。只有这种任务才会让 thinking 的规划、假设验证、错误恢复、约束权衡能力体现出来。

---

# 交给 Claude Code 的总任务

请在 SeekFlow 仓库中新增一个独立 benchmark，暂名：

```text
benchmarks/thinking_stress_v1/
```

这个 benchmark 的目标不是继续比较“报告写得好不好”，而是专门验证：

```text
SeekFlow stable + thinking
是否在高复杂度、多约束、可执行、可失败、需回归验证的工程修复任务中，
显著优于 stable-no-thinking / fast-no-thinking / LangChain / CrewAI。
```

这个 benchmark 应该围绕 SeekFlow 最新 README 的核心能力设计：DeepSeek thinking management、Policy Engine、ToolPolicy、Path sandbox、SSRF protection、Secret redaction、Untrusted Content、Per-tool timeout、Audit Trail、Prompt Cache Compiler、JSON repair、Runner isolation 等。README 目前把 SeekFlow 定位为 “DeepSeek-native zero-trust tool gateway”，并强调它是围绕 thinking mode、prompt caching、JSON repair、FIM 构建，而不是 generic OpenAI wrapper。([GitHub][1])

---

# 一、为什么必须新建 benchmark，而不是继续扩展 fair_comparison_v2

当前 `fair_comparison_v2` 已经经历过一轮问题：早期 stable 因真实 web_search 并发、工具失败、输出截断、提示词铁律、单位混淆等问题被反向惩罚；这些问题在用户原始记录中已有明确证据，例如 Stable supply 场景 R1/R2 分数低至 5.2/5.5，而 R3 web_search 成功后又升到 8.2，说明旧基准强受工具可用性影响。
最新 README 中，v0.3.7 已经把主 benchmark 改成 6 场景、fixture search、blind LLM judge + programmatic compliance judge，并报告 Stable 综合 8.9、Fast 7.9、CrewAI 7.9、LangChain 7.8。([GitHub][1])

但 README 同时也承认：在三个 extreme reasoning 场景中，thinking 没有拉开差距，Stable 8.9、Fast 8.8、LangChain 8.9、CrewAI 8.9，差异几乎为零。([GitHub][1])
这说明 `trilemma / causal forensics / negotiation deadlock` 仍然不够“工程闭环”，v4-pro 不开 thinking 也能靠强语言推理完成。新 benchmark 必须换一种范式：

```text
旧范式：给信息 → 调工具 → 写报告 → LLM judge 评分
新范式：给坏仓库 → 读代码 → 跑测试 → 定位根因 → 修改代码 → 回归验证 → 隐藏测试验收
```

---

# 二、Benchmark 总体设计

新 benchmark 名称：

```text
Thinking Stress Benchmark v1
```

核心场景名称：

```text
runtime_repair_lab
```

任务类型：

```text
企业级 Agent Runtime 安全与协议修复任务
```

被测对象：

```text
同一个 v4-pro 模型，在不同 agent 编排策略下，是否能完成复杂代码修复闭环。
```

对比组至少包括：

```text
1. SeekFlow stable-thinking
   mode="stable", thinking=True, max_steps=30

2. SeekFlow stable-no-thinking
   mode="stable", thinking=False, max_steps=30

3. SeekFlow fast-no-thinking
   mode="fast", thinking=False, max_steps=12 或 16

4. LangChain no-thinking
   thinking disabled，使用同一组工具

5. CrewAI no-thinking 或 default
   如果无法可靠关闭 thinking，则标记为 adapter-limited，不进入 thinking 主结论
```

这里一定要加入 `stable-no-thinking`，否则无法区分：

```text
stable-thinking 优势到底来自 thinking，
还是来自 stable mode 的工程能力、max_steps、工具策略、cache、policy 等。
```

README 里也明确提到 SeekFlow 相比 LangChain/CrewAI 的差异不只是 thinking，还包括 JSON repair、Prompt cache stabilization、Circuit breaker、Policy Engine、Path sandbox、SSRF protection、Secret redaction 等。([GitHub][1])
因此必须把 `stable-thinking` 和 `stable-no-thinking` 拆开。

---

# 三、目录结构设计

请新增如下目录：

```text
benchmarks/thinking_stress_v1/
├── __init__.py
├── README.md
├── scenario.py
├── tools.py
├── runner.py
├── agents.py
├── scorer.py
├── llm_judge.py
├── report.py
├── contracts.py
├── output/
│   └── .gitkeep
├── fixture_repo/
│   ├── pyproject.toml
│   ├── README.md
│   ├── src/
│   │   └── mini_agent_runtime/
│   │       ├── __init__.py
│   │       ├── messages.py
│   │       ├── tool_runtime.py
│   │       ├── security.py
│   │       ├── redaction.py
│   │       ├── cache_cost.py
│   │       ├── policy.py
│   │       └── json_repair.py
│   └── tests/
│       ├── test_messages.py
│       ├── test_tool_runtime.py
│       ├── test_security.py
│       ├── test_redaction.py
│       ├── test_cache_cost.py
│       ├── test_policy.py
│       └── test_json_repair.py
└── hidden_tests/
    ├── test_hidden_security.py
    ├── test_hidden_messages.py
    ├── test_hidden_redaction.py
    ├── test_hidden_cache_cost.py
    └── test_hidden_no_test_tampering.py
```

注意：`hidden_tests/` 不应该被 agent 的 `list_files` / `read_file` / `search_code` 工具看到。它只由 `scorer.py` 在最终验收时运行。这样可以防止 agent 只针对公开测试硬编码。

---

# 四、Fixture Repo 的功能定位

`fixture_repo/` 是一个故意写坏的小型 Agent Runtime。它模拟 SeekFlow 的关键能力，但不要直接复制 SeekFlow 源码，避免 benchmark 太重、太依赖真实项目结构。它应该包含 7 类真实工程问题：

```text
1. DeepSeek thinking/tool-call 多轮消息协议 bug
2. 并行 tool result 顺序 bug
3. Path sandbox 绕过 bug
4. SSRF 防护绕过 bug
5. Secret redaction 不完整 bug
6. Prompt cache / cost accounting bug
7. Policy deny-by-default / JSON repair 安全 bug
```

这些问题都与 README 当前强调的框架能力直接相关：README 的安全架构图里列出了 Thinking mode / Cache、safe_join / validate_url、redact_secrets、UntrustedContent、ProcessRunner、ContainerRunner、Audit trail、DeepSeek API 等层次。([GitHub][1])
Security levels 文档也明确 Level 2 支持 path traversal blocked via `safe_join()`、limited network access with SSRF validation、ProcessRunner hard timeout、schema validation with hallucination defense；Level 3 candidate 进一步支持 ToolManifest、ExternalToolRunner、MCPGateway、EgressGateway、SecretBroker、DurableAuditStore。([GitHub][2])

---

# 五、Fixture Repo 中要故意埋入的 bug

下面是建议 Claude Code 直接实现的初始“坏代码”。

## 5.1 `messages.py`：DeepSeek thinking/tool-call 消息协议 bug

目标 bug：

```text
当 assistant message 同时包含 tool_calls 和 reasoning_content 时，
下一轮 messages 构造丢失 reasoning_content。
```

为什么它能体现 thinking：

```text
不开 thinking 的模式不会产生 reasoning_content，或者不会依赖 reasoning_content。
开 thinking 的复杂多轮 tool call 场景必须正确维护它，否则协议、上下文连续性、后续工具计划都会出问题。
```

坏代码示例：

```python
# fixture_repo/src/mini_agent_runtime/messages.py

from __future__ import annotations

from typing import Any


def build_next_messages(history: list[dict[str, Any]], tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Build next API messages after tool execution.

    BUG:
    - Drops reasoning_content from previous assistant messages.
    - Does not preserve tool_call_id order reliably.
    """
    messages: list[dict[str, Any]] = []

    for msg in history:
        if msg.get("role") == "assistant":
            copied = {
                "role": "assistant",
                "content": msg.get("content", ""),
            }
            if "tool_calls" in msg:
                copied["tool_calls"] = msg["tool_calls"]
            # BUG: reasoning_content omitted
            messages.append(copied)
        else:
            messages.append(dict(msg))

    for result in tool_results:
        messages.append({
            "role": "tool",
            "tool_call_id": result["tool_call_id"],
            "content": result["content"],
        })

    return messages
```

公开测试：

```python
# fixture_repo/tests/test_messages.py

from mini_agent_runtime.messages import build_next_messages


def test_preserves_reasoning_content_when_assistant_has_tool_calls():
    history = [
        {"role": "user", "content": "analyze"},
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "I need to call inspect_file first.",
            "tool_calls": [
                {"id": "call_1", "function": {"name": "inspect_file", "arguments": "{}"}}
            ],
        },
    ]
    tool_results = [{"tool_call_id": "call_1", "content": '{"ok": true}'}]

    messages = build_next_messages(history, tool_results)

    assistant = messages[1]
    assert assistant["reasoning_content"] == "I need to call inspect_file first."
    assert assistant["tool_calls"][0]["id"] == "call_1"
```

隐藏测试要检查：

```text
1. reasoning_content 为空时不应添加空字段
2. 多个 assistant 消息时都要保留
3. tool result 不能插到 assistant 前面
4. 不得把 reasoning_content 拼进 content
```

最后修复应是：

```python
if "reasoning_content" in msg and msg["reasoning_content"]:
    copied["reasoning_content"] = msg["reasoning_content"]
```

---

## 5.2 `tool_runtime.py`：并行工具返回顺序 bug

目标 bug：

```text
并行工具执行后按完成顺序返回，而不是按原始 tool_calls 顺序 / tool_call_id 对齐。
```

坏代码：

```python
# fixture_repo/src/mini_agent_runtime/tool_runtime.py

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable


def execute_parallel_tool_calls(
    tool_calls: list[dict[str, Any]],
    registry: dict[str, Callable[..., Any]],
) -> list[dict[str, Any]]:
    """
    Execute tool calls concurrently.

    BUG:
    Returns results by completion order, causing unstable message ordering.
    """
    def run_one(call: dict[str, Any]) -> dict[str, Any]:
        name = call["name"]
        args = call.get("args", {})
        result = registry[name](**args)
        return {
            "tool_call_id": call["id"],
            "name": name,
            "content": result,
        }

    results = []
    with ThreadPoolExecutor(max_workers=min(8, len(tool_calls))) as pool:
        futures = [pool.submit(run_one, call) for call in tool_calls]
        for fut in as_completed(futures):
            results.append(fut.result())

    return results
```

公开测试：

```python
# fixture_repo/tests/test_tool_runtime.py

import time

from mini_agent_runtime.tool_runtime import execute_parallel_tool_calls


def test_parallel_results_preserve_tool_call_order():
    def slow(value: str, delay: float):
        time.sleep(delay)
        return value

    calls = [
        {"id": "call_a", "name": "slow", "args": {"value": "A", "delay": 0.05}},
        {"id": "call_b", "name": "slow", "args": {"value": "B", "delay": 0.01}},
        {"id": "call_c", "name": "slow", "args": {"value": "C", "delay": 0.02}},
    ]

    out = execute_parallel_tool_calls(calls, {"slow": slow})

    assert [x["tool_call_id"] for x in out] == ["call_a", "call_b", "call_c"]
    assert [x["content"] for x in out] == ["A", "B", "C"]
```

正确修复方式：

```python
indexed_futures = {
    pool.submit(run_one, call): i
    for i, call in enumerate(tool_calls)
}
ordered = [None] * len(tool_calls)
for fut in as_completed(indexed_futures):
    ordered[indexed_futures[fut]] = fut.result()
return ordered
```

这个问题很适合 thinking，因为它不是语法问题，而是“并发执行”和“协议顺序”之间的隐性约束。不开 thinking 的模型容易只改成串行执行，虽然通过顺序测试，但破坏并行能力。隐藏测试要检查函数仍然并行，比如总耗时不能接近所有 delay 之和。

---

## 5.3 `security.py`：Path sandbox + SSRF 双漏洞

目标 bug：

```text
safe_join 只做字符串 startswith，没有处理 URL 编码、symlink、resolve。
validate_url 只挡 localhost 字符串，没有挡私有 IP、IPv6、本地网段、metadata endpoint、整数 IP。
```

坏代码：

```python
# fixture_repo/src/mini_agent_runtime/security.py

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from urllib.parse import urlparse


def safe_join(workspace_root: str, user_path: str) -> Path:
    """
    Join user path inside workspace.

    BUG:
    - String prefix check is unsafe.
    - Does not decode percent-encoded traversal.
    - Does not resolve symlinks.
    """
    root = Path(workspace_root)
    candidate = root / user_path
    if not str(candidate).startswith(str(root)):
        raise ValueError("path escapes workspace")
    return candidate


def validate_url(url: str, allowed_domains: set[str] | None = None) -> bool:
    """
    Validate URL for network tools.

    BUG:
    - Only checks scheme and literal localhost.
    - Does not block private IPs, metadata IP, IPv6 loopback, decimal IP.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False

    host = parsed.hostname or ""
    if "localhost" in host or host.startswith("127."):
        return False

    if allowed_domains and host not in allowed_domains:
        return False

    return True
```

公开测试：

```python
# fixture_repo/tests/test_security.py

import os
from pathlib import Path

import pytest

from mini_agent_runtime.security import safe_join, validate_url


def test_safe_join_blocks_parent_traversal(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    with pytest.raises(ValueError):
        safe_join(str(root), "../secret.txt")


def test_safe_join_blocks_percent_encoded_traversal(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    with pytest.raises(ValueError):
        safe_join(str(root), "%2e%2e/secret.txt")


def test_validate_url_blocks_metadata_endpoint():
    assert validate_url("http://169.254.169.254/latest/meta-data") is False


def test_validate_url_allows_explicit_allowed_domain():
    assert validate_url("https://api.example.com/v1", {"api.example.com"}) is True


def test_validate_url_blocks_private_ip():
    assert validate_url("http://192.168.1.10/admin") is False
```

隐藏测试增加：

```text
http://2130706433/              # integer form of 127.0.0.1
http://0x7f000001/              # hex form
http://[::1]/
http://10.0.0.1/
http://172.16.0.1/
http://localhost.evil.com/      # 应该按 hostname 精确判断，不要误挡 allowed domain，但也不能误放 localhost
symlink escape:
workspace/link -> /tmp/outside
safe_join(workspace, "link/secret.txt") 应该拒绝
```

修复思路：

```python
from urllib.parse import unquote

def safe_join(workspace_root: str, user_path: str) -> Path:
    root = Path(workspace_root).resolve()
    decoded = unquote(user_path)
    candidate = (root / decoded).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ValueError("path escapes workspace")
    return candidate
```

`validate_url` 的修复要保守，至少做到：

```python
def _is_blocked_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )
```

同时支持解析常见 integer / hex IPv4。这个地方可以让 Claude Code 实现一个小 helper：

```python
def _parse_numeric_ipv4(host: str) -> ipaddress.IPv4Address | None:
    ...
```

---

## 5.4 `redaction.py`：Secret redaction 不完整

坏代码：

```python
# fixture_repo/src/mini_agent_runtime/redaction.py

from __future__ import annotations

import re


def redact_secrets(text: str) -> str:
    """
    Redact secrets from logs.

    BUG:
    Only redacts sk- style keys.
    """
    text = re.sub(r"sk-[A-Za-z0-9]{8,}", "sk-REDACTED", text)
    return text
```

公开测试：

```python
# fixture_repo/tests/test_redaction.py

from mini_agent_runtime.redaction import redact_secrets


def test_redacts_deepseek_key():
    text = "api_key=sk-1234567890abcdef"
    assert "1234567890abcdef" not in redact_secrets(text)


def test_redacts_bearer_token():
    text = "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456"
    out = redact_secrets(text)
    assert "abcdefghijklmnopqrstuvwxyz123456" not in out
    assert "Bearer" in out


def test_redacts_aws_access_key():
    text = "AWS key AKIAIOSFODNN7EXAMPLE leaked"
    assert "AKIAIOSFODNN7EXAMPLE" not in redact_secrets(text)


def test_redacts_jwt():
    token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.signaturevalue"
    assert token not in redact_secrets(token)
```

隐藏测试检查：

```text
1. 不要过度 redaction，把普通英文句子全替换
2. 多个 secret 同时出现都要替换
3. URL query 中的 token=xxx 也要替换
```

---

## 5.5 `cache_cost.py`：Prompt cache / cost accounting bug

坏代码：

```python
# fixture_repo/src/mini_agent_runtime/cache_cost.py

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class Usage:
    prompt_tokens: int
    cached_tokens: int
    completion_tokens: int


def build_cache_prefix(system_prompt: str, tools_schema: str) -> str:
    """
    BUG:
    Includes timestamp in prefix, destroying prompt cache.
    """
    return f"{time.time()}::{system_prompt}\nTOOLS:\n{tools_schema}"


def estimate_cost_cny(
    usage: Usage,
    input_price: float,
    cached_input_price: float,
    output_price: float,
) -> float:
    """
    BUG:
    Charges cached tokens at full input price.
    Prices are CNY per 1M tokens.
    """
    return (
        usage.prompt_tokens * input_price
        + usage.completion_tokens * output_price
    ) / 1_000_000
```

公开测试：

```python
# fixture_repo/tests/test_cache_cost.py

from mini_agent_runtime.cache_cost import Usage, build_cache_prefix, estimate_cost_cny


def test_cache_prefix_is_stable_for_same_inputs():
    a = build_cache_prefix("sys", '{"tools": []}')
    b = build_cache_prefix("sys", '{"tools": []}')
    assert a == b


def test_cost_charges_cached_tokens_at_cached_rate():
    usage = Usage(prompt_tokens=1000, cached_tokens=800, completion_tokens=200)
    cost = estimate_cost_cny(
        usage,
        input_price=1.74,
        cached_input_price=0.028,
        output_price=3.48,
    )
    expected = ((200 * 1.74) + (800 * 0.028) + (200 * 3.48)) / 1_000_000
    assert abs(cost - expected) < 1e-9
```

这个点很契合 README 里的 Prompt Cache Compiler 和 cache-aware cost tracking。README 中明确列出 Prompt cache stabilization、Balance/cost tracking 为 SeekFlow 相对 LangChain/CrewAI 的差异能力。([GitHub][1])

---

## 5.6 `policy.py`：默认放行 bug

坏代码：

```python
# fixture_repo/src/mini_agent_runtime/policy.py

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ToolPolicy:
    name: str
    capabilities: set[str]
    risk: str
    trusted: bool = False


def authorize_tool_call(
    tool_name: str,
    requested_capability: str,
    policies: dict[str, ToolPolicy],
) -> bool:
    """
    BUG:
    Missing policy defaults to allow.
    """
    policy = policies.get(tool_name)
    if policy is None:
        return True

    return requested_capability in policy.capabilities
```

公开测试：

```python
# fixture_repo/tests/test_policy.py

from mini_agent_runtime.policy import ToolPolicy, authorize_tool_call


def test_missing_policy_denied_by_default():
    assert authorize_tool_call("unknown_tool", "network", {}) is False


def test_capability_must_match():
    policies = {
        "read_file": ToolPolicy(
            name="read_file",
            capabilities={"filesystem.read"},
            risk="read",
            trusted=True,
        )
    }
    assert authorize_tool_call("read_file", "filesystem.read", policies) is True
    assert authorize_tool_call("read_file", "network", policies) is False
```

这也对齐 README 的 “no-policy deny-by-default” 和 Policy Engine 描述。README 中 v0.3.7 说明 Lv2 baseline 已包含 no-policy deny-by-default、runner minimum isolation 等安全基线。([GitHub][1])

---

## 5.7 `json_repair.py`：JSON repair 信心门控 bug

坏代码：

```python
# fixture_repo/src/mini_agent_runtime/json_repair.py

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class RepairResult:
    ok: bool
    value: dict[str, Any] | None
    confidence: float
    method: str


def repair_tool_args(raw: str, dangerous: bool = False) -> RepairResult:
    """
    BUG:
    Allows low-confidence repaired JSON for dangerous tools.
    """
    try:
        return RepairResult(True, json.loads(raw), 1.0, "native")
    except json.JSONDecodeError:
        pass

    fixed = raw.strip()
    fixed = fixed.replace("'", '"')
    if fixed.endswith(",}"):
        fixed = fixed[:-2] + "}"

    try:
        value = json.loads(fixed)
        return RepairResult(True, value, 0.6, "syntactic")
    except json.JSONDecodeError:
        return RepairResult(False, None, 0.0, "fail")
```

公开测试：

```python
# fixture_repo/tests/test_json_repair.py

from mini_agent_runtime.json_repair import repair_tool_args


def test_low_confidence_repair_allowed_for_safe_tool():
    r = repair_tool_args("{'path': 'README.md'}", dangerous=False)
    assert r.ok is True
    assert r.value == {"path": "README.md"}


def test_low_confidence_repair_denied_for_dangerous_tool():
    r = repair_tool_args("{'cmd': 'rm -rf /'}", dangerous=True)
    assert r.ok is False
```

这个点对应 README 的 JSON Repair Pipeline：README 中写到 JSON repair 是 confidence-gated，并且 dangerous tools 在低置信修复下应拒绝。([GitHub][1])

---

# 六、Agent 可用工具设计

不要给 agent 任意 shell。所有框架都必须使用同一组受控工具。新增 `benchmarks/thinking_stress_v1/tools.py`。

工具列表：

```text
init_workspace(case_id: str) -> dict
list_files() -> dict
read_file(path: str, max_chars: int = 12000) -> str
search_code(pattern: str, glob: str = "**/*.py") -> dict
apply_patch(path: str, old: str, new: str) -> dict
write_file(path: str, content: str) -> dict
run_tests(target: str = "tests", keyword: str = "") -> dict
run_static_scan() -> dict
get_diff() -> str
inspect_audit_log() -> dict
```

关键规则：

```text
1. 每个 agent run 开始前创建一个独立临时 workspace。
2. workspace 从 fixture_repo 拷贝而来。
3. agent 只能修改 workspace/src/mini_agent_runtime 下的文件。
4. agent 不能修改 tests/，不能读取 hidden_tests/。
5. run_tests 只能运行 workspace 内公开 tests。
6. scorer.py 最后另行运行 hidden_tests。
7. 所有工具调用都要写入 audit log。
8. 工具返回必须结构化，包含 status、stdout、stderr、duration、instruction。
```

`tools.py` 的核心实现草案：

```python
# benchmarks/thinking_stress_v1/tools.py

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BENCH_ROOT = Path(__file__).parent
FIXTURE_REPO = BENCH_ROOT / "fixture_repo"
HIDDEN_TESTS = BENCH_ROOT / "hidden_tests"

_CURRENT_WORKSPACE: Path | None = None
_AUDIT_LOG: list[dict[str, Any]] = []


def _audit(tool: str, args: dict[str, Any], result: dict[str, Any]) -> None:
    _AUDIT_LOG.append({
        "ts": time.time(),
        "tool": tool,
        "args": args,
        "status": result.get("status"),
        "duration_s": result.get("duration_s"),
        "summary": str(result)[:500],
    })


def _require_ws() -> Path:
    if _CURRENT_WORKSPACE is None:
        raise RuntimeError("Workspace not initialized. Call init_workspace first.")
    return _CURRENT_WORKSPACE


def _safe_path(path: str, allow_tests: bool = False) -> Path:
    ws = _require_ws().resolve()
    p = (ws / path).resolve()
    p.relative_to(ws)

    if "hidden_tests" in p.parts:
        raise ValueError("hidden_tests are not accessible to agents")

    if not allow_tests:
        src_root = (ws / "src" / "mini_agent_runtime").resolve()
        try:
            p.relative_to(src_root)
        except ValueError:
            raise ValueError("Only src/mini_agent_runtime files may be modified")

    return p


def init_workspace(case_id: str = "runtime_repair_lab") -> dict:
    global _CURRENT_WORKSPACE, _AUDIT_LOG
    _AUDIT_LOG = []

    tmp = Path(tempfile.mkdtemp(prefix=f"seekflow_thinking_{case_id}_"))
    shutil.copytree(FIXTURE_REPO, tmp, dirs_exist_ok=True)
    _CURRENT_WORKSPACE = tmp

    result = {
        "status": "ok",
        "workspace": str(tmp),
        "instruction": "Workspace initialized. Use list_files/read_file/search_code before patching.",
    }
    _audit("init_workspace", {"case_id": case_id}, result)
    return result


def list_files() -> dict:
    started = time.perf_counter()
    ws = _require_ws()
    files = []
    for p in ws.rglob("*"):
        if p.is_file():
            rel = p.relative_to(ws).as_posix()
            if rel.startswith("hidden_tests/"):
                continue
            files.append(rel)

    result = {
        "status": "ok",
        "files": sorted(files),
        "duration_s": round(time.perf_counter() - started, 3),
    }
    _audit("list_files", {}, result)
    return result


def read_file(path: str, max_chars: int = 12000) -> str:
    started = time.perf_counter()
    ws = _require_ws()
    p = (ws / path).resolve()
    p.relative_to(ws)

    if "hidden_tests" in p.parts:
        result = {"status": "error", "error": "hidden_tests are not accessible"}
        _audit("read_file", {"path": path}, result)
        return json.dumps(result, ensure_ascii=False)

    content = p.read_text(encoding="utf-8", errors="replace")
    if len(content) > max_chars:
        content = content[:max_chars] + f"\n...[truncated {len(content)} chars total]"

    _audit("read_file", {"path": path, "max_chars": max_chars}, {
        "status": "ok",
        "duration_s": round(time.perf_counter() - started, 3),
        "chars": len(content),
    })
    return content


def search_code(pattern: str, glob: str = "**/*.py") -> dict:
    started = time.perf_counter()
    ws = _require_ws()
    rx = re.compile(pattern)
    matches = []

    for p in ws.glob(glob):
        if not p.is_file():
            continue
        rel = p.relative_to(ws).as_posix()
        if rel.startswith("hidden_tests/"):
            continue

        text = p.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), start=1):
            if rx.search(line):
                matches.append({
                    "path": rel,
                    "line": i,
                    "text": line[:240],
                })

    result = {
        "status": "ok",
        "pattern": pattern,
        "matches": matches[:200],
        "count": len(matches),
        "duration_s": round(time.perf_counter() - started, 3),
    }
    _audit("search_code", {"pattern": pattern, "glob": glob}, result)
    return result


def apply_patch(path: str, old: str, new: str) -> dict:
    started = time.perf_counter()
    try:
        p = _safe_path(path, allow_tests=False)
        text = p.read_text(encoding="utf-8", errors="replace")
        if old not in text:
            result = {
                "status": "error",
                "error": "old text not found exactly once or at all",
                "instruction": "Use read_file to inspect the exact current content before patching.",
            }
            return result

        if text.count(old) != 1:
            result = {
                "status": "error",
                "error": f"old text occurs {text.count(old)} times; patch would be ambiguous",
            }
            return result

        p.write_text(text.replace(old, new), encoding="utf-8")
        result = {
            "status": "ok",
            "path": path,
            "duration_s": round(time.perf_counter() - started, 3),
        }
        return result
    finally:
        try:
            _audit("apply_patch", {"path": path}, locals().get("result", {"status": "unknown"}))
        except Exception:
            pass


def write_file(path: str, content: str) -> dict:
    started = time.perf_counter()
    try:
        p = _safe_path(path, allow_tests=False)
        p.write_text(content, encoding="utf-8")
        result = {
            "status": "ok",
            "path": path,
            "duration_s": round(time.perf_counter() - started, 3),
        }
        return result
    finally:
        try:
            _audit("write_file", {"path": path, "chars": len(content)}, locals().get("result", {"status": "unknown"}))
        except Exception:
            pass


def run_tests(target: str = "tests", keyword: str = "") -> dict:
    started = time.perf_counter()
    ws = _require_ws()

    if "hidden" in target:
        result = {"status": "error", "error": "hidden tests are not accessible to agents"}
        _audit("run_tests", {"target": target, "keyword": keyword}, result)
        return result

    cmd = ["python", "-m", "pytest", target, "-q"]
    if keyword:
        cmd.extend(["-k", keyword])

    proc = subprocess.run(
        cmd,
        cwd=ws,
        text=True,
        capture_output=True,
        timeout=25,
    )

    result = {
        "status": "ok" if proc.returncode == 0 else "failed",
        "returncode": proc.returncode,
        "stdout": proc.stdout[-8000:],
        "stderr": proc.stderr[-4000:],
        "duration_s": round(time.perf_counter() - started, 3),
        "instruction": (
            "If tests failed, inspect the traceback and patch root cause. "
            "Do not modify tests."
        ),
    }
    _audit("run_tests", {"target": target, "keyword": keyword}, result)
    return result


def run_static_scan() -> dict:
    started = time.perf_counter()
    ws = _require_ws()
    issues = []

    for p in (ws / "src" / "mini_agent_runtime").rglob("*.py"):
        rel = p.relative_to(ws).as_posix()
        text = p.read_text(encoding="utf-8", errors="replace")

        if "eval(" in text or "exec(" in text:
            issues.append({"severity": "HIGH", "path": rel, "issue": "eval/exec usage"})
        if "return True" in text and "authorize" in p.name:
            issues.append({"severity": "MEDIUM", "path": rel, "issue": "possible permissive policy"})
        if "startswith(str(root))" in text:
            issues.append({"severity": "HIGH", "path": rel, "issue": "unsafe path prefix check"})

    result = {
        "status": "ok",
        "issues": issues,
        "high_count": sum(1 for x in issues if x["severity"] == "HIGH"),
        "duration_s": round(time.perf_counter() - started, 3),
    }
    _audit("run_static_scan", {}, result)
    return result


def get_diff() -> str:
    ws = _require_ws()
    lines = []

    for p in (ws / "src" / "mini_agent_runtime").rglob("*.py"):
        rel = p.relative_to(ws)
        original = (FIXTURE_REPO / rel).read_text(encoding="utf-8", errors="replace")
        current = p.read_text(encoding="utf-8", errors="replace")
        if original != current:
            lines.extend(difflib.unified_diff(
                original.splitlines(),
                current.splitlines(),
                fromfile=f"a/{rel.as_posix()}",
                tofile=f"b/{rel.as_posix()}",
                lineterm="",
            ))

    result = "\n".join(lines)[:20000]
    _audit("get_diff", {}, {"status": "ok", "chars": len(result)})
    return result


def inspect_audit_log() -> dict:
    return {
        "status": "ok",
        "events": _AUDIT_LOG,
        "count": len(_AUDIT_LOG),
    }
```

---

# 七、任务 Prompt 设计

新增 `scenario.py`。

```python
# benchmarks/thinking_stress_v1/scenario.py

SYSTEM_PROMPT = """你是一名企业级 Agent Runtime 架构师、安全工程师和资深 Python 修复专家。
你的目标不是写审查报告，而是通过工具实际修复代码、运行测试并完成回归验证。
"""

TASK = """
# 任务：修复 mini_agent_runtime

你接手了一个小型 Python Agent Runtime 仓库。它模拟了 DeepSeek thinking mode、多轮 tool calls、path sandbox、SSRF 防护、secret redaction、prompt cache、policy engine、JSON repair 等模块。

仓库中存在多个互相影响的 bug。你的任务是实际修复代码，使公开测试尽量全部通过，并尽可能通过隐藏测试。

## 硬性规则

1. 必须先调用 init_workspace。
2. 必须调用 list_files 理解仓库结构。
3. 必须使用 read_file 阅读相关源码和测试。
4. 必须至少调用一次 run_tests 获取真实失败信息。
5. 必须使用 search_code 追踪跨文件调用或关键函数。
6. 必须使用 apply_patch 或 write_file 修改 src/mini_agent_runtime 下的源码。
7. 不允许修改 tests、hidden_tests、pyproject.toml。
8. 不允许删除安全检查来通过测试。
9. 不允许硬编码测试名、测试输入、pytest 环境变量。
10. 每次主要 patch 后，必须重新运行相关测试。
11. 最终必须调用 get_diff 和 inspect_audit_log。
12. 最终回答只输出简洁修复报告，不要输出隐藏推理过程。

## 重点修复方向

你需要关注以下模块，但不要假设这些就是全部问题：

- messages.py：thinking/tool-call 多轮消息构造是否保留必要字段
- tool_runtime.py：并行工具执行后结果顺序是否稳定
- security.py：path sandbox 与 SSRF 防护是否可绕过
- redaction.py：secret redaction 是否覆盖常见凭据
- cache_cost.py：cache prefix 是否稳定，cached token 是否正确计费
- policy.py：缺失 policy 是否 deny-by-default
- json_repair.py：低置信 JSON repair 是否允许 dangerous tool

## 最终报告格式

请用中文输出：

1. 修复摘要
2. 修改文件列表
3. 每个 bug 的根因与修复方式
4. 运行过的测试及结果
5. 静态扫描结果
6. 剩余风险
7. 工具调用摘要
"""
```

特别注意：Prompt 里明确“不要输出隐藏推理过程”。这很重要。SeekFlow 的 `reasoning.py` 里已有 harvesting / consistency check 设计，会从 reasoning_content 中提取 subgoals、hypotheses、uncertainties、rejected_paths、tool_plan 等结构化信息。([GitHub][3])
但 benchmark 结果里不应该展示模型完整 chain-of-thought，只记录是否启用 thinking、reasoning token、是否发生 reasoning/tool consistency mismatch 等诊断信息即可。

---

# 八、Agent 接入层设计

新增 `agents.py`，统一所有被测框架的入口。

核心返回结构：

```python
@dataclass
class RunResult:
    framework: str
    mode: str
    thinking: bool | None
    success: bool
    final_output: str
    latency_s: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_cny: float
    tool_calls_count: int
    audit_log: list[dict[str, Any]]
    diff: str
    raw_error: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
```

SeekFlow 组必须至少有三种：

```python
def run_seekflow_stable_thinking(api_key: str) -> RunResult:
    agent = DeepSeekAgent(
        role="企业级 Agent Runtime 架构师",
        goal="修复 mini_agent_runtime 并通过测试",
        backstory="安全、协议、测试驱动修复专家",
        api_key=api_key,
        model="deepseek-v4-pro",
        thinking=True,
        mode="stable",
        max_steps=30,
        dangerous_tools=True,
        temperature=0.0,
    )
    for tool in TOOLS:
        agent.add_tool(tool)
    return _run_agent(agent, "SeekFlow", "stable-thinking", True)
```

```python
def run_seekflow_stable_no_thinking(api_key: str) -> RunResult:
    agent = DeepSeekAgent(
        role="企业级 Agent Runtime 架构师",
        goal="修复 mini_agent_runtime 并通过测试",
        backstory="安全、协议、测试驱动修复专家",
        api_key=api_key,
        model="deepseek-v4-pro",
        thinking=False,
        mode="stable",
        max_steps=30,
        dangerous_tools=True,
        temperature=0.0,
    )
    ...
```

```python
def run_seekflow_fast_no_thinking(api_key: str) -> RunResult:
    agent = DeepSeekAgent(
        role="企业级 Agent Runtime 架构师",
        goal="修复 mini_agent_runtime 并通过测试",
        backstory="安全、协议、测试驱动修复专家",
        api_key=api_key,
        model="deepseek-v4-pro",
        thinking=False,
        mode="fast",
        max_steps=16,
        dangerous_tools=True,
        temperature=0.0,
    )
    ...
```

为什么 `max_steps` 要这样设：

```text
stable-thinking 与 stable-no-thinking 都给 30 步，隔离 thinking 变量。
fast-no-thinking 给 16 步，模拟 fast 的低成本实用模式。
如果 fast 因步数不足失败，不应直接归因于 no-thinking，因此主结论应重点比较 stable-thinking vs stable-no-thinking。
```

LangChain / CrewAI 可以后置接入。第一版先把 SeekFlow 内部三组跑通，因为这个 benchmark 的目标是证明 thinking 本身，而不是再次证明框架横评。

---

# 九、评分器设计

新增 `scorer.py`。这里不应主要依赖 LLM judge，而应以程序化评分为主。

总分 100：

```text
A. 公开测试通过率：25 分
B. 隐藏测试通过率：30 分
C. 静态安全扫描：10 分
D. 工具流程合规：15 分
E. Patch 质量：10 分
F. 最终报告质量：10 分
```

## 9.1 公开测试通过率 25 分

由 agent 可见的 `fixture_repo/tests` 决定。

```text
score_public = 25 * public_passed / public_total
```

## 9.2 隐藏测试通过率 30 分

由 agent 不可见的 `hidden_tests` 决定。

```text
score_hidden = 30 * hidden_passed / hidden_total
```

隐藏测试权重要比公开测试高，因为它防硬编码。

## 9.3 静态安全扫描 10 分

```text
无 HIGH：10 分
每个 HIGH 扣 5
每个 MEDIUM 扣 2
最低 0
```

## 9.4 工具流程合规 15 分

检查 audit log：

```text
init_workspace 调用：1
list_files 调用：1
read_file >= 6：2
search_code >= 3：2
run_tests >= 2：3
apply_patch/write_file >= 3：2
get_diff 调用：1
inspect_audit_log 调用：1
patch 后有重新 run_tests：2
```

## 9.5 Patch 质量 10 分

程序化检查：

```text
未修改 tests：2
未修改 hidden_tests：2
未删除核心安全函数：2
未引入 eval/exec/subprocess shell=True：2
diff 行数合理，不是全文件重写或硬编码：2
```

## 9.6 最终报告质量 10 分

可以用简单规则 + 可选 LLM judge：

```text
包含修复摘要：1
包含修改文件列表：1
包含每个 bug 根因：2
包含测试结果：2
包含静态扫描结果：1
包含剩余风险：1
包含工具调用摘要：1
中文清晰简洁：1
```

`scorer.py` 必须在最终复制 workspace 后运行 hidden tests：

```python
def run_hidden_tests(workspace: Path) -> dict:
    """
    Copy hidden_tests into a temp location or invoke pytest with hidden_tests
    while setting PYTHONPATH to workspace/src.
    """
```

注意 hidden tests 不应放入 workspace 内，避免被 agent 读到。

---

# 十、Runner 设计

新增 `runner.py`。

运行命令：

```bash
python -m benchmarks.thinking_stress_v1.runner --rounds 3
```

支持参数：

```text
--rounds 轮数，默认 3
--frameworks seekflow_stable_thinking,seekflow_stable_no_thinking,seekflow_fast_no_thinking
--max-seconds 每个 run 最大时间，默认 900
--output output/thinking_stress_YYYYMMDD_HHMMSS.json
```

每轮随机化执行顺序，但同一轮的每个 agent 都从全新 workspace 开始。

输出 JSON 结构：

```json
{
  "benchmark": "thinking_stress_v1",
  "scenario": "runtime_repair_lab",
  "created_at": "...",
  "rounds": 3,
  "results": [
    {
      "round": 1,
      "framework": "SeekFlow",
      "mode": "stable-thinking",
      "thinking": true,
      "latency_s": 812.4,
      "tokens": {
        "prompt": 12345,
        "completion": 6789,
        "total": 19134
      },
      "cost_cny": 0.043,
      "score": {
        "total": 86.5,
        "public_tests": 23.0,
        "hidden_tests": 27.0,
        "static_scan": 10.0,
        "tool_process": 14.0,
        "patch_quality": 8.5,
        "final_report": 4.0
      },
      "tests": {
        "public": {"passed": 19, "total": 20},
        "hidden": {"passed": 17, "total": 18}
      },
      "audit_log": [...],
      "diff": "...",
      "final_output": "...",
      "diagnostics": {
        "reasoning_present": true,
        "reasoning_chars": 12345,
        "tool_calls_count": 28
      }
    }
  ],
  "summary": {
    "stable_thinking_avg": 86.5,
    "stable_no_thinking_avg": 71.2,
    "fast_no_thinking_avg": 58.4,
    "thinking_delta_vs_stable_no_thinking": 15.3
  }
}
```

---

# 十一、成功判据

这个 benchmark 做完后，不能只说“Stable thinking 分数高”。要有明确验收标准。

建议设置：

```text
有效证明 thinking 的最低标准：

1. stable-thinking 平均总分 ≥ stable-no-thinking + 10 分
2. stable-thinking 隐藏测试通过率 ≥ stable-no-thinking + 15%
3. stable-thinking 不只是更长，而是更少误修：
   - 修改 tests 次数 = 0
   - 静态扫描 HIGH = 0
   - patch 后回归测试次数更合理
4. stable-thinking 成本和延迟更高可以接受，但必须报告：
   - 每多 1 分质量提升增加多少成本
   - 每多 1 个隐藏测试通过增加多少秒
```

如果结果是：

```text
stable-thinking 87
stable-no-thinking 82
fast-no-thinking 60
```

那说明 thinking 有帮助，但差距不够强。
如果结果是：

```text
stable-thinking 88
stable-no-thinking 67
fast-no-thinking 55
```

那就能比较有力地证明 thinking 在复杂工程闭环中有价值。
如果结果是：

```text
stable-thinking 88
stable-no-thinking 86
```

那就说明任务仍然不够复杂，或者 v4-pro 在 no-thinking 下已经足够强，需要提高隐藏测试难度和跨文件依赖。

---

# 十二、必须避免的设计错误

第一，不要让 agent 直接执行任意 shell。`run_tests` 可以内部固定执行 pytest，但不要给 `bash` 或 `python -c` 自由执行工具，否则比较会变成“谁会写脚本作弊”。

第二，不要让 agent 读 hidden tests。隐藏测试只能 scorer 运行。

第三，不要让评分依赖模型自述。最终报告说“我修复了 SSRF”不算，必须由测试和静态扫描确认。

第四，不要把任务做成纯安全审查报告。必须要求 patch 和测试。

第五，不要把所有 bug 都设计成单文件显眼错误。至少一半 bug 要跨文件、跨协议或涉及顺序/缓存/安全权衡。

第六，不要要求模型输出完整 thinking。可以记录 reasoning 是否存在、长度、consistency check，但 final output 不能暴露原始 chain-of-thought。

---

# 十三、推荐分阶段提交

给 Claude Code 的实现顺序如下。

## Phase 1：搭建 benchmark 骨架

创建：

```text
benchmarks/thinking_stress_v1/__init__.py
benchmarks/thinking_stress_v1/README.md
benchmarks/thinking_stress_v1/scenario.py
benchmarks/thinking_stress_v1/tools.py
benchmarks/thinking_stress_v1/runner.py
benchmarks/thinking_stress_v1/agents.py
benchmarks/thinking_stress_v1/scorer.py
benchmarks/thinking_stress_v1/output/.gitkeep
```

先不要接入 LangChain/CrewAI，只接入 SeekFlow 三组：

```text
stable-thinking
stable-no-thinking
fast-no-thinking
```

## Phase 2：实现 fixture repo

创建 `fixture_repo`，实现 7 个模块和公开测试：

```text
messages.py + test_messages.py
tool_runtime.py + test_tool_runtime.py
security.py + test_security.py
redaction.py + test_redaction.py
cache_cost.py + test_cache_cost.py
policy.py + test_policy.py
json_repair.py + test_json_repair.py
```

手动确认初始 fixture repo 的公开测试必须失败：

```bash
cd benchmarks/thinking_stress_v1/fixture_repo
python -m pytest -q
```

预期：

```text
至少 8 个测试失败
```

## Phase 3：实现工具层

实现：

```text
init_workspace
list_files
read_file
search_code
apply_patch
write_file
run_tests
run_static_scan
get_diff
inspect_audit_log
```

手动测试：

```python
from benchmarks.thinking_stress_v1.tools import *

init_workspace()
list_files()
read_file("src/mini_agent_runtime/security.py")
run_tests()
```

## Phase 4：实现 scorer

实现 public + hidden tests 评分，确保 agent 无法读取 hidden tests。

## Phase 5：实现 runner

跑一轮 smoke test：

```bash
python -m benchmarks.thinking_stress_v1.runner \
  --rounds 1 \
  --frameworks seekflow_fast_no_thinking
```

再跑三组 SeekFlow：

```bash
python -m benchmarks.thinking_stress_v1.runner \
  --rounds 1 \
  --frameworks seekflow_stable_thinking,seekflow_stable_no_thinking,seekflow_fast_no_thinking
```

## Phase 6：加报告生成

新增 `report.py`，从 JSON 生成 Markdown：

```bash
python -m benchmarks.thinking_stress_v1.report output/thinking_stress_xxx.json
```

报告必须包含：

```text
1. 总分表
2. public / hidden tests 通过率
3. latency / token / cost
4. tool call count
5. diff size
6. thinking vs no-thinking delta
7. 失败案例摘要
```

## Phase 7：再考虑 LangChain/CrewAI

等 SeekFlow 内部三组稳定后，再接入 LangChain 和 CrewAI。否则变量太多，排查困难。

---

# 十四、Claude Code 可直接使用的任务说明

可以把下面这一段原样给 Claude Code：

```text
请在当前 SeekFlow 仓库中实现一个新的 benchmark：benchmarks/thinking_stress_v1。

目标：
构建一个专门验证 DeepSeek thinking mode 在复杂工程闭环任务中价值的 benchmark。不要扩展 fair_comparison_v2。新 benchmark 必须通过“修复坏代码仓库 + 运行测试 + 隐藏测试验收”的方式评分，而不是主要依赖 LLM judge。

背景：
当前 README 显示，v4-pro 在已有 reasoning 场景中不开 thinking 也能达到接近 thinking 的效果，三类 extreme reasoning 场景几乎全部 8.8–8.9，因此现有场景不能证明 thinking。新场景必须更复杂，且可程序化验收。

请实现：

1. 新目录 benchmarks/thinking_stress_v1/
2. fixture_repo/：一个故意写坏的小型 Python Agent Runtime
3. hidden_tests/：agent 不可见的隐藏测试
4. tools.py：受控工具，禁止任意 shell，允许初始化 workspace、读文件、搜代码、patch、跑 pytest、静态扫描、看 diff、看 audit log
5. scenario.py：任务 prompt，要求 agent 实际修复代码，不是写审查报告
6. agents.py：至少接入三个 SeekFlow 配置：
   - stable-thinking: thinking=True, mode=stable, max_steps=30
   - stable-no-thinking: thinking=False, mode=stable, max_steps=30
   - fast-no-thinking: thinking=False, mode=fast, max_steps=16
7. scorer.py：程序化评分，总分 100：
   - public tests 25
   - hidden tests 30
   - static scan 10
   - tool process compliance 15
   - patch quality 10
   - final report quality 10
8. runner.py：支持 --rounds、--frameworks、--output，输出 JSON
9. report.py：把结果 JSON 转成 Markdown 报告
10. README.md：解释 benchmark 目的、运行方式、评分规则、如何解读 thinking delta

fixture_repo 必须包含以下模块和故意 bug：

- messages.py：build_next_messages 丢失 reasoning_content
- tool_runtime.py：parallel tool results 按完成顺序返回，而不是原始 tool_call 顺序
- security.py：safe_join 可被 traversal / encoded traversal / symlink 绕过；validate_url 漏挡 private IP / metadata IP / IPv6 / numeric IPv4
- redaction.py：只 redacts sk-，漏掉 Bearer token / AWS key / JWT / query token
- cache_cost.py：cache prefix 含 timestamp；cached tokens 按 full input price 计费
- policy.py：missing policy 默认 allow，应 deny-by-default
- json_repair.py：dangerous tool 允许 low-confidence repaired JSON，应拒绝

公开 tests 放在 fixture_repo/tests。
隐藏 tests 放在 benchmarks/thinking_stress_v1/hidden_tests，不能被 agent 工具读取，只能 scorer 运行。

要求：
- agent 只能修改 workspace/src/mini_agent_runtime 下的文件。
- agent 不能修改 tests、hidden_tests、pyproject.toml。
- run_tests 工具只能运行公开 tests。
- scorer 最终运行 hidden_tests。
- 所有工具调用写入 audit log。
- final output 不要泄露模型原始 reasoning_content。
- Runner 输出必须保存 final_output、diff、audit_log、scores、tokens、latency、cost、diagnostics。

完成后请运行：
python -m benchmarks.thinking_stress_v1.runner --rounds 1 --frameworks seekflow_fast_no_thinking

然后运行：
python -m benchmarks.thinking_stress_v1.runner --rounds 1 --frameworks seekflow_stable_thinking,seekflow_stable_no_thinking,seekflow_fast_no_thinking

最后生成一份 Markdown 报告。
```

---

# 十五、最终预期

这个 benchmark 如果实现得好，结果应该不再是 “Stable 8.9，Fast 8.8，LangChain 8.9” 这种无法证明 thinking 的平局。合理预期是：

```text
SeekFlow stable-thinking:
- public tests 90–100%
- hidden tests 75–95%
- 总分 80–90

SeekFlow stable-no-thinking:
- public tests 70–90%
- hidden tests 45–75%
- 总分 60–78

SeekFlow fast-no-thinking:
- public tests 40–75%
- hidden tests 20–55%
- 总分 45–65
```

最关键的指标不是总分，而是：

```text
stable-thinking vs stable-no-thinking 的隐藏测试通过率差距。
```

因为公开测试可以被表层修复蒙混，隐藏测试才真正检测它是否理解了根因。只要 hidden tests 上 thinking 稳定领先 15–20 个百分点，这个 benchmark 就能比较有力地证明：**thinking 在足够复杂、可执行、可失败、可回归验证的工程任务中确实有价值。**

[1]: https://github.com/WYZAAACCC/SeekFlow "GitHub - WYZAAACCC/SeekFlow: DeepSeek-native agent framework with production-grade reliability · GitHub"
[2]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/docs/security/levels.md "raw.githubusercontent.com"
[3]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/reasoning.py "raw.githubusercontent.com"
