"""收盘后用东方财富公开只读快照增量追加全 A 日线。

该模块只读取公开行情，不读取账户，也不包含下单、撤单或转账函数。
它要求 SuperMind 历史底库已经生成 ``runtime/s1_daily.csv``，之后每天
只追加一个已完成交易日，并对日期、覆盖率、单位和重复写入做失败关闭。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time as clock_time, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "adapters"))

from adapters.eastmoney_readonly import (  # noqa: E402
    QUOTE_URL,
    _request_json,
    _secid,
    historical_daily,
)
from prepare_supermind_scan_data import load_universe  # noqa: E402
from s1_engine import load_config  # noqa: E402


CHINA_TZ = timezone(timedelta(hours=8))
TENCENT_BENCHMARK_URL = (
    "https://web.ifzq.gtimg.cn/appstock/app/kline/kline?"
    "param=sh000905,day,,,{limit}"
)
SOHU_HISTORY_URL = "https://q.stock.sohu.com/hisHq"
SINA_QUOTE_URL = "https://hq.sinajs.cn/list="
DAILY_COLUMNS = [
    "date", "symbol", "open", "high", "low", "close",
    "volume", "amount", "paused", "st", "listing_days",
]


class IncrementalUpdateError(RuntimeError):
    """数据质量不足或已有数据冲突时停止更新。"""


def _tencent_benchmark(limit: int) -> list[dict[str, Any]]:
    request = Request(
        TENCENT_BENCHMARK_URL.format(limit=limit),
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"},
    )
    with urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    block = payload.get("data", {}).get("sh000905", {})
    values = block.get("day") or block.get("qfqday") or []
    rows = []
    for item in values:
        if len(item) < 5:
            continue
        rows.append({
            "ts_code": "000905.SH",
            "trade_date": item[0],
            "open": float(item[1]),
            "close": float(item[2]),
            "high": float(item[3]),
            "low": float(item[4]),
            "volume": float(item[5]) if len(item) > 5 else 0.0,
            "turnover": 0.0,
            "provider": "tencent_public_fallback",
        })
    if not rows:
        raise IncrementalUpdateError("腾讯中证500兜底数据为空")
    return rows


def fetch_benchmark_with_retry(limit: int = 10) -> list[dict[str, Any]]:
    fallback_error: Exception | None = None
    try:
        return _tencent_benchmark(limit)
    except Exception as exc:
        fallback_error = exc
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            return historical_daily(["000905.SH"], limit=limit)
        except Exception as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise IncrementalUpdateError(
        f"中证500腾讯源和东方财富源均失败：{fallback_error}; {last_error}"
    ) from last_error


def cached_research_benchmark(runtime: Path, limit: int = 10) -> list[dict[str, Any]]:
    paths = sorted((runtime / "fast_research").glob("????-??-??/benchmark_for_scan.csv"))
    if not paths:
        return []
    frame = pd.read_csv(paths[-1]).tail(limit)
    return [
        {
            "ts_code": "000905.SH",
            "trade_date": str(pd.Timestamp(row["date"]).date()),
            "close": float(row["close"]),
            "provider": "tencent_public_cached_research",
        }
        for row in frame.to_dict("records")
    ]


def benchmark_rows_for_update(
    runtime: Path, current: datetime, limit: int = 10
) -> list[dict[str, Any]]:
    """增量更新优先读取实时公开源，缓存仅作失败兜底。

    不能无条件优先缓存，否则缓存最后日期会永久限制目标日期，导致工作日
    收盘后仍被错误判定为ALREADY_CURRENT。
    """
    try:
        return fetch_benchmark_with_retry(limit=limit)
    except Exception as live_error:
        cached = cached_research_benchmark(runtime, limit=limit)
        if not cached:
            raise
        local_now = current.astimezone(CHINA_TZ)
        cached_last = max(pd.Timestamp(row["trade_date"]).normalize() for row in cached)
        today = pd.Timestamp(local_now.date())
        after_close_on_weekday = (
            local_now.weekday() < 5 and local_now.time() >= clock_time(15, 10)
        )
        if after_close_on_weekday and cached_last < today:
            raise IncrementalUpdateError(
                f"中证500实时源失败且研究缓存停在{cached_last.date()}，"
                f"不能据此判断{today.date()}是否为交易日：{live_error}"
            ) from live_error
        return cached


def account_tradable_symbols(
    metadata: dict[str, dict[str, Any]], cfg: dict[str, Any]
) -> list[str]:
    """只增量维护账户可交易板块；被硬排除板块不参与排名。"""
    universe = cfg["universe"]
    prefixes = tuple(str(value) for value in universe.get("excluded_symbol_prefixes", []))
    exchanges = {str(value).upper() for value in universe.get("excluded_exchanges", [])}
    return sorted(
        symbol
        for symbol in metadata
        if not (prefixes and symbol.startswith(prefixes))
        and symbol.rsplit(".", 1)[-1].upper() not in exchanges
    )


def _sohu_history_batch(
    symbols: list[str], target: pd.Timestamp
) -> dict[str, list[dict[str, Any]]]:
    """批量读取目标日前约40天日K；成交量为手、成交额为万元。"""
    target = pd.Timestamp(target).normalize()
    by_code = {symbol.split(".")[0]: symbol for symbol in symbols}
    params = {
        "code": ",".join(f"cn_{code}" for code in by_code),
        "start": (target - pd.Timedelta(days=40)).strftime("%Y%m%d"),
        "end": target.strftime("%Y%m%d"),
        "stat": 1,
        "order": "D",
        "period": "d",
        "rt": "json",
    }
    request = Request(
        f"{SOHU_HISTORY_URL}?{urlencode(params)}",
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://q.stock.sohu.com/"},
    )
    with urlopen(request, timeout=15) as response:
        raw = response.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        # 搜狐响应头未声明字符集，包含证券中文名时实际可能为 GBK。
        text = raw.decode("gb18030")
    payload = json.loads(text)
    result: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in symbols}
    for block in payload or []:
        code = str(block.get("code") or "").replace("cn_", "")
        symbol = by_code.get(code)
        if symbol is None:
            continue
        status = int(block.get("status", -1))
        if status not in (0, 2):
            continue
        rows = []
        for item in block.get("hq") or []:
            if len(item) < 9 or item[1] in ("", "-"):
                continue
            rows.append({
                "ts_code": symbol,
                "trade_date": item[0],
                "open": float(item[1]),
                "close": float(item[2]),
                "low": float(item[5]),
                "high": float(item[6]),
                "volume": float(item[7]),
                "turnover": float(item[8]) * 10000.0,
                "provider": "sohu_public_history",
            })
        result[symbol] = sorted(rows, key=lambda row: row["trade_date"])
    return result


def _sohu_history(symbol: str, target: pd.Timestamp) -> list[dict[str, Any]]:
    return _sohu_history_batch([symbol], target)[symbol]


def fetch_historical_target_rows(
    symbols: list[str],
    target: pd.Timestamp,
    metadata: dict[str, dict[str, Any]],
    *,
    workers: int = 6,
    limit: int = 5,
    cache_path: Path | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """盘中补前一交易日时逐股读取已完成K线；缺目标日不得推断停牌。"""
    target = pd.Timestamp(target).normalize()
    row_by_symbol: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, str]] = []
    missing_history: list[str] = []
    paused_symbols: list[str] = []

    if cache_path is not None and cache_path.exists():
        cached = pd.read_csv(cache_path)
        missing_columns = set(DAILY_COLUMNS) - set(cached.columns)
        if missing_columns:
            raise IncrementalUpdateError(f"历史补数缓存缺少字段：{sorted(missing_columns)}")
        cached["date"] = pd.to_datetime(cached["date"]).dt.normalize()
        if not cached.empty and set(cached["date"]) != {target}:
            raise IncrementalUpdateError("历史补数缓存日期与目标日不一致")
        for row in cached[DAILY_COLUMNS].to_dict("records"):
            # 旧缓存可能由“缺日K=停牌”推断生成，缺来源证明的零量/停牌缓存重新查询。
            if row["symbol"] in symbols and row['paused'] is False and float(row['volume']) > 0:
                row_by_symbol[str(row["symbol"])] = row

    pending_symbols = [symbol for symbol in symbols if symbol not in row_by_symbol]
    cached_before_run = len(row_by_symbol)

    def history_to_row(symbol: str, history: list[dict[str, Any]]) -> dict[str, Any]:
        dated = [(pd.Timestamp(item["trade_date"]).normalize(), item) for item in history]
        matches = [item for date, item in dated if date == target]
        paused = False
        if len(matches) == 1:
            item = matches[0]
            open_price = float(item["open"])
            high = float(item["high"])
            low = float(item["low"])
            close = float(item["close"])
            volume = float(item["volume"]) * 100.0
            amount = float(item["turnover"])
        elif not matches:
            raise ValueError("缺目标日K线，不能由旧价格推断停牌")
        else:
            raise ValueError("目标日K线重复")
        security = metadata[symbol]
        listed = pd.Timestamp(security["listed_date"]).normalize()
        if paused:
            paused_symbols.append(symbol)
        return {
            "date": target,
            "symbol": symbol,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": amount,
            "paused": paused,
            "st": "ST" in str(security.get("name") or "").upper(),
            "listing_days": max((target - listed).days, 0),
        }

    # 搜狐支持多代码请求。小批量、有限重试、批间节流可减少 500/503，
    # 每个成功批次都立即写断点，进程中断后只补剩余代码。
    batch_failures: list[dict[str, str]] = []
    batch_size = 15
    for start in range(0, len(pending_symbols), batch_size):
        chunk = pending_symbols[start:start + batch_size]
        histories = None
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                histories = _sohu_history_batch(chunk, target)
                break
            except Exception as exc:
                last_error = exc
                time.sleep(0.8 * (attempt + 1))
        if histories is None:
            batch_failures.extend(
                {"symbol": symbol, "error": str(last_error)} for symbol in chunk
            )
            continue
        for symbol in chunk:
            try:
                row_by_symbol[symbol] = history_to_row(symbol, histories.get(symbol, []))
            except Exception:
                continue
        if cache_path is not None:
            _atomic_csv(
                pd.DataFrame(row_by_symbol.values(), columns=DAILY_COLUMNS),
                cache_path,
            )
        print(
            f"historical batch progress: {min(start + batch_size, len(pending_symbols))}/"
            f"{len(pending_symbols)} (cached total {len(row_by_symbol)}/{len(symbols)})",
            flush=True,
        )
        time.sleep(0.35)

    pending_symbols = [symbol for symbol in symbols if symbol not in row_by_symbol]

    def fetch(symbol: str) -> list[dict[str, Any]]:
        # 搜狐历史端点含真实成交额；失败后再回退东方财富。
        last_error: Exception | None = None
        for attempt in range(3):
            time.sleep(0.25 + (sum(ord(ch) for ch in symbol) % 5) * 0.03)
            try:
                return _sohu_history(symbol, target)
            except Exception as exc:
                last_error = exc
                time.sleep(0.8 * (attempt + 1))
        try:
            return historical_daily([symbol], limit=limit)
        except Exception as exc:
            raise IncrementalUpdateError(
                f"搜狐和东方财富个股历史源均失败：{last_error}; {exc}"
            ) from exc

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch, symbol): symbol for symbol in pending_symbols}
        completed = 0
        for future in as_completed(futures):
            symbol = futures[future]
            completed += 1
            try:
                history = future.result()
            except Exception as exc:
                failures.append({"symbol": symbol, "error": str(exc)})
                continue
            try:
                row_by_symbol[symbol] = history_to_row(symbol, history)
            except Exception as exc:
                missing_history.append(symbol)
                failures.append({"symbol": symbol, "error": str(exc)})
                continue
            if cache_path is not None and len(row_by_symbol) % 100 == 0:
                _atomic_csv(
                    pd.DataFrame(row_by_symbol.values(), columns=DAILY_COLUMNS),
                    cache_path,
                )
            if completed % 500 == 0:
                print(
                    f"historical catch-up progress: {completed}/{len(pending_symbols)} "
                    f"(cached total {len(row_by_symbol)}/{len(symbols)})",
                    flush=True,
                )

    frame = pd.DataFrame(row_by_symbol.values(), columns=DAILY_COLUMNS)
    if cache_path is not None:
        _atomic_csv(frame, cache_path)
    if frame.duplicated(["date", "symbol"]).any():
        raise IncrementalUpdateError("历史补数包含重复date/symbol")
    quality = {
        "mode": "historical_catch_up_sohu_with_eastmoney_fallback",
        "requested_symbols": len(symbols),
        "cached_before_run": cached_before_run,
        "accepted_symbols": len(frame),
        "paused_symbols": paused_symbols,
        "missing_history_symbols": missing_history,
        "quote_failures": failures,
        "batch_failures": batch_failures,
    }
    return frame.sort_values("symbol").reset_index(drop=True), quality


def fetch_snapshot_for_symbols(
    symbols: list[str], *, batch_size: int = 50, delay_seconds: float = 0.2
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, str]]]:
    """通过稳定的批量报价端点读取静态股票池，失败批次自动二分重试。"""
    if not 1 <= batch_size <= 100:
        raise ValueError("batch_size 必须在 1 到 100 之间")
    fields = "f2,f3,f4,f5,f6,f12,f13,f14,f15,f16,f17,f18,f124"
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    failures: list[dict[str, str]] = []

    def fetch_chunk(chunk: list[str]) -> None:
        try:
            payload = _request_json(
                QUOTE_URL,
                {
                    "fltt": 2,
                    "secids": ",".join(_secid(symbol) for symbol in chunk),
                    "fields": fields,
                },
            )
        except Exception as exc:
            if len(chunk) > 1:
                middle = len(chunk) // 2
                fetch_chunk(chunk[:middle])
                fetch_chunk(chunk[middle:])
            else:
                failures.append({"symbol": chunk[0], "error": str(exc)})
            return
        by_code = {
            str(item.get("f12")): item
            for item in payload["data"].get("diff", [])
        }
        for symbol in chunk:
            item = by_code.get(symbol.split(".")[0])
            if item is None:
                missing.append(symbol)
                continue
            rows.append({
                "symbol": symbol,
                "name": item.get("f14"),
                "last": item.get("f2"),
                "pct_change": item.get("f3"),
                "volume": item.get("f5"),
                "amount": item.get("f6"),
                "high": item.get("f15"),
                "low": item.get("f16"),
                "open": item.get("f17"),
                "pre_close": item.get("f18"),
                "market_timestamp": item.get("f124"),
            })

    for start in range(0, len(symbols), batch_size):
        fetch_chunk(symbols[start:start + batch_size])
        if start + batch_size < len(symbols):
            time.sleep(delay_seconds)
    return rows, missing, failures


def fetch_sina_snapshot_for_symbols(
    symbols: list[str], *, batch_size: int = 50, delay_seconds: float = 0.15
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, str]]]:
    """读取新浪收盘快照；其成交量单位为股，转换为内部快照的手。"""
    if not 1 <= batch_size <= 100:
        raise ValueError("batch_size 必须在 1 到 100 之间")
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    failures: list[dict[str, str]] = []

    for start in range(0, len(symbols), batch_size):
        chunk = symbols[start:start + batch_size]
        codes = {
            ("sh" if symbol.endswith(".SH") else "sz") + symbol[:6]: symbol
            for symbol in chunk
        }
        request = Request(
            SINA_QUOTE_URL + ",".join(codes),
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://finance.sina.com.cn/",
            },
        )
        try:
            with urlopen(request, timeout=15) as response:
                # 数值、代码和日期字段均为 ASCII；latin-1 可无损跳过名称乱码。
                text = response.read().decode("latin-1")
        except Exception as exc:
            failures.extend({"symbol": symbol, "error": str(exc)} for symbol in chunk)
            continue

        seen: set[str] = set()
        for line in text.splitlines():
            if "hq_str_" not in line or '="' not in line:
                continue
            provider_code = line.split("hq_str_", 1)[1].split("=", 1)[0]
            symbol = codes.get(provider_code)
            if symbol is None:
                continue
            values = line.split('="', 1)[1].rsplit('"', 1)[0].split(",")
            if len(values) < 32 or not values[30]:
                missing.append(symbol)
                continue
            try:
                observed = datetime.fromisoformat(
                    f"{values[30]}T{values[31]}"
                ).replace(tzinfo=CHINA_TZ)
                volume_shares = float(values[8] or 0)
                pre_close = float(values[2] or 0)
                last = float(values[3] or 0)
                rows.append({
                    "symbol": symbol,
                    "name": values[0],
                    "last": last if last > 0 else None,
                    "pct_change": None,
                    "volume": volume_shares / 100.0,
                    "amount": float(values[9] or 0),
                    "high": float(values[4]) if float(values[4] or 0) > 0 else None,
                    "low": float(values[5]) if float(values[5] or 0) > 0 else None,
                    "open": float(values[1]) if float(values[1] or 0) > 0 else None,
                    "pre_close": pre_close if pre_close > 0 else None,
                    "market_timestamp": int(observed.timestamp()),
                })
                seen.add(symbol)
            except (TypeError, ValueError) as exc:
                failures.append({"symbol": symbol, "error": str(exc)})
        missing.extend(symbol for symbol in chunk if symbol not in seen and symbol not in missing)
        if start + batch_size < len(symbols):
            time.sleep(delay_seconds)

    return rows, sorted(set(missing)), failures


def _number(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return number


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    frame.to_csv(temporary, index=False)
    os.replace(temporary, path)


def _atomic_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, path)


def completed_target_date(
    now: datetime, benchmark_rows: list[dict[str, Any]]
) -> pd.Timestamp:
    dates = pd.Series([row["trade_date"] for row in benchmark_rows])
    dates = pd.to_datetime(dates).dt.normalize()
    today = pd.Timestamp(now.astimezone(CHINA_TZ).date())
    if now.astimezone(CHINA_TZ).time() < clock_time(15, 10):
        dates = dates[dates < today]
    else:
        dates = dates[dates <= today]
    if dates.empty:
        raise IncrementalUpdateError("中证500没有可用的已完成交易日")
    return dates.max()


def next_unwritten_target_date(
    now: datetime,
    benchmark_rows: list[dict[str, Any]],
    benchmark_path: Path,
) -> pd.Timestamp:
    """有多个缺口时只补最早一天，禁止直接跳到最新交易日。"""
    latest = completed_target_date(now, benchmark_rows)
    existing = pd.read_csv(benchmark_path, usecols=["date"])
    existing_dates = pd.to_datetime(existing["date"]).dt.normalize()
    if existing_dates.empty:
        raise IncrementalUpdateError("本地中证500底库为空")
    local_last = existing_dates.max()
    available = sorted({
        pd.Timestamp(row["trade_date"]).normalize()
        for row in benchmark_rows
        if local_last < pd.Timestamp(row["trade_date"]).normalize() <= latest
    })
    return available[0] if available else latest


def build_incremental_rows(
    snapshot: list[dict[str, Any]],
    target: pd.Timestamp,
    metadata: dict[str, dict[str, Any]],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """把收盘快照转换为与 SuperMind 底库一致的一日日线。"""
    target = pd.Timestamp(target).normalize()
    rows: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    stale_traded: list[str] = []
    metadata_missing: list[str] = []

    for item in snapshot:
        symbol = str(item.get("symbol") or "")
        volume_lots = _number(item.get("volume"))
        amount = _number(item.get("amount"))
        close = _number(item.get("last"))
        pre_close = _number(item.get("pre_close"))
        timestamp = item.get("market_timestamp")
        observed = None
        if isinstance(timestamp, (int, float)) and timestamp > 0:
            observed = datetime.fromtimestamp(timestamp, CHINA_TZ)

        paused = bool(volume_lots is not None and volume_lots <= 0)
        if volume_lots is None:
            rejected.append({"symbol": symbol, "reason": "missing_volume"})
            continue
        if not paused and (observed is None or pd.Timestamp(observed.date()) != target):
            stale_traded.append(symbol)
            continue
        if close is None:
            close = pre_close if paused else None
        if close is None or amount is None:
            rejected.append({"symbol": symbol, "reason": "missing_price_or_amount"})
            continue

        open_price = _number(item.get("open"))
        high = _number(item.get("high"))
        low = _number(item.get("low"))
        if paused:
            open_price = close if open_price is None else open_price
            high = close if high is None else high
            low = close if low is None else low
        if any(value is None for value in (open_price, high, low)):
            rejected.append({"symbol": symbol, "reason": "missing_ohlc"})
            continue

        security = metadata.get(symbol)
        if security is None:
            metadata_missing.append(symbol)
            listing_days = 1  # 保守处理：新代码不会误过上市天数过滤。
        else:
            listed = pd.Timestamp(security["listed_date"]).normalize()
            listing_days = max((target - listed).days, 0)

        rows.append({
            "date": target,
            "symbol": symbol,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            # 东方财富 f5/kline 成交量单位为手；SuperMind 底库单位为股。
            "volume": volume_lots * 100.0,
            "amount": amount,
            "paused": paused,
            "st": "ST" in str(item.get("name") or "").upper(),
            "listing_days": listing_days,
        })

    frame = pd.DataFrame(rows, columns=DAILY_COLUMNS)
    duplicates = int(frame.duplicated(["date", "symbol"]).sum())
    if duplicates:
        raise IncrementalUpdateError(f"当日快照包含 {duplicates} 个重复代码")
    quality = {
        "snapshot_symbols": len(snapshot),
        "accepted_symbols": len(frame),
        "rejected": rejected,
        "stale_traded_symbols": stale_traded,
        "metadata_missing_symbols": metadata_missing,
        "paused_symbols": int(frame["paused"].sum()) if not frame.empty else 0,
    }
    return frame.sort_values("symbol").reset_index(drop=True), quality


def _canonical_day(frame: pd.DataFrame) -> str:
    columns = DAILY_COLUMNS
    normalized = frame[columns].copy().sort_values("symbol").reset_index(drop=True)
    normalized["date"] = pd.to_datetime(normalized["date"]).dt.strftime("%Y-%m-%d")
    for column in ["open", "high", "low", "close", "volume", "amount"]:
        normalized[column] = pd.to_numeric(normalized[column], errors="raise").round(6)
    for column in ["paused", "st"]:
        normalized[column] = normalized[column].astype(str).str.lower().isin(
            {"1", "true", "yes", "y"}
        )
    normalized["listing_days"] = pd.to_numeric(
        normalized["listing_days"], errors="raise"
    ).astype("int64")
    return normalized.to_csv(index=False, lineterminator="\n")


def append_daily(
    path: Path, incoming: pd.DataFrame, target: pd.Timestamp
) -> tuple[str, pd.DataFrame]:
    if not path.exists():
        raise IncrementalUpdateError(
            f"历史底库不存在：{path}；必须先完成一次 SuperMind 全量建库"
        )
    existing = pd.read_csv(path)
    missing_columns = set(DAILY_COLUMNS) - set(existing.columns)
    if missing_columns:
        raise IncrementalUpdateError(f"历史底库缺少字段：{sorted(missing_columns)}")
    existing["date"] = pd.to_datetime(existing["date"]).dt.normalize()
    target = pd.Timestamp(target).normalize()
    same_day = existing.loc[existing["date"] == target, DAILY_COLUMNS]
    if not same_day.empty:
        if _canonical_day(same_day) == _canonical_day(incoming):
            return "already_current", existing
        raise IncrementalUpdateError(
            f"{target.date()} 已有数据与新快照冲突，拒绝静默覆盖"
        )
    if not existing.empty and target <= existing["date"].max():
        raise IncrementalUpdateError("目标日期早于底库末日，拒绝乱序追加")
    combined = pd.concat([existing[DAILY_COLUMNS], incoming], ignore_index=True)
    combined = combined.sort_values(["date", "symbol"]).reset_index(drop=True)
    return "append", combined


def append_benchmark(
    path: Path, benchmark_rows: list[dict[str, Any]], target: pd.Timestamp
) -> tuple[str, pd.DataFrame]:
    if not path.exists():
        raise IncrementalUpdateError(f"基准底库不存在：{path}")
    target = pd.Timestamp(target).normalize()
    match = [row for row in benchmark_rows if pd.Timestamp(row["trade_date"]) == target]
    if len(match) != 1:
        raise IncrementalUpdateError(f"中证500目标日记录数量异常：{len(match)}")
    incoming_close = float(match[0]["close"])
    existing = pd.read_csv(path)
    existing["date"] = pd.to_datetime(existing["date"]).dt.normalize()
    same_day = existing.loc[existing["date"] == target]
    if not same_day.empty:
        if len(same_day) == 1 and abs(float(same_day.iloc[0]["close"]) - incoming_close) < 1e-8:
            return "already_current", existing
        raise IncrementalUpdateError(f"{target.date()} 中证500数据冲突")
    if not existing.empty and target <= existing["date"].max():
        raise IncrementalUpdateError("中证500目标日期早于底库末日")
    combined = pd.concat([
        existing[["date", "close"]],
        pd.DataFrame([{"date": target, "close": incoming_close}]),
    ], ignore_index=True).sort_values("date").reset_index(drop=True)
    return "append", combined


def run_update(
    daily_path: Path,
    benchmark_path: Path,
    universe_root: Path,
    manifest_root: Path,
    *,
    now: datetime | None = None,
    minimum_coverage: float = 0.995,
    config_path: Path | None = None,
) -> dict[str, Any]:
    started = datetime.now(CHINA_TZ)
    current = (now or started).astimezone(CHINA_TZ)
    if not daily_path.exists():
        raise IncrementalUpdateError(
            f"历史底库不存在：{daily_path}；必须先完成一次 SuperMind 全量建库"
        )
    if not benchmark_path.exists():
        raise IncrementalUpdateError(f"基准底库不存在：{benchmark_path}")
    benchmark_rows = benchmark_rows_for_update(universe_root, current, limit=10)
    benchmark_provider = str(benchmark_rows[-1].get("provider") or "unknown")
    target = next_unwritten_target_date(current, benchmark_rows, benchmark_path)
    _, metadata = load_universe(universe_root)
    cfg = load_config(config_path or ROOT / "config" / "s1_config.json")
    requested_symbols = account_tradable_symbols(metadata, cfg)
    today = pd.Timestamp(current.date())

    # 当天已经通过门槛并写入正式库时，重复运行只核验日期和哈希，不再次
    # 请求全市场。公开源限速不应把已验收的健康底库误报为失败。
    existing_manifest_path = manifest_root / f"{target.strftime('%Y-%m-%d')}.json"
    if existing_manifest_path.exists():
        previous = json.loads(existing_manifest_path.read_text(encoding="utf-8"))
        daily_dates = pd.read_csv(daily_path, usecols=["date"])
        benchmark_dates = pd.read_csv(benchmark_path, usecols=["date"])
        daily_last = pd.to_datetime(daily_dates["date"]).max().normalize()
        benchmark_last = pd.to_datetime(benchmark_dates["date"]).max().normalize()
        hashes_match = (
            previous.get("daily_sha256_after") == _sha256(daily_path)
            and previous.get("benchmark_sha256_after") == _sha256(benchmark_path)
        )
        coverage_ok = float(previous.get("coverage", 0.0)) >= minimum_coverage
        if daily_last == target == benchmark_last and hashes_match and coverage_ok:
            result = dict(previous)
            result.update({
                "generated_at": datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
                "status": "ALREADY_CURRENT",
                "daily_action": "already_current",
                "benchmark_action": "already_current",
                "elapsed_seconds": round(
                    (datetime.now(CHINA_TZ) - started).total_seconds(), 3
                ),
            })
            return result

    if target < today:
        incoming, detail = fetch_historical_target_rows(
            requested_symbols,
            target,
            metadata,
            cache_path=manifest_root.parent / "daily_catchup" / f"{target.strftime('%Y-%m-%d')}.csv",
        )
    else:
        snapshot, quote_missing, quote_failures = fetch_sina_snapshot_for_symbols(
            requested_symbols
        )
        # 新浪偶发缺码时只对缺口使用东方财富，避免接口故障触发全池递归重试。
        fallback_symbols = sorted(set(quote_missing) | {
            str(item["symbol"]) for item in quote_failures
        })
        if fallback_symbols:
            fallback_rows, fallback_missing, fallback_failures = (
                fetch_snapshot_for_symbols(fallback_symbols)
            )
            snapshot.extend(fallback_rows)
            quote_missing = fallback_missing
            quote_failures.extend(fallback_failures)
        incoming, detail = build_incremental_rows(snapshot, target, metadata)
        detail["mode"] = "closing_snapshot_sina_with_eastmoney_fallback"
        detail["requested_symbols"] = len(requested_symbols)
        detail["quote_missing_symbols"] = quote_missing
        detail["quote_failures"] = quote_failures
        # 已核验的AKShare入口只承担当天小缺口，避免接口故障触发数千次请求。
        absent = sorted(set(requested_symbols) - set(incoming['symbol']))
        if absent:
            from akshare_daily_bridge import fetch_missing
            extra, ak_detail = fetch_missing(absent, target, metadata, manifest_root.parent / 'akshare_closing_fallback')
            detail['akshare_fallback'] = ak_detail
            if not extra.empty:
                incoming = pd.concat([incoming, extra[DAILY_COLUMNS]], ignore_index=True)
                detail['quote_missing_symbols'] = sorted(set(detail['quote_missing_symbols']) - set(extra['symbol']))
    coverage = len(incoming) / len(requested_symbols) if requested_symbols else 0.0
    if coverage < minimum_coverage:
        raise IncrementalUpdateError(
            f"当日有效覆盖率 {coverage:.2%} 低于门槛 {minimum_coverage:.2%}"
        )

    daily_action, combined_daily = append_daily(daily_path, incoming, target)
    benchmark_action, combined_benchmark = append_benchmark(
        benchmark_path, benchmark_rows, target
    )
    if {daily_action, benchmark_action} == {"append", "already_current"}:
        raise IncrementalUpdateError("日线与基准更新状态不一致，拒绝部分写入")

    before_daily = _sha256(daily_path)
    before_benchmark = _sha256(benchmark_path)
    if daily_action == "append":
        _atomic_csv(combined_daily, daily_path)
        _atomic_csv(combined_benchmark, benchmark_path)

    result = {
        "schema_version": 1,
        "source": "public_eod_incremental",
        "benchmark_provider": benchmark_provider,
        "read_only_market_data": True,
        "generated_at": datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
        "target_date": target.strftime("%Y-%m-%d"),
        "status": "UPDATED" if daily_action == "append" else "ALREADY_CURRENT",
        "daily_action": daily_action,
        "benchmark_action": benchmark_action,
        "minimum_coverage": minimum_coverage,
        "coverage": round(coverage, 6),
        "quality": detail,
        "daily_sha256_before": before_daily,
        "daily_sha256_after": _sha256(daily_path),
        "benchmark_sha256_before": before_benchmark,
        "benchmark_sha256_after": _sha256(benchmark_path),
        "elapsed_seconds": round((datetime.now(CHINA_TZ) - started).total_seconds(), 3),
        "limitations": [
            "东方财富公开接口不是带服务承诺的正式行情源",
            "当前名称用于 ST 状态，仅适合当日研究扫描",
            "股票代码池来自最近一次已验收元数据，新上市代码需周期性刷新股票池",
            "创业板、科创板和北交所按账户权限硬排除，不参与增量覆盖率或候选排名",
            "程序不会自动下单、撤单或读取资金账户",
        ],
    }
    _atomic_json(result, manifest_root / f"{target.strftime('%Y-%m-%d')}.json")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="全 A 收盘日线增量更新（只读行情）")
    parser.add_argument("--daily", default=str(ROOT / "runtime" / "s1_daily.csv"))
    parser.add_argument(
        "--benchmark", default=str(ROOT / "runtime" / "s1_benchmark.csv")
    )
    parser.add_argument("--universe-root", default=str(ROOT / "runtime"))
    parser.add_argument(
        "--manifest-root", default=str(ROOT / "runtime" / "daily_updates")
    )
    parser.add_argument("--minimum-coverage", type=float, default=0.995)
    args = parser.parse_args()
    if not 0.95 <= args.minimum_coverage <= 1.0:
        raise ValueError("minimum-coverage 必须在 0.95 到 1.0 之间")
    try:
        result = run_update(
            Path(args.daily),
            Path(args.benchmark),
            Path(args.universe_root),
            Path(args.manifest_root),
            minimum_coverage=args.minimum_coverage,
        )
    except Exception as exc:
        failure = {
            "schema_version": 1,
            "source": "eastmoney_public_eod_incremental",
            "read_only_market_data": True,
            "generated_at": datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
            "status": "FAILED_CLOSED",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        print(json.dumps(failure, ensure_ascii=False, indent=2))
        raise SystemExit(2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
