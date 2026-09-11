"""Local, read-only MCP bridge for A-share market and account data.

Install locally with: pip install mcp
No order, cancel, transfer, or credential-reading tool is exposed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from tushare_readonly import realtime_minutes as tushare_minutes
from tushare_readonly import realtime_quotes as tushare_quotes
from eastmoney_readonly import historical_daily as eastmoney_daily
from eastmoney_readonly import market_status as eastmoney_status
from eastmoney_readonly import realtime_minutes as eastmoney_minutes
from eastmoney_readonly import realtime_quotes as eastmoney_quotes
from supermind_market_snapshot import (
    SuperMindSnapshotError,
    historical_bars as supermind_historical_bars,
    market_status as supermind_status,
    realtime_minutes as supermind_minutes,
    realtime_quotes as supermind_quotes,
)


mcp = FastMCP("A-share read-only")


def _provider() -> str:
    requested = os.environ.get("ASHARE_PROVIDER", "auto").strip().lower()
    if requested not in {"auto", "tushare", "supermind", "eastmoney"}:
        raise ValueError("ASHARE_PROVIDER must be auto, tushare, supermind or eastmoney")
    if requested != "auto":
        return requested
    if os.environ.get("TUSHARE_TOKEN", "").strip():
        return "tushare"
    raw_path = os.environ.get("ASHARE_MARKET_SNAPSHOT", "runtime/supermind_market_snapshot.json")
    if Path(raw_path).expanduser().resolve().is_file():
        return "supermind"
    return "eastmoney"


@mcp.tool()
def get_realtime_quotes(ts_codes: list[str]) -> list[dict]:
    """Return current A-share quote rows for codes such as 601975.SH."""
    provider = _provider()
    if provider == "tushare":
        return tushare_quotes(ts_codes)
    if provider == "supermind":
        try:
            return supermind_quotes(ts_codes)
        except SuperMindSnapshotError:
            # 自动模式下，陈旧快照不能阻断只读实时行情；显式指定
            # ASHARE_PROVIDER=supermind 时仍保留失败关闭语义。
            if os.environ.get("ASHARE_PROVIDER", "auto").strip().lower() != "auto":
                raise
            return eastmoney_quotes(ts_codes)
    return eastmoney_quotes(ts_codes)


@mcp.tool()
def get_realtime_minutes(ts_codes: list[str], freq: str = "1MIN") -> list[dict]:
    """Return current-day A-share minute bars at a documented frequency."""
    provider = _provider()
    if provider == "tushare":
        return tushare_minutes(ts_codes, freq)
    if provider == "eastmoney":
        return eastmoney_minutes(ts_codes, freq)
    if freq.upper() != "1MIN":
        raise ValueError("SuperMind快照当前只支持1MIN；其他周期请配置TUSHARE_TOKEN")
    try:
        return supermind_minutes(ts_codes)
    except SuperMindSnapshotError:
        if os.environ.get("ASHARE_PROVIDER", "auto").strip().lower() != "auto":
            raise
        return eastmoney_minutes(ts_codes, freq)


@mcp.tool()
def get_market_status() -> dict:
    """Return provider, snapshot time, age and available symbols."""
    provider = _provider()
    if provider == "tushare":
        return {"provider": "tushare", "snapshot_required": False}
    if provider == "supermind":
        return supermind_status()
    return eastmoney_status()


@mcp.tool()
def get_public_daily_bars(
    ts_codes: list[str], limit: int = 120, adjust: str = "none"
) -> list[dict]:
    """Read public daily A-share bars without an account or token."""
    return eastmoney_daily(ts_codes, limit, adjust)


@mcp.tool()
def get_snapshot_daily_bars(ts_codes: list[str], limit: int = 120) -> list[dict]:
    """Read daily bars from the downloaded SuperMind snapshot, including after close."""
    return supermind_historical_bars(ts_codes, "daily", limit)


@mcp.tool()
def get_snapshot_minute_bars(ts_codes: list[str], limit: int = 240) -> list[dict]:
    """Read minute bars from the downloaded SuperMind snapshot, including after close."""
    return supermind_historical_bars(ts_codes, "minute", limit)


@mcp.tool()
def get_account_snapshot() -> dict:
    """Read the latest local snapshot exported by SuperMind."""
    raw_path = os.environ.get("ASHARE_ACCOUNT_SNAPSHOT", "account_snapshot.json")
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"account snapshot not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = {"generated_at", "portfolio", "positions"}
    missing = required.difference(payload)
    if missing:
        raise ValueError(f"invalid account snapshot, missing: {sorted(missing)}")
    return payload


if __name__ == "__main__":
    mcp.run(transport="stdio")
