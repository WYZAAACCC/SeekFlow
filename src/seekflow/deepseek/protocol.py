"""DeepSeek protocol state machine — message ordering and validation.

When DeepSeek thinking mode is active and the assistant returns tool_calls,
the reasoning_content MUST be preserved exactly and the message ordering
MUST follow: assistant(tool_calls) → tool_result → tool_result → ...

No user/system messages may be inserted between assistant tool_calls and
their corresponding tool results.

This module is mode-aware: non-thinking mode does NOT require reasoning_content.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from seekflow.runtime_errors import DeepSeekProtocolError


@dataclass(frozen=True)
class ValidationIssue:
    """A single protocol validation finding."""
    code: str
    message: str
    index: int | None = None
    severity: Literal["error", "warning"] = "error"


@dataclass
class ConversationState:
    """Typed conversation state with protocol validation.

    Tracks pending tool call IDs and enforces DeepSeek message ordering:
    - assistant + tool_calls must be followed immediately by tool results
    - tool results must match pending tool_call_ids in order
    - no semantic messages inserted between calls and results
    - reasoning_content must be present when tool_calls are present (thinking mode only)
    """

    messages: list[dict[str, Any]] = field(default_factory=list)
    pending_tool_call_ids: list[str] = field(default_factory=list)
    thinking_enabled: bool = True

    def add_system(self, content: str) -> None:
        self._assert_no_pending_tool_results()
        self.messages.append({"role": "system", "content": content})

    def add_user(self, content: str) -> None:
        self._assert_no_pending_tool_results()
        self.messages.append({"role": "user", "content": content})

    def add_assistant(
        self,
        *,
        content: str | None,
        reasoning_content: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        tool_calls = tool_calls or []

        if tool_calls and self.thinking_enabled and reasoning_content is None:
            raise DeepSeekProtocolError(
                "Assistant messages with tool_calls in DeepSeek thinking mode "
                "must preserve reasoning_content exactly. Do not compress or "
                "discard reasoning_content when tool_calls are present."
            )

        msg: dict[str, Any] = {"role": "assistant", "content": content}
        if reasoning_content is not None:
            msg["reasoning_content"] = reasoning_content
        if tool_calls:
            msg["tool_calls"] = tool_calls
            self.pending_tool_call_ids = [tc["id"] for tc in tool_calls]

        self.messages.append(msg)

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        if not self.pending_tool_call_ids:
            raise DeepSeekProtocolError(
                "No pending tool calls — tool result without preceding "
                "assistant tool_call."
            )

        expected = self.pending_tool_call_ids[0]
        if tool_call_id != expected:
            raise DeepSeekProtocolError(
                f"Tool result order mismatch. Expected {expected}, "
                f"got {tool_call_id}. Tool results must follow the same "
                "order as tool_calls in the assistant message."
            )

        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        })
        self.pending_tool_call_ids.pop(0)

    def validate_before_model_request(self) -> None:
        self._assert_no_pending_tool_results()
        issues = validate_deepseek_messages(self.messages, thinking_enabled=self.thinking_enabled)
        errors = [i for i in issues if i.severity == "error"]
        if errors:
            raise DeepSeekProtocolError(
                f"Protocol validation failed: {'; '.join(i.message for i in errors)}"
            )

    def _assert_no_pending_tool_results(self) -> None:
        if self.pending_tool_call_ids:
            raise DeepSeekProtocolError(
                f"Pending tool results missing: {self.pending_tool_call_ids}. "
                "All tool_calls must have matching tool results before adding "
                "new user/system messages or making a model request."
            )


def validate_deepseek_messages(
    messages: list[dict[str, Any]],
    *,
    thinking_enabled: bool = True,
    require_assistant_content_for_tool_calls: bool = True,
    repair: bool = False,
) -> list[ValidationIssue]:
    """Validate that a messages list follows DeepSeek protocol.

    Mode-aware: non-thinking mode does NOT require reasoning_content.

    Checks:
    - Roles are system/user/assistant/tool only
    - Assistant messages with tool_calls have reasoning_content (thinking mode only)
    - Assistant messages with tool_calls must have content (repaired to "" if repair=True)
    - Tool results immediately follow their assistant tool_calls
    - Tool result IDs match the expected order
    - No user/system messages inserted between call and result
    """
    issues: list[ValidationIssue] = []

    valid_roles = {"system", "user", "assistant", "tool"}
    for i, msg in enumerate(messages):
        role = msg.get("role")
        if role not in valid_roles:
            # developer role must be handled in adapter layer
            issues.append(ValidationIssue(
                code="invalid_role",
                message=f"Invalid role '{role}' at index {i}. Must be one of: {sorted(valid_roles)}.",
                index=i,
            ))

    for i, msg in enumerate(messages):
        if msg.get("role") != "assistant":
            continue

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            continue

        # 1. reasoning_content: required in thinking mode, optional otherwise
        has_reasoning = "reasoning_content" in msg and msg["reasoning_content"]
        if thinking_enabled and not has_reasoning:
            issues.append(ValidationIssue(
                code="missing_reasoning_content",
                message=f"DeepSeek thinking mode requires reasoning_content for assistant with tool_calls at index {i}.",
                index=i,
            ))
        elif not thinking_enabled and not has_reasoning:
            issues.append(ValidationIssue(
                code="missing_reasoning_content_non_thinking",
                message=f"Assistant with tool_calls at index {i} missing reasoning_content (not required in non-thinking mode).",
                index=i,
                severity="warning",
            ))

        # 2. content must not be None for assistant with tool_calls
        if msg.get("content") is None:
            if repair:
                msg["content"] = ""
            else:
                issues.append(ValidationIssue(
                    code="null_content_in_tool_call",
                    message=f"Assistant message with tool_calls at index {i} has null content.",
                    index=i,
                ))

        # 3. tool_call_id → tool result pairing
        expected_ids = [tc["id"] for tc in tool_calls]
        following = messages[i + 1 : i + 1 + len(expected_ids)]

        if len(following) != len(expected_ids):
            issues.append(ValidationIssue(
                code="missing_tool_results",
                message=f"Missing tool result messages after assistant tool_calls at index {i}. "
                        f"Expected {len(expected_ids)}, found {len(following)}.",
                index=i,
            ))
            continue

        for j, (expected_id, tool_msg) in enumerate(zip(expected_ids, following, strict=False)):
            if tool_msg.get("role") != "tool":
                issues.append(ValidationIssue(
                    code="non_tool_after_tool_calls",
                    message=f"Assistant tool_calls at index {i} must be followed immediately by "
                            f"tool messages. Found role='{tool_msg.get('role')}' at index {i + 1 + j}.",
                    index=i + 1 + j,
                ))
            if tool_msg.get("tool_call_id") != expected_id:
                issues.append(ValidationIssue(
                    code="tool_call_id_mismatch",
                    message=f"Tool result id mismatch at index {i + 1 + j}. "
                            f"Expected '{expected_id}', got '{tool_msg.get('tool_call_id')}'.",
                    index=i + 1 + j,
                ))

    return issues


def repair_deepseek_messages(
    messages: list[dict[str, Any]],
    *,
    thinking_enabled: bool = True,
) -> list[dict[str, Any]]:
    """Repair protocol issues that are safe to fix mechanically.

    Does NOT fabricate reasoning_content — if thinking tool-call turns miss
    reasoning_content, it fails closed (returns original messages with a warning).
    """
    import copy
    repaired = copy.deepcopy(messages)

    for msg in repaired:
        if msg.get("role") != "assistant":
            continue
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            continue

        # Fix null content
        if msg.get("content") is None:
            msg["content"] = ""

        # For thinking mode: reasoning_content must exist — fail closed
        if thinking_enabled and not msg.get("reasoning_content"):
            raise DeepSeekProtocolError(
                f"Assistant message with tool_calls at index "
                f"{repaired.index(msg)} missing reasoning_content. "
                "Cannot repair — reasoning_content must be preserved from the model response."
            )

    return repaired
