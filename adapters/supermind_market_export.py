"""在 SuperMind 研究环境中运行，导出只读 A 股行情快照。

该脚本只调用 ``get_price``，不导入 TradeAPI，也不包含任何交易函数。
运行后会在研究环境当前目录生成 ``supermind_market_snapshot.json``；
请通过研究环境的文件列表下载到本地项目 ``runtime/`` 目录。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
from mindgo_api import get_price


SYMBOLS = ["000001.SZ", "601975.SH", "601555.SH"]
OUTPUT_PATH = "supermind_market_snapshot.json"
DAILY_BAR_COUNT = 120
MINUTE_BAR_COUNT = 240
CHINA_TZ = timezone(timedelta(hours=8))


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    try:
        if value != value:  # NaN
            return None
    except Exception:
        pass
    return value


def _frame_rows(frame: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for timestamp, series in frame.iterrows():
        row = {"datetime": _json_value(timestamp)}
        row.update({str(key): _json_value(value) for key, value in series.items()})
        rows.append(row)
    return rows


def _as_symbol_map(result: Any, symbols: List[str]) -> Dict[str, Any]:
    if isinstance(result, dict):
        return result
    if len(symbols) != 1:
        raise TypeError("SuperMind returned a non-dict result for multiple symbols")
    return {symbols[0]: result}


def export_snapshot(symbols: Optional[List[str]] = None) -> str:
    selected = list(symbols or SYMBOLS)
    if not selected:
        raise ValueError("SYMBOLS must not be empty")

    now = datetime.now(CHINA_TZ)
    common_fields = ["open", "high", "low", "close", "volume", "turnover"]
    daily = get_price(
        selected, None, now, "1d", common_fields,
        skip_paused=False, fq=None, bar_count=DAILY_BAR_COUNT, is_panel=False,
    )
    minute_start = now.replace(hour=9, minute=30, second=0, microsecond=0)
    minutes = get_price(
        selected, minute_start, now, "1m", common_fields,
        # SuperMind 要求 bar_count 为整数；0 表示使用给定时间范围。
        skip_paused=False, fq=None, bar_count=0, is_panel=False,
    )

    daily_map = _as_symbol_map(daily, selected)
    minute_map = _as_symbol_map(minutes, selected)
    payload: Dict[str, Any] = {
        "schema_version": 1,
        "source": "supermind_get_price",
        "generated_at": now.isoformat(timespec="seconds"),
        "symbols": selected,
        "daily_bars": {},
        "minute_bars": {},
        "quotes": {},
    }

    latest_times: List[str] = []
    for symbol in selected:
        daily_rows = _frame_rows(daily_map[symbol])
        minute_rows = _frame_rows(minute_map[symbol])
        payload["daily_bars"][symbol] = daily_rows
        payload["minute_bars"][symbol] = minute_rows
        latest = minute_rows[-1] if minute_rows else (daily_rows[-1] if daily_rows else None)
        if latest:
            payload["quotes"][symbol] = dict(latest)
            latest_times.append(str(latest["datetime"]))

    payload["market_data_at"] = max(latest_times) if latest_times else None
    pd.Series(payload, dtype=object).to_json(
        OUTPUT_PATH, force_ascii=False, indent=2
    )
    print(f"只读行情快照已生成：{OUTPUT_PATH}")
    print(f"股票数：{len(selected)}；行情时间：{payload['market_data_at']}")
    return OUTPUT_PATH


export_snapshot()
