"""Account balance query via GET https://api.deepseek.com/user/balance."""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

import requests

from seekflow.errors import map_http_error

CACHE_TTL = 300  # seconds

_balance_cache: dict[str, tuple[float, "BalanceInfo"]] = {}


def _safe_decimal(value, default: str = "0.00") -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


@dataclass
class BalanceInfo:
    """Account balance information. All monetary fields are Decimal for safe arithmetic."""
    total_balance: Decimal = Decimal("0.00")
    topped_up_balance: Decimal = Decimal("0.00")
    granted_balance: Decimal = Decimal("0.00")
    currency: str = "CNY"
    is_available: bool = False
    queried_at: float = 0.0


def get_balance(api_key: str | None = None, timeout: float = 30.0) -> BalanceInfo:
    """Query DeepSeek account balance.

    Results are cached for CACHE_TTL seconds using a hashed key
    to avoid storing raw API keys in the cache dict.
    """
    import os
    key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    cache_key = hashlib.sha256(key.encode()).hexdigest()

    # Check cache
    now = time.time()
    if cache_key in _balance_cache:
        cached_at, cached_info = _balance_cache[cache_key]
        if now - cached_at < CACHE_TTL:
            return cached_info

    url = "https://api.deepseek.com/user/balance"
    headers = {"Authorization": f"Bearer {key}"}

    resp = requests.get(url, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        body = resp.json() if resp.text else {}
        raise map_http_error(
            resp.status_code,
            body.get("error", resp.text),
            headers=dict(resp.headers),
        )

    data = resp.json()
    is_available = data.get("is_available", False)
    infos = data.get("balance_infos", [])
    if infos:
        bi = infos[0]
        info = BalanceInfo(
            total_balance=_safe_decimal(bi.get("total_balance", "0.00")),
            topped_up_balance=_safe_decimal(bi.get("topped_up_balance", "0.00")),
            granted_balance=_safe_decimal(bi.get("granted_balance", "0.00")),
            currency=bi.get("currency", "CNY"),
            is_available=is_available,
            queried_at=now,
        )
    else:
        info = BalanceInfo(is_available=is_available, queried_at=now)

    _balance_cache[cache_key] = (now, info)
    return info
