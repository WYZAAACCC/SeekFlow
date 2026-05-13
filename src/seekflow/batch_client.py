"""Batch API client for DeepSeek batch processing."""
from __future__ import annotations

import io
import json
import time
from collections.abc import Iterator


class BatchExpiredError(Exception):
    """Raised when a batch job has expired."""


class BatchTimeoutError(TimeoutError):
    """Raised when batch polling exceeds max_wait."""


class BatchClient:
    """Client for DeepSeek Batch API: submit, poll, download.

    Wraps a DeepSeekClient to access the underlying OpenAI-compatible
    files and batches endpoints.
    """

    def __init__(self, client: object, poll_interval: float = 30.0):
        from seekflow.client import DeepSeekClient
        if isinstance(client, DeepSeekClient):
            self._openai = client._client
        else:
            self._openai = client._client  # Assume it has _client attribute
        self.poll_interval = poll_interval

    # ------------------------------------------------------------------
    # submit_batch
    # ------------------------------------------------------------------

    def submit_batch(self, requests: list[dict]) -> str:
        """Submit a batch of chat completion requests.

        Args:
            requests: List of dicts, each with ``custom_id`` and ``body`` keys.
                      If ``custom_id`` is missing, ``f"req-{index}"`` is used.

        Returns:
            The batch ID string.
        """
        # Build JSONL
        lines = []
        for i, req in enumerate(requests):
            entry = {
                "custom_id": req.get("custom_id", f"req-{i}"),
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": req["body"],
            }
            lines.append(json.dumps(entry, ensure_ascii=False))
        jsonl_content = "\n".join(lines)

        # Upload file with retry (3 attempts)
        file_bytes = jsonl_content.encode("utf-8")
        upload = None
        for attempt in range(3):
            try:
                upload = self._openai.files.create(
                    file=("batch_input.jsonl", io.BytesIO(file_bytes), "application/jsonl"),
                    purpose="batch",
                )
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(1.0 * (2 ** attempt))

        # Create batch
        batch = self._openai.batches.create(
            input_file_id=upload.id,
            endpoint="/v1/chat/completions",
            completion_window="24h",
        )
        return batch.id

    # ------------------------------------------------------------------
    # poll_batch
    # ------------------------------------------------------------------

    def poll_batch(
        self,
        batch_id: str,
        poll_interval: float | None = None,
        max_wait: float = 3600.0,
    ) -> tuple[str, object]:
        """Poll a batch job until it reaches a terminal state.

        Returns:
            Tuple of (status_string, batch_object).

        Raises:
            BatchExpiredError: If the batch expires.
            BatchTimeoutError: If *max_wait* is exceeded.
        """
        interval = poll_interval if poll_interval is not None else self.poll_interval
        deadline = time.monotonic() + max_wait

        while True:
            batch = self._openai.batches.retrieve(batch_id)
            status = batch.status

            if status in ("completed", "failed", "cancelled"):
                return status, batch

            if status == "expired":
                raise BatchExpiredError(f"Batch {batch_id} has expired")

            if time.monotonic() > deadline:
                completed = getattr(batch, "request_counts", {})
                raise BatchTimeoutError(
                    f"Batch {batch_id} did not complete within {max_wait}s. "
                    f"Completed: {completed.get('completed', 0)}/{completed.get('total', '?')}"
                )

            time.sleep(interval)

    # ------------------------------------------------------------------
    # download_results
    # ------------------------------------------------------------------

    def download_results(self, batch_id: str) -> list[dict]:
        """Download and parse the results of a completed batch.

        Returns:
            List of result dicts sorted by ``custom_id``.
            Each dict has keys: ``custom_id``, ``status_code``, ``response``, ``error``.
        """
        batch = self._openai.batches.retrieve(batch_id)
        if not getattr(batch, "output_file_id", None):
            return []

        content = self._openai.files.content(batch.output_file_id)
        if hasattr(content, "read"):
            raw = content.read()
        else:
            raw = str(content)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        raw = raw.strip()

        if not raw:
            return []

        results = []
        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            response_data = entry.get("response", {})
            status_code = response_data.get("status_code")
            error = None
            if status_code and status_code >= 400:
                error = response_data.get("body", {}).get("error", {})
            results.append({
                "custom_id": entry["custom_id"],
                "status_code": status_code,
                "response": response_data.get("body"),
                "error": error,
            })

        # Sort by custom_id to match request order
        results.sort(key=lambda r: r["custom_id"])
        return results
