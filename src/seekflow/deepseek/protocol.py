"""DeepSeek protocol state machine — message ordering enforcement.

When DeepSeek thinking mode is active and the assistant returns tool_calls,
the reasoning_content MUST be preserved exactly and the message ordering
MUST follow: assistant(tool_calls) → tool_result → tool_result → ...

No user/system messages may be inserted between assistant tool_calls and
their corresponding tool results.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from seekflow.runtime_errors import DeepSeekProtocolError


@dataclass
class ConversationState:
    """Typed conversation state with protocol validation.

    Tracks pending tool call IDs and enforces DeepSeek message ordering:
    - assistant + tool_calls must be followed immediately by tool results
    - tool results must match pending tool_call_ids in order
    - no semantic messages inserted between calls and results
    - reasoning_content must be present when tool_calls are present
    """

    messages: list[dict[str, Any]] = field(default_factory=list)
    pending_tool_call_ids: list[str] = field(default_factory=list)

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

        if tool_calls and reasoning_content is None:
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
        validate_deepseek_messages(self.messages)

    def _assert_no_pending_tool_results(self) -> None:
        if self.pending_tool_call_ids:
            raise DeepSeekProtocolError(
                f"Pending tool results missing: {self.pending_tool_call_ids}. "
                "All tool_calls must have matching tool results before adding "
                "new user/system messages or making a model request."
            )


def validate_deepseek_messages(messages: list[dict[str, Any]]) -> None:
    """Validate that a messages list follows DeepSeek protocol.

    Checks:
    - Assistant messages with tool_calls have reasoning_content
    - Tool results immediately follow their assistant tool_calls
    - Tool result IDs match the expected order
    - No user/system messages inserted between call and result
    """
    for i, msg in enumerate(messages):
        if msg.get("role") != "assistant":
            continue

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            continue

        if "reasoning_content" not in msg or not msg["reasoning_content"]:
            raise DeepSeekProtocolError(
                "DeepSeek assistant message with tool_calls must contain "
                "reasoning_content. Found at message index {i}."
            )

        expected_ids = [tc["id"] for tc in tool_calls]
        following = messages[i + 1 : i + 1 + len(expected_ids)]

        if len(following) != len(expected_ids):
            raise DeepSeekProtocolError(
                f"Missing tool result messages after assistant tool_calls. "
                f"Expected {len(expected_ids)}, found {len(following)}."
            )

        for expected_id, tool_msg in zip(expected_ids, following, strict=True):
            if tool_msg.get("role") != "tool":
                raise DeepSeekProtocolError(
                    "Assistant tool_calls must be followed immediately by "
                    "tool messages. Found role={tool_msg.get('role')} instead. "
                    "No user or system messages may be inserted between "
                    "assistant tool_calls and tool results."
                )
            if tool_msg.get("tool_call_id") != expected_id:
                raise DeepSeekProtocolError(
                    f"Tool result id mismatch. Expected {expected_id}, "
                    f"got {tool_msg.get('tool_call_id')}."
                )
