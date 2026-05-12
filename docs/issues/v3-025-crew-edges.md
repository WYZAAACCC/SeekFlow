# v3-025: Crew 边界处理

**状态**: 已完成
**优先级**: P1
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景
PRD 第8节边界情况要求：空 tasks 返回明确错误、thread_id 冲突检测。当前：空 tasks 会 IndexError，无冲突检测。

## 任务
1. 空 tasks → 返回错误而非崩溃
2. Crew 边界保护

## 验收标准
- [x] 空 tasks 不崩溃，返回明确错误信息

## 分类: ready-for-agent
