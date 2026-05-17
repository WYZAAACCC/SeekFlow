# SeekFlow Production Readiness Checklist

Checklist for graduating SeekFlow between security levels. Current target: **Level 3 candidate** (v0.3.7).

## Release Gate

Every release must pass:

- [ ] `pytest` — 0 failed
- [ ] `python scripts/check_xfail_policy.py --strict-core` exits 0
- [ ] `ruff check` — 0 errors
- [ ] `README.md` version == `pyproject.toml` version
- [ ] No known P0/P1 security gaps

## Lv3 Security Gates (Improve16)

- [ ] strict external manifest 必须有签名 (P0-B)
- [ ] 签名伪造不可通过 (P0-B)
- [ ] package_digest 与真实包不匹配时拒绝 (P0-C)
- [ ] OCI image tag-only 被拒绝 (P0-C)
- [ ] external tool 有 network 需求时启动 sidecar (P0-A)
- [ ] sidecar 未配置时网络工具不可用 (P0-A)
- [ ] sidecar 执行 DNS/IP/domain/method/body/redirect 校验 (P0-A)
- [ ] MCP gateway 不依赖全局 registry (P0-D)
- [ ] MCP 输出经过 schema validation (P0-E)
- [ ] durable audit 覆盖成功和失败路径 (P1-A)
- [ ] audit_required=True 时写入失败阻断执行 (P1-A)
- [ ] ExternalToolRunner text=False + bytes-level bounded (P1-B)
- [ ] drain 阶段仍受限制 (P1-B)
- [ ] README Security Status 准确描述 Lv3 candidate 状态 (P1-C)

## Lv2 Security Gates (v0.3.x — baseline)

- [ ] policy.runner cannot decrease required isolation (PR-1)
- [ ] code_exec/destructive tools without `container_codegen_trusted` are denied (PR-2)
- [ ] ProcessRunner bounds all output types, not just strings (PR-3)
- [ ] Cache read/write unified under `_cache_allowed` (PR-4)
- [ ] `metadata.trusted` no longer controls output wrapping (PR-5)
- [ ] No-policy tools are denied by default (PR-6)
- [ ] `authorize_with_context()` emits DeprecationWarning (PR-7)
- [ ] ContainerSandbox timeout does explicit `docker kill/rm` (PR-8)
- [ ] `check_xfail_policy.py --strict-core` available (PR-9)
- [ ] Documentation clearly states Level 2 boundaries (PR-10)

## Test Gates

- [ ] Runner minimum isolation tests pass (≥3)
- [ ] Container runner semantics tests pass (≥3)
- [ ] Process large output tests pass (≥3)
- [ ] Cache policy tests pass (≥3)
- [ ] Trusted output tests pass (≥3)
- [ ] No-policy execution tests pass (≥3)
- [ ] Manifest signature tests pass (≥9)
- [ ] Egress sidecar integration tests pass (≥7)
- [ ] MCP isolation tests pass (≥6)
- [ ] Durable audit production tests pass (≥5)
- [ ] Output bounds tests pass (≥6)
