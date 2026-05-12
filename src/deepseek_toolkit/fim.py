"""FIM (Fill-in-the-Middle) completions via DeepSeek beta endpoint.

POST https://api.deepseek.com/beta/completions

Uses the OpenAI Completions API format with FIM tokens:
    <|fim_begin|>prefix<|fim_hole|>suffix<|fim_end|>
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from openai import OpenAI

FIM_BASE_URL = "https://api.deepseek.com/beta"


def _make_fim_client(api_key: str | None, timeout: float) -> OpenAI:
    import os
    key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    return OpenAI(api_key=key, base_url=FIM_BASE_URL, timeout=timeout)


@dataclass
class FIMResponse:
    """Result from a FIM completion request."""
    text: str
    model: str
    finish_reason: str | None = None
    usage: dict | None = None


@dataclass
class FIMChunk:
    """A single chunk from a streaming FIM completion."""
    text: str
    finish_reason: str | None = None


def fim_complete(
    prefix: str,
    suffix: str,
    *,
    model: str,
    api_key: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    stop: list[str] | None = None,
    timeout: float = 60.0,
    **kwargs,
) -> FIMResponse:
    """Send a FIM completion request and return the full response.

    Args:
        prefix: Code/text before the cursor.
        suffix: Code/text after the cursor.
        model: Model name (e.g. "deepseek-v4-pro").
        api_key: DeepSeek API key (defaults to env var).
        max_tokens: Maximum tokens to generate.
        temperature: Sampling temperature.
        top_p: Nucleus sampling parameter.
        stop: Stop sequences.
        timeout: Request timeout in seconds.
    """
    client = _make_fim_client(api_key, timeout)
    prompt = _build_fim_prompt(prefix, suffix)

    params: dict = {"model": model, "prompt": prompt, **kwargs}
    if max_tokens is not None:
        params["max_tokens"] = max_tokens
    if temperature is not None:
        params["temperature"] = temperature
    if top_p is not None:
        params["top_p"] = top_p
    if stop is not None:
        params["stop"] = stop

    # Retry logic: 3 attempts with exponential backoff
    import time as _time
    for attempt in range(3):
        try:
            response = client.completions.create(**params)
            break
        except Exception as e:
            if attempt == 2:
                raise
            delay = 2 ** attempt + _time.time() % 1.0
            _time.sleep(delay)

    choice = response.choices[0]

    return FIMResponse(
        text=choice.text,
        model=response.model,
        finish_reason=choice.finish_reason,
        usage={
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        } if response.usage else None,
    )


def fim_complete_stream(
    prefix: str,
    suffix: str,
    *,
    model: str,
    api_key: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    stop: list[str] | None = None,
    timeout: float = 60.0,
    **kwargs,
) -> Iterator[FIMChunk]:
    """Send a streaming FIM completion request, yielding chunks.

    Args:
        prefix: Code/text before the cursor.
        suffix: Code/text after the cursor.
        model: Model name.
        api_key: DeepSeek API key.
        max_tokens: Maximum tokens to generate.
        temperature: Sampling temperature.
        top_p: Nucleus sampling parameter.
        stop: Stop sequences.
        timeout: Request timeout in seconds.
    """
    client = _make_fim_client(api_key, timeout)
    prompt = _build_fim_prompt(prefix, suffix)

    params: dict = {"model": model, "prompt": prompt, "stream": True, **kwargs}
    if max_tokens is not None:
        params["max_tokens"] = max_tokens
    if temperature is not None:
        params["temperature"] = temperature
    if top_p is not None:
        params["top_p"] = top_p
    if stop is not None:
        params["stop"] = stop

    stream = client.completions.create(**params)
    for event in stream:
        choice = event.choices[0] if event.choices else None
        if choice is None:
            continue
        yield FIMChunk(
            text=choice.text or "",
            finish_reason=choice.finish_reason,
        )


def _build_fim_prompt(prefix: str, suffix: str) -> str:
    """Build the FIM prompt with special tokens."""
    return f"<|fim_begin|>{prefix}<|fim_hole|>{suffix}<|fim_end|>"
