"""Tests for deepseek_toolkit.async_runtime — async ToolRuntime."""
import pytest


class TestAsyncToolRuntime:
    def test_async_runtime_exists(self):
        from deepseek_toolkit.async_runtime import AsyncToolRuntime
        rt = AsyncToolRuntime(tools=[], api_key="sk-test")
        assert rt is not None

    def test_chat_async_is_coroutine(self):
        import asyncio
        from deepseek_toolkit.async_runtime import AsyncToolRuntime
        rt = AsyncToolRuntime(tools=[], api_key="sk-test")
        assert asyncio.iscoroutinefunction(rt.chat_async)

    def test_chat_stream_async_is_async_generator(self):
        import inspect
        from deepseek_toolkit.async_runtime import AsyncToolRuntime
        rt = AsyncToolRuntime(tools=[], api_key="sk-test")
        assert inspect.isasyncgenfunction(rt.chat_stream_async)
