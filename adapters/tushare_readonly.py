"""Read-only Tushare Pro client for A-share live quotes and bars.

The token is read from TUSHARE_TOKEN. This module never sends orders and never
persists the token. It uses the documented Tushare HTTP API directly so the
project does not require the optional tushare Python package.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any


API_URL = "https://api.tushare.pro"


class TushareError(RuntimeError):
    pass


def _token() -> str:
    value = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not value:
        raise TushareError("TUSHARE_TOKEN is not configured")
    return value


def call(api_name: str, params: dict[str, Any], fields: str = "") -> list[dict[str, Any]]:
    payload = json.dumps(
        {"api_name": api_name, "token": _token(), "params": params, "fields": fields}
    ).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "ashare-readonly/2.1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # network and JSON errors are both fail-closed
        raise TushareError(f"Tushare request failed: {exc}") from exc

    if body.get("code") != 0:
        raise TushareError(body.get("msg") or f"Tushare error code {body.get('code')}")
    data = body.get("data") or {}
    names = data.get("fields") or []
    return [dict(zip(names, row)) for row in data.get("items") or []]


def realtime_quotes(ts_codes: list[str]) -> list[dict[str, Any]]:
    if not ts_codes:
        return []
    return call("rt_k", {"ts_code": ",".join(ts_codes)})


def realtime_minutes(ts_codes: list[str], freq: str = "1MIN") -> list[dict[str, Any]]:
    allowed = {"1MIN", "5MIN", "15MIN", "30MIN", "60MIN"}
    if freq not in allowed:
        raise ValueError(f"freq must be one of {sorted(allowed)}")
    if not ts_codes:
        return []
    return call("rt_min", {"ts_code": ",".join(ts_codes), "freq": freq})

