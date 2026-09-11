"""读取并校验从 SuperMind 研究环境下载的只读行情快照。"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SYMBOL_PATTERN = re.compile(r"^(?:[036]\d{5}\.(?:SZ|SH)|68\d{4}\.SH|[489]\d{5}\.BJ)$")
DEFAULT_PATH = "runtime/supermind_market_snapshot.json"


class SuperMindSnapshotError(RuntimeError):
    pass


def snapshot_path() -> Path:
    raw = os.environ.get("ASHARE_MARKET_SNAPSHOT", DEFAULT_PATH)
    return Path(raw).expanduser().resolve()


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc).astimezone()
    return parsed


def load_snapshot(path: Path | None = None) -> dict[str, Any]:
    selected = (path or snapshot_path()).resolve()
    if not selected.is_file():
        raise SuperMindSnapshotError(f"SuperMind行情快照不存在：{selected}")
    try:
        payload = json.loads(selected.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SuperMindSnapshotError(f"无法读取SuperMind行情快照：{exc}") from exc
    required = {"schema_version", "source", "generated_at", "market_data_at", "quotes", "minute_bars"}
    missing = required.difference(payload)
    if missing:
        raise SuperMindSnapshotError(f"行情快照缺少字段：{sorted(missing)}")
    if payload["schema_version"] != 1 or payload["source"] != "supermind_get_price":
        raise SuperMindSnapshotError("不支持的SuperMind行情快照格式")
    if not isinstance(payload["quotes"], dict) or not isinstance(payload["minute_bars"], dict):
        raise SuperMindSnapshotError("行情快照的quotes/minute_bars格式错误")
    return payload


def snapshot_age_seconds(payload: dict[str, Any], now: datetime | None = None) -> float:
    market_time = payload.get("market_data_at")
    if not market_time:
        raise SuperMindSnapshotError("行情快照没有有效market_data_at")
    observed = _parse_time(str(market_time))
    current = now or datetime.now(observed.tzinfo)
    if current.tzinfo is None:
        current = current.replace(tzinfo=observed.tzinfo)
    return max(0.0, (current.astimezone(observed.tzinfo) - observed).total_seconds())


def require_fresh(payload: dict[str, Any], max_age_seconds: int = 90) -> None:
    age = snapshot_age_seconds(payload)
    if age > max_age_seconds:
        raise SuperMindSnapshotError(
            f"SuperMind行情已陈旧：{age:.0f}秒，阈值为{max_age_seconds}秒"
        )


def _validate_symbols(symbols: list[str]) -> None:
    invalid = [symbol for symbol in symbols if not SYMBOL_PATTERN.fullmatch(symbol)]
    if invalid:
        raise ValueError(f"无效A股代码：{invalid}")


def realtime_quotes(symbols: list[str], max_age_seconds: int = 90) -> list[dict[str, Any]]:
    _validate_symbols(symbols)
    payload = load_snapshot()
    require_fresh(payload, max_age_seconds)
    missing = [symbol for symbol in symbols if symbol not in payload["quotes"]]
    if missing:
        raise SuperMindSnapshotError(f"行情快照不包含股票：{missing}")
    return [{"ts_code": symbol, **payload["quotes"][symbol]} for symbol in symbols]


def realtime_minutes(symbols: list[str], max_age_seconds: int = 90) -> list[dict[str, Any]]:
    _validate_symbols(symbols)
    payload = load_snapshot()
    require_fresh(payload, max_age_seconds)
    missing = [symbol for symbol in symbols if symbol not in payload["minute_bars"]]
    if missing:
        raise SuperMindSnapshotError(f"分钟行情快照不包含股票：{missing}")
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        rows.extend({"ts_code": symbol, **row} for row in payload["minute_bars"][symbol])
    return rows


def historical_bars(
    symbols: list[str], kind: str = "daily", limit: int = 120
) -> list[dict[str, Any]]:
    """读取快照中的历史K线；允许收盘后使用，但仍返回原始行情时间。"""
    _validate_symbols(symbols)
    if kind not in {"daily", "minute"}:
        raise ValueError("kind must be 'daily' or 'minute'")
    if not 1 <= limit <= 5000:
        raise ValueError("limit must be between 1 and 5000")
    payload = load_snapshot()
    key = "daily_bars" if kind == "daily" else "minute_bars"
    bars = payload.get(key)
    if not isinstance(bars, dict):
        raise SuperMindSnapshotError(f"行情快照缺少有效{key}")
    missing = [symbol for symbol in symbols if symbol not in bars]
    if missing:
        raise SuperMindSnapshotError(f"行情快照不包含股票：{missing}")
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        rows.extend({"ts_code": symbol, **row} for row in bars[symbol][-limit:])
    return rows


def market_status() -> dict[str, Any]:
    payload = load_snapshot()
    return {
        "provider": "supermind_snapshot",
        "generated_at": payload["generated_at"],
        "market_data_at": payload["market_data_at"],
        "age_seconds": round(snapshot_age_seconds(payload), 1),
        "symbols": sorted(payload["quotes"]),
    }
