"""用东方财富公开只读接口建立当日全市场研究快照并运行S1扫描。

该脚本不读取账户、不包含交易函数，也不会生成可自动执行的订单。
公开接口仅作为研究与数据管道试运行来源，不能替代正式时点数据验收。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time as clock_time, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "adapters"))

from adapters.eastmoney_readonly import (  # noqa: E402
    EastMoneyError,
    SYMBOL_PATTERN,
    _request_json,
    historical_daily,
)
from s1_engine import load_config, prepare_daily_features  # noqa: E402


CHINA_TZ = timezone(timedelta(hours=8))
UNIVERSE_URL = "https://push2.eastmoney.com/api/qt/clist/get"
UNIVERSE_FILTER = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"


def _symbol(code: str, market: int) -> str:
    if code.startswith(("4", "8", "9")):
        exchange = "BJ"
    else:
        exchange = "SH" if market == 1 else "SZ"
    return f"{code}.{exchange}"


def fetch_universe(page_size: int = 100) -> list[dict[str, Any]]:
    common = {
        "pz": page_size,
        "po": 1,
        "np": 1,
        "fltt": 2,
        "invt": 2,
        "fid": "f12",
        "fs": UNIVERSE_FILTER,
        "fields": "f12,f13,f14,f2,f3,f5,f6,f15,f16,f17,f18,f20,f21,f124",
    }
    def fetch_page(page: int) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(6):
            try:
                return _request_json(UNIVERSE_URL, {**common, "pn": page})["data"]
            except EastMoneyError as exc:
                last_error = exc
                time.sleep(min(8.0, 0.8 * (2**attempt)))
        raise RuntimeError(f"代码池第{page}页读取失败：{last_error}") from last_error

    first = fetch_page(1)
    total = int(first.get("total") or 0)
    pages = max(1, math.ceil(total / page_size))
    rows = list(first.get("diff") or [])
    for page in range(2, pages + 1):
        time.sleep(0.2)
        payload = fetch_page(page)
        rows.extend(payload.get("diff") or [])

    by_symbol: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = str(row.get("f12") or "")
        symbol = _symbol(code, int(row.get("f13") or 0))
        if SYMBOL_PATTERN.fullmatch(symbol):
            by_symbol[symbol] = {
                "symbol": symbol,
                "name": str(row.get("f14") or ""),
                "last": row.get("f2"),
                "pct_change": row.get("f3"),
                "volume": row.get("f5"),
                "amount": row.get("f6"),
                "open": row.get("f17"),
                "high": row.get("f15"),
                "low": row.get("f16"),
                "pre_close": row.get("f18"),
                "market_timestamp": row.get("f124"),
                "total_market_cap": row.get("f20"),
                "float_market_cap": row.get("f21"),
            }
    return sorted(by_symbol.values(), key=lambda row: row["symbol"])


def fetch_histories(
    universe: list[dict[str, Any]], limit: int, workers: int
) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[str]]:
    histories: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    empty: list[str] = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(historical_daily, [row["symbol"]], limit): row["symbol"]
            for row in universe
        }
        completed = 0
        for future in as_completed(futures):
            symbol = futures[future]
            completed += 1
            try:
                rows = future.result()
                if rows:
                    histories.extend(rows)
                else:
                    empty.append(symbol)
            except Exception as exc:  # 保留逐股失败，不让部分数据伪装成完整扫描
                failures.append({"symbol": symbol, "error": str(exc)})
            if completed % 500 == 0:
                print(f"history progress: {completed}/{len(futures)}", flush=True)
    return histories, failures, empty


def completed_signal_date(now: datetime, benchmark_dates: pd.Series) -> pd.Timestamp:
    today = pd.Timestamp(now.date())
    dates = pd.to_datetime(benchmark_dates).dt.normalize()
    if now.time() < clock_time(15, 10):
        dates = dates[dates < today]
    else:
        dates = dates[dates <= today]
    if dates.empty:
        raise RuntimeError("中证500没有可用的已完成交易日")
    return dates.max()


def build_daily_frame(
    histories: list[dict[str, Any]], universe: list[dict[str, Any]], target: pd.Timestamp
) -> pd.DataFrame:
    daily = pd.DataFrame(histories).rename(
        columns={"trade_date": "date", "turnover": "amount"}
    )
    if daily.empty:
        raise RuntimeError("全市场日线为空")
    daily["date"] = pd.to_datetime(daily["date"]).dt.normalize()
    daily = daily[daily["date"] <= target].copy()
    daily = daily.sort_values(["symbol", "date"])
    daily["listing_days"] = daily.groupby("symbol").cumcount() + 1
    daily["paused"] = False
    name_map = {row["symbol"]: row["name"] for row in universe}
    daily["name"] = daily["symbol"].map(name_map).fillna("")
    daily["st"] = daily["name"].str.upper().str.contains("ST", regex=False)
    return daily[
        [
            "date", "symbol", "name", "open", "high", "low", "close",
            "volume", "amount", "paused", "st", "listing_days",
        ]
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="建立全A研究快照并运行S1收盘扫描")
    parser.add_argument("--history-limit", type=int, default=121)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--config", default=str(ROOT / "config" / "s1_config.json"))
    parser.add_argument("--output-root", default=str(ROOT / "runtime" / "eod"))
    args = parser.parse_args()
    if args.history_limit < 121:
        raise ValueError("history-limit至少为121，才能计算S1的60日指标和上市天数")
    if not 1 <= args.workers <= 16:
        raise ValueError("workers必须在1到16之间")

    started = time.time()
    now = datetime.now(CHINA_TZ)
    output_root = Path(args.output_root)
    try:
        universe = fetch_universe()
    except Exception as exc:
        failure_dir = output_root / "failed-runs"
        failure_dir.mkdir(parents=True, exist_ok=True)
        failure = {
            "source": "eastmoney_public_research",
            "generated_at": now.isoformat(timespec="seconds"),
            "scan_status": "DATA_SOURCE_FAIL",
            "formal_candidate_eligible": False,
            "error": str(exc),
        }
        failure_path = failure_dir / f"{now.strftime('%Y%m%dT%H%M%S')}.json"
        failure_path.write_text(
            json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(failure, ensure_ascii=False, indent=2))
        print(f"wrote {failure_path}")
        raise SystemExit(2)
    histories, failures, empty = fetch_histories(
        universe, args.history_limit, args.workers
    )
    benchmark_rows = historical_daily(["000905.SH"], args.history_limit)
    benchmark = pd.DataFrame(benchmark_rows).rename(columns={"trade_date": "date"})
    target = completed_signal_date(now, benchmark["date"])
    benchmark["date"] = pd.to_datetime(benchmark["date"]).dt.normalize()
    benchmark = benchmark[benchmark["date"] <= target][["date", "close"]].copy()
    daily = build_daily_frame(histories, universe, target)

    symbols_with_target = int(daily.loc[daily["date"] == target, "symbol"].nunique())
    universe_count = len(universe)
    target_coverage = symbols_with_target / universe_count if universe_count else 0.0
    request_failure_rate = len(failures) / universe_count if universe_count else 1.0

    output_dir = output_root / target.strftime("%Y-%m-%d")
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(universe).to_csv(output_dir / "universe.csv", index=False)
    daily.to_csv(output_dir / "daily_ohlcv.csv", index=False)
    benchmark.to_csv(output_dir / "benchmark_daily.csv", index=False)
    (output_dir / "failures.json").write_text(
        json.dumps({"failures": failures, "empty": empty}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    quality: dict[str, Any] = {
        "source": "eastmoney_public_research",
        "generated_at": now.isoformat(timespec="seconds"),
        "signal_date": target.strftime("%Y-%m-%d"),
        "universe_count": universe_count,
        "symbols_with_target_bar": symbols_with_target,
        "target_coverage": round(target_coverage, 6),
        "history_request_failures": len(failures),
        "empty_histories": len(empty),
        "elapsed_seconds": round(time.time() - started, 2),
        "formal_candidate_eligible": False,
        "limitations": [
            "公开接口尚未通过长期稳定性与完整时点股票池验收",
            "ST和上市天数依据当前名称及121根行情近似，不适用于历史回测",
            "公告和定期报告日历尚未接入",
        ],
    }

    if request_failure_rate > 0.01 or target_coverage < 0.90:
        quality["scan_status"] = "DATA_QUALITY_FAIL"
        candidates = pd.DataFrame()
    else:
        cfg = load_config(args.config)
        features = prepare_daily_features(daily, benchmark, cfg)
        target_rows = features[features["date"] == target].copy()
        candidates = target_rows[target_rows["signal"]].copy()
        candidate_columns = [
            "date", "symbol", "name", "close", "high", "ma20", "ma60",
            "atr20", "volume_ratio", "excess20_pct", "compression10", "score",
            "structure_low10", "market_gate",
        ]
        candidates = candidates[candidate_columns].sort_values("score", ascending=False)
        quality["scan_status"] = "RESEARCH_SCAN_ONLY"
        quality["eligible_symbols"] = int(target_rows["eligible"].sum())
        quality["candidate_count"] = len(candidates)
        quality["market_gate"] = bool(target_rows["market_gate"].fillna(False).any())

    candidates.to_csv(output_dir / "candidates.csv", index=False)
    (output_dir / "quality.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(quality, ensure_ascii=False, indent=2))
    if not candidates.empty:
        print(candidates.head(20).to_string(index=False))
    print(f"wrote {output_dir}")


if __name__ == "__main__":
    main()
