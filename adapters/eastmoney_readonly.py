"""无需 Token 的东方财富公开行情只读适配器。

只访问公开行情 HTTP 接口，不读取账户，也不包含交易函数。
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, time as clock_time, timezone, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SYMBOL_PATTERN = re.compile(r"^(?:[036]\d{5}\.(?:SZ|SH)|68\d{4}\.SH|[489]\d{5}\.BJ)$")
CHINA_TZ = timezone(timedelta(hours=8))
QUOTE_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
TRENDS_URL = "https://push2.eastmoney.com/api/qt/stock/trends2/get"
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "application/json,text/plain,*/*",
    "Connection": "close",
}


class EastMoneyError(RuntimeError):
    pass


def _validate_symbols(symbols: list[str]) -> None:
    if not symbols:
        raise ValueError("股票代码列表不能为空")
    invalid = [symbol for symbol in symbols if not SYMBOL_PATTERN.fullmatch(symbol)]
    if invalid:
        raise ValueError(f"无效A股代码：{invalid}")


def _secid(symbol: str) -> str:
    code, exchange = symbol.split(".")
    return f"{1 if exchange == 'SH' else 0}.{code}"


def _request_json(url: str, params: dict[str, Any], retries: int = 3) -> dict[str, Any]:
    params = {**params, "_": int(time.time() * 1000)}
    target = f"{url}?{urlencode(params)}"
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = Request(target, headers=HEADERS)
            with urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("rc") != 0 or payload.get("data") is None:
                raise EastMoneyError(f"东方财富接口返回异常：rc={payload.get('rc')}")
            return payload
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError, EastMoneyError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(0.4 * (2**attempt))
    raise EastMoneyError(f"东方财富行情请求失败：{last_error}") from last_error


def _scaled(value: Any, divisor: float = 100.0) -> float | None:
    if value in (None, "-"):
        return None
    return round(float(value) / divisor, 4)


def _quote_from_data(
    symbol: str, data: dict[str, Any], now: datetime | None = None
) -> dict[str, Any]:
    observed = data.get("f124")
    market_data_at = None
    age_seconds = None
    if isinstance(observed, (int, float)) and observed > 0:
        observed_at = datetime.fromtimestamp(observed, CHINA_TZ)
        market_data_at = observed_at.isoformat(timespec="seconds")
        age_seconds = max(0.0, ((now or datetime.now(CHINA_TZ)) - observed_at).total_seconds())
    return {
        "ts_code": symbol,
        "name": data.get("f14"),
        "market_data_at": market_data_at,
        "age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
        "open": data.get("f17"),
        "high": data.get("f15"),
        "low": data.get("f16"),
        "close": data.get("f2"),
        "pre_close": data.get("f18"),
        "change": data.get("f4"),
        "pct_change": data.get("f3"),
        "volume": data.get("f5"),
        "turnover": data.get("f6"),
        "provider": "eastmoney_public",
    }


def realtime_quotes(symbols: list[str]) -> list[dict[str, Any]]:
    _validate_symbols(symbols)
    fields = "f2,f3,f4,f5,f6,f12,f13,f14,f15,f16,f17,f18,f124"
    payload = _request_json(
        QUOTE_URL,
        {"fltt": 2, "secids": ",".join(_secid(symbol) for symbol in symbols), "fields": fields},
    )
    by_code = {str(item.get("f12")): item for item in payload["data"].get("diff", [])}
    missing = [symbol for symbol in symbols if symbol.split(".")[0] not in by_code]
    if missing:
        raise EastMoneyError(f"东方财富行情缺少股票：{missing}")
    now = datetime.now(CHINA_TZ)
    status = market_status(now)
    rows = [_quote_from_data(symbol, by_code[symbol.split(".")[0]], now) for symbol in symbols]
    market_open = status["session"].startswith("OPEN_")
    for row in rows:
        age = row["age_seconds"]
        if market_open and (age is None or age > 90):
            raise EastMoneyError(f"东方财富行情已陈旧：{row['ts_code']}，超过90秒")
        row["market_session"] = status["session"]
        row["actionable_for_new_orders"] = bool(market_open and age is not None and age <= 90)
    return rows


def _parse_trend(symbol: str, item: str) -> dict[str, Any]:
    parts = item.split(",")
    if len(parts) < 8:
        raise EastMoneyError(f"分钟行情字段不足：{symbol}")
    return {
        "ts_code": symbol,
        "datetime": parts[0],
        "open": float(parts[1]),
        "close": float(parts[2]),
        "high": float(parts[3]),
        "low": float(parts[4]),
        "volume": float(parts[5]),
        "turnover": float(parts[6]),
        "average": float(parts[7]),
        "provider": "eastmoney_public",
    }


def realtime_minutes(symbols: list[str], freq: str = "1MIN") -> list[dict[str, Any]]:
    _validate_symbols(symbols)
    if freq.upper() != "1MIN":
        raise ValueError("东方财富公开接口当前只支持1MIN")
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        payload = _request_json(
            TRENDS_URL,
            {
                "secid": _secid(symbol),
                "ndays": 1,
                "iscr": 0,
                "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            },
        )
        trends = payload["data"].get("trends") or []
        rows.extend(_parse_trend(symbol, item) for item in trends)
    return rows


def _parse_kline(symbol: str, item: str) -> dict[str, Any]:
    parts = item.split(",")
    if len(parts) < 11:
        raise EastMoneyError(f"日线行情字段不足：{symbol}")
    return {
        "ts_code": symbol,
        "trade_date": parts[0],
        "open": float(parts[1]),
        "close": float(parts[2]),
        "high": float(parts[3]),
        "low": float(parts[4]),
        "volume": float(parts[5]),
        "turnover": float(parts[6]),
        "amplitude_pct": float(parts[7]),
        "pct_change": float(parts[8]),
        "change": float(parts[9]),
        "turnover_rate": float(parts[10]),
        "provider": "eastmoney_public",
    }


def historical_daily(symbols: list[str], limit: int = 120, adjust: str = "none") -> list[dict[str, Any]]:
    _validate_symbols(symbols)
    if not 1 <= limit <= 5000:
        raise ValueError("limit must be between 1 and 5000")
    adjust_map = {"none": 0, "forward": 1, "backward": 2}
    if adjust not in adjust_map:
        raise ValueError("adjust must be 'none', 'forward' or 'backward'")
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        payload = _request_json(
            KLINE_URL,
            {
                "secid": _secid(symbol),
                "klt": 101,
                "fqt": adjust_map[adjust],
                "lmt": limit,
                "end": 20500101,
                "iscca": 1,
                "fields1": "f1,f2,f3,f4,f5,f6,f7,f8",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            },
        )
        klines = payload["data"].get("klines") or []
        rows.extend(_parse_kline(symbol, item) for item in klines[-limit:])
    return rows


def market_status(now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ)
    weekday = current.weekday()
    value = current.time()
    if weekday >= 5:
        session = "CLOSED_WEEKEND"
    elif clock_time(9, 30) <= value <= clock_time(11, 30):
        session = "OPEN_MORNING"
    elif clock_time(11, 30) < value < clock_time(13, 0):
        session = "LUNCH_BREAK"
    elif clock_time(13, 0) <= value <= clock_time(15, 0):
        session = "OPEN_AFTERNOON"
    else:
        session = "CLOSED"
    return {
        "provider": "eastmoney_public",
        "snapshot_required": False,
        "session": session,
        "checked_at": current.isoformat(timespec="seconds"),
        "read_only": True,
    }
