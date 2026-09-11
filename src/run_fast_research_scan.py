"""用腾讯公开日K快速补目标日，仅生成隔离的研究候选，不写正式底库。"""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd

from generate_candidates import generate_research_outputs
from prepare_supermind_scan_data import DAILY_COLUMNS, load_universe
from s1_engine import load_config
from update_daily_incremental import (
    CHINA_TZ,
    _atomic_csv,
    _tencent_benchmark,
    account_tradable_symbols,
    next_unwritten_target_date,
)


ROOT = Path(__file__).resolve().parents[1]


def _tencent_history(symbol: str, limit: int = 5) -> list[list[str]]:
    code, exchange = symbol.split(".")
    key = ("sh" if exchange == "SH" else "sz") + code
    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/kline/kline?"
        f"param={key},day,,,{limit}"
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"})
            with urlopen(request, timeout=12) as response:
                payload = json.loads(response.read().decode("utf-8"))
            block = payload.get("data", {}).get(key, {})
            return block.get("day") or []
        except Exception as exc:
            last_error = exc
            time.sleep(0.3 * (attempt + 1))
    assert last_error is not None
    raise last_error


def main() -> None:
    runtime = ROOT / "runtime"
    config_path = ROOT / "config" / "s1_config.json"
    daily_path = runtime / "s1_daily.csv"
    benchmark_path = runtime / "s1_benchmark.csv"
    cfg = load_config(config_path)
    _, metadata = load_universe(runtime)
    symbols = account_tradable_symbols(metadata, cfg)
    benchmark_rows = _tencent_benchmark(10)
    # 快速研究链可以顺序使用前一日的隔离输入，但永不回写正式底库。
    chained = []
    for directory in sorted((runtime / "fast_research").glob("????-??-??")):
        candidate_daily = directory / "daily_for_scan.csv"
        candidate_benchmark = directory / "benchmark_for_scan.csv"
        if candidate_daily.exists() and candidate_benchmark.exists():
            chained.append((directory.name, candidate_daily, candidate_benchmark))
    if chained:
        _, daily_path, benchmark_path = chained[-1]
    target = next_unwritten_target_date(
        datetime.now(CHINA_TZ), benchmark_rows, benchmark_path
    )
    input_dir = runtime / "fast_research" / target.strftime("%Y-%m-%d")
    input_dir.mkdir(parents=True, exist_ok=True)

    rows: dict[str, dict] = {}
    exact_cache = runtime / "daily_catchup" / f"{target.strftime('%Y-%m-%d')}.csv"
    exact_count = 0
    if exact_cache.exists():
        cached = pd.read_csv(exact_cache)
        cached["date"] = pd.to_datetime(cached["date"]).dt.normalize()
        for row in cached.loc[cached["date"] == target, DAILY_COLUMNS].to_dict("records"):
            if row["symbol"] in symbols:
                rows[row["symbol"]] = row
        exact_count = len(rows)

    tencent_cache = input_dir / "target_day_rows_cache.csv"
    if tencent_cache.exists():
        cached = pd.read_csv(tencent_cache)
        cached["date"] = pd.to_datetime(cached["date"]).dt.normalize()
        for row in cached.loc[cached["date"] == target, DAILY_COLUMNS].to_dict("records"):
            if row["symbol"] in symbols and row["symbol"] not in rows:
                rows[row["symbol"]] = row

    pending = [symbol for symbol in symbols if symbol not in rows]
    failures: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = {executor.submit(_tencent_history, symbol): symbol for symbol in pending}
        for completed, future in enumerate(as_completed(futures), 1):
            symbol = futures[future]
            try:
                history = future.result()
                dated = [(pd.Timestamp(item[0]).normalize(), item) for item in history]
                matches = [item for date, item in dated if date == target]
                paused = False
                if len(matches) == 1:
                    item = matches[0]
                    open_price, close, high, low = map(float, item[1:5])
                    volume = float(item[5]) * 100.0
                else:
                    prior = [item for date, item in dated if date < target]
                    if not prior:
                        raise ValueError("目标日前无日K")
                    close = float(prior[-1][2])
                    open_price = high = low = close
                    volume = 0.0
                    paused = True
                security = metadata[symbol]
                listed = pd.Timestamp(security["listed_date"]).normalize()
                rows[symbol] = {
                    "date": target,
                    "symbol": symbol,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                    # 目标日信号的20日均成交额使用shift(1)，该占位不会参与本次判定。
                    "amount": 0.0,
                    "paused": paused,
                    "st": "ST" in str(security.get("name") or "").upper(),
                    "listing_days": max((target - listed).days, 0),
                }
                if len(rows) % 100 == 0:
                    _atomic_csv(
                        pd.DataFrame(rows.values(), columns=DAILY_COLUMNS),
                        tencent_cache,
                    )
            except Exception as exc:
                failures.append({"symbol": symbol, "error": str(exc)})
            if completed % 500 == 0:
                print(f"fast research progress: {completed}/{len(pending)}", flush=True)

    increment = pd.DataFrame(rows.values(), columns=DAILY_COLUMNS).sort_values("symbol")
    coverage = len(increment) / len(symbols)
    _atomic_csv(increment, tencent_cache)
    failure_path = input_dir / "fetch_failures.json"
    failure_path.write_text(
        json.dumps({"failures": failures}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if coverage < 0.995:
        raise RuntimeError(f"快速研究覆盖率{coverage:.2%}低于99.5%")

    increment_path = input_dir / "target_day_rows.csv"
    _atomic_csv(increment, increment_path)
    base = pd.read_csv(daily_path)
    base["date"] = pd.to_datetime(base["date"]).dt.normalize()
    combined = pd.concat([base.loc[base["date"] < target, DAILY_COLUMNS], increment], ignore_index=True)
    combined_path = input_dir / "daily_for_scan.csv"
    _atomic_csv(combined, combined_path)

    benchmark = pd.read_csv(benchmark_path)
    benchmark["date"] = pd.to_datetime(benchmark["date"]).dt.normalize()
    match = [row for row in benchmark_rows if pd.Timestamp(row["trade_date"]).normalize() == target]
    if len(match) != 1:
        raise RuntimeError("目标日中证500记录数量异常")
    benchmark = pd.concat([
        benchmark.loc[benchmark["date"] < target, ["date", "close"]],
        pd.DataFrame([{"date": target, "close": float(match[0]["close"])}]),
    ], ignore_index=True)
    combined_benchmark_path = input_dir / "benchmark_for_scan.csv"
    _atomic_csv(benchmark, combined_benchmark_path)

    report_dir = ROOT / "reports" / "fast_research" / target.strftime("%Y-%m-%d")
    manifest = generate_research_outputs(
        combined_path, combined_benchmark_path, config_path, target, report_dir
    )
    supplement = {
        "scan_status": "FAST_CROSS_SOURCE_RESEARCH_COMPLETE",
        "formal_daily_database_modified": False,
        "target_date": target.strftime("%Y-%m-%d"),
        "tradable_symbols": len(symbols),
        "coverage": round(coverage, 6),
        "eastmoney_exact_cached_rows": exact_count,
        "tencent_rows_or_paused_fills": len(increment) - exact_count,
        "failures": failures,
        "candidate_count": manifest["candidate_count"],
        "caveat": "腾讯日K不含成交额；目标日amount置0，但S1目标日流动性使用此前20日shift(1)数据，因此不影响本次信号。该文件不得追加到正式底库。",
    }
    path = report_dir / "fast_source_manifest.json"
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(supplement, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    print(json.dumps(supplement, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
