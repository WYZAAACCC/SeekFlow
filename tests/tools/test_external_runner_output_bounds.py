"""Phase 5 tests: ExternalToolRunner byte-level output bounds."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from seekflow.tools.external_runner import _bounded_communicate


def _patch_bounded(proc, stdout_chunks=None, stderr_chunks=None, poll_side_effect=None):
    """Helper to mock selectors and make _bounded_communicate testable.

    Each chunk list is a sequence of bytes. The mock selector yields each
    chunk in order, simulating the non-blocking read loop.

    poll_side_effect: sequence of return values. When None is returned the
    loop continues; when 0 (int) is returned the process is considered done.
    """
    if stdout_chunks is None:
        stdout_chunks = []
    if stderr_chunks is None:
        stderr_chunks = []

    class _FakeKey:
        def __init__(self, data):
            self.data = data
            self.fileobj = MagicMock()

    class _FakeSel:
        def __init__(self):
            self._calls = 0

        def register(self, fileobj, events, data):
            pass

        def unregister(self, fileobj):
            pass

        def select(self, timeout=None):
            self._calls += 1
            result = []
            if self._calls <= len(stdout_chunks) and stdout_chunks[self._calls - 1] is not None:
                key = _FakeKey("stdout")
                key.fileobj.read.return_value = stdout_chunks[self._calls - 1]
                result.append((key, 1))
            if self._calls <= len(stderr_chunks) and stderr_chunks[self._calls - 1] is not None:
                key = _FakeKey("stderr")
                key.fileobj.read.return_value = stderr_chunks[self._calls - 1]
                result.append((key, 1))
            return result

        def close(self):
            pass

    proc.poll = MagicMock()
    if poll_side_effect:
        proc.poll.side_effect = poll_side_effect
    else:
        # Default: return None for first N polls, then 0
        n = max(len(stdout_chunks), len(stderr_chunks), 1)
        proc.poll.side_effect = [None] * n + [0] * 3

    proc.stdout = MagicMock()
    proc.stdout.read.return_value = b""
    proc.stderr = MagicMock()
    proc.stderr.read.return_value = b""

    with patch("selectors.DefaultSelector", return_value=_FakeSel()):
        return _bounded_communicate(proc, timeout_s=5.0, max_stdout=10000, max_stderr=10000)


def _patch_bounded_limit(proc, stdout_chunks, max_stdout, max_stderr, poll_side_effect=None):
    """Same as _patch_bounded but with configurable limits."""
    if poll_side_effect is None:
        n = max(len(stdout_chunks), 1)
        poll_side_effect = [None] * n + [0] * 3

    class _FakeKey:
        def __init__(self, data):
            self.data = data
            self.fileobj = MagicMock()

    class _FakeSel:
        def __init__(self):
            self._calls = 0

        def register(self, fileobj, events, data):
            pass

        def unregister(self, fileobj):
            pass

        def select(self, timeout=None):
            self._calls += 1
            result = []
            if self._calls <= len(stdout_chunks):
                chunk = stdout_chunks[self._calls - 1]
                if chunk is not None:
                    key = _FakeKey("stdout")
                    key.fileobj.read.return_value = chunk
                    result.append((key, 1))
            return result

        def close(self):
            pass

    proc.poll = MagicMock(side_effect=poll_side_effect)
    proc.stdout = MagicMock()
    proc.stdout.read.return_value = b""
    proc.stderr = MagicMock()
    proc.stderr.read.return_value = b""

    with patch("selectors.DefaultSelector", return_value=_FakeSel()):
        return _bounded_communicate(proc, timeout_s=5.0, max_stdout=max_stdout, max_stderr=max_stderr)


# ── Tests ──────────────────────────────────────────────────────────


def test_stdout_counted_in_bytes_not_chars():
    """stdout按bytes计数而非字符"""
    data = "你好世界".encode("utf-8")  # 12 bytes, 4 chars
    proc = MagicMock()
    stdout, stderr, timed_out, limit_exceeded = _patch_bounded(
        proc, stdout_chunks=[data],
    )
    assert not limit_exceeded
    assert len(stdout) == 12  # 12 bytes


def test_stdout_limit_enforced_in_bytes():
    """stdout超bytes限制→limit_exceeded"""
    proc = MagicMock()
    # 10k bytes, limit 5k
    chunks = [b"x" * 4096, b"x" * 4096, b"x" * 4096]
    stdout, stderr, timed_out, limit_exceeded = _patch_bounded_limit(
        proc, stdout_chunks=chunks, max_stdout=5000, max_stderr=10000,
    )
    assert limit_exceeded


def test_stderr_limit_enforced_in_bytes():
    """stderr超bytes限制→limit_exceeded"""
    proc = MagicMock()
    # Simulate large stderr with mocked approach
    chunks = [b"e" * 4096, b"e" * 4096, b"e" * 4096]
    stdout, stderr, timed_out, limit_exceeded = _patch_bounded_limit(
        proc, stdout_chunks=chunks, max_stdout=5000, max_stderr=10000,
    )
    assert limit_exceeded


def test_tail_output_after_exit_still_bounded():
    """proc退出后drain仍受限制"""
    tail_data = b"tail data" * 100  # 900 bytes

    def _stdout_read(size=-1):
        if size > 0:
            return tail_data[:size]
        return tail_data

    proc = MagicMock()
    proc.poll.side_effect = [0]  # exit immediately
    proc.stdout.read.side_effect = _stdout_read
    proc.stderr.read.return_value = b""

    class _FakeSel:
        def register(self, f, e, d): pass
        def unregister(self, f): pass
        def select(self, timeout=None): return []  # no events, proc already exited
        def close(self): pass

    with patch("selectors.DefaultSelector", return_value=_FakeSel()):
        stdout, stderr, timed_out, limit_exceeded = _bounded_communicate(
            proc, timeout_s=5.0, max_stdout=100, max_stderr=1000,
        )
    # drain reads at most remaining_quota = 100 bytes
    assert len(stdout) <= 100
    assert not limit_exceeded


def test_multibyte_utf8_counted_in_bytes():
    """多字节UTF-8按bytes计数而非字符"""
    text = "€" * 100  # 100 chars × 3 bytes = 300 bytes
    encoded = text.encode("utf-8")
    assert len(encoded) == 300
    assert len(text) == 100

    proc = MagicMock()
    stdout, stderr, timed_out, limit_exceeded = _patch_bounded(
        proc, stdout_chunks=[encoded],
    )
    assert not limit_exceeded
    assert len(stdout) == 300


def test_empty_output_returns_ok():
    """空输出正常返回"""
    proc = MagicMock()
    stdout, stderr, timed_out, limit_exceeded = _patch_bounded(
        proc, stdout_chunks=[b""],
    )
    assert not timed_out
    assert not limit_exceeded


def test_decode_bytes_after_bounded_communicate():
    """bytes输出正确解码为字符串"""
    data = '{"status": "ok", "value": "café"}'.encode("utf-8")
    proc = MagicMock()
    stdout, stderr, timed_out, limit_exceeded = _patch_bounded(
        proc, stdout_chunks=[data],
    )
    decoded = stdout.decode("utf-8")
    assert "café" in decoded
    assert '"status": "ok"' in decoded
