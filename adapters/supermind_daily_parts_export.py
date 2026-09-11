"""在 SuperMind 研究环境分片导出全 A 股历史日线。

研究环境实测一次请求 5 只股票稳定，20 只可能长时间无响应，因此批次固定为 5。
输出文件由 pandas 写入，不依赖受限的文件系统接口。
"""

from datetime import datetime
from time import perf_counter

import pandas as pd
from mindgo_api import get_all_securities, get_price


BAR_COUNT = 121
BATCH_SIZE = 5
START_BATCH = 0
END_BATCH = 2  # 首次只验收两个批次；验收后改为 None 才跑全量。
FIELDS = ["open", "high", "low", "close", "volume", "turnover"]
BENCHMARK_SYMBOL = "000905.SH"

UNIVERSE_PATH = "supermind_universe.json"
MANIFEST_PATH = "supermind_export_manifest.json"
BENCHMARK_PATH = "supermind_benchmark.json"
PART_PATH_TEMPLATE = "supermind_daily_part_{:04d}.json"


def write_json(payload, path):
    pd.Series(payload, dtype=object).to_json(
        path, force_ascii=False, indent=2
    )


def frame_rows(frame):
    normalized = frame.copy()
    normalized.insert(0, "date", frame.index.strftime("%Y-%m-%d"))
    normalized = normalized.where(pd.notna(normalized), None)
    return normalized.to_dict(orient="records")


def active_stock_universe(as_of):
    securities = get_all_securities()
    stocks = securities.loc[securities["type"].eq("stock")].copy()
    active = stocks.loc[
        stocks["start_date"].le(as_of)
        & stocks["end_date"].ge(as_of)
        & stocks["listed_date"].le(as_of)
        & stocks["de_listed_date"].ge(as_of)
    ].copy()
    active = active.sort_index()
    return active


def security_rows(active):
    rows = []
    for symbol, row in active.iterrows():
        rows.append({
            "symbol": str(symbol),
            "name": row["display_name"],
            "exchange": row["exchange"],
            "listed_date": row["listed_date"].strftime("%Y-%m-%d"),
            "de_listed_date": row["de_listed_date"].strftime("%Y-%m-%d"),
        })
    return rows


def export_daily_parts():
    as_of = pd.Timestamp.today().normalize()
    generated_at = datetime.now().isoformat(timespec="seconds")
    active = active_stock_universe(as_of)
    symbols = active.index.astype(str).tolist()
    total_batches = (len(symbols) + BATCH_SIZE - 1) // BATCH_SIZE
    stop_batch = total_batches if END_BATCH is None else min(END_BATCH, total_batches)

    universe = {
        "schema_version": 1,
        "source": "supermind_get_all_securities",
        "as_of": as_of.strftime("%Y-%m-%d"),
        "symbol_count": len(symbols),
        "batch_size": BATCH_SIZE,
        "total_batches": total_batches,
        "securities": security_rows(active),
    }
    write_json(universe, UNIVERSE_PATH)

    benchmark_result = get_price(
        [BENCHMARK_SYMBOL], None, datetime.now(), "1d", FIELDS,
        skip_paused=False, fq=None, bar_count=BAR_COUNT,
        is_panel=False,
    )
    benchmark_rows = frame_rows(benchmark_result[BENCHMARK_SYMBOL])
    benchmark = {
        "schema_version": 1,
        "source": "supermind_get_price",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": as_of.strftime("%Y-%m-%d"),
        "symbol": BENCHMARK_SYMBOL,
        "fields": FIELDS,
        "bar_count_requested": BAR_COUNT,
        "row_count": len(benchmark_rows),
        "daily_bars": benchmark_rows,
    }
    write_json(benchmark, BENCHMARK_PATH)

    manifest = {
        "schema_version": 1,
        "source": "supermind_get_price",
        "generated_at": generated_at,
        "as_of": as_of.strftime("%Y-%m-%d"),
        "status": "running",
        "batch_size": BATCH_SIZE,
        "bar_count_requested": BAR_COUNT,
        "benchmark_symbol": BENCHMARK_SYMBOL,
        "benchmark_path": BENCHMARK_PATH,
        "total_symbols": len(symbols),
        "total_batches": total_batches,
        "requested_start_batch": START_BATCH,
        "requested_end_batch": stop_batch,
        "completed_batches": [],
        "completed_symbols": 0,
        "last_completed_batch": None,
        "failures": [],
    }
    write_json(manifest, MANIFEST_PATH)

    for batch_number in range(START_BATCH, stop_batch):
        start = batch_number * BATCH_SIZE
        selected = symbols[start:start + BATCH_SIZE]
        started = perf_counter()
        try:
            result = get_price(
                selected, None, datetime.now(), "1d", FIELDS,
                skip_paused=False, fq=None, bar_count=BAR_COUNT,
                is_panel=False,
            )
            daily_bars = {}
            row_counts = {}
            missing_symbols = []
            for symbol in selected:
                if symbol not in result:
                    missing_symbols.append(symbol)
                    row_counts[symbol] = 0
                    daily_bars[symbol] = []
                    continue
                rows = frame_rows(result[symbol])
                daily_bars[symbol] = rows
                row_counts[symbol] = len(rows)

            elapsed = round(perf_counter() - started, 3)
            part = {
                "schema_version": 1,
                "source": "supermind_get_price",
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "as_of": as_of.strftime("%Y-%m-%d"),
                "batch_number": batch_number,
                "symbols": selected,
                "fields": FIELDS,
                "bar_count_requested": BAR_COUNT,
                "elapsed_seconds": elapsed,
                "missing_symbols": missing_symbols,
                "row_counts": row_counts,
                "daily_bars": daily_bars,
            }
            part_path = PART_PATH_TEMPLATE.format(batch_number)
            write_json(part, part_path)
            manifest["completed_batches"].append(batch_number)
            manifest["completed_symbols"] += len(selected)
            manifest["last_completed_batch"] = batch_number
            print("完成批次", batch_number, selected, elapsed, "秒")
        except Exception as exc:
            manifest["failures"].append({
                "batch_number": batch_number,
                "symbols": selected,
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
            print("批次失败", batch_number, selected, type(exc).__name__, str(exc))
        write_json(manifest, MANIFEST_PATH)

    manifest["status"] = "completed" if not manifest["failures"] else "completed_with_failures"
    manifest["finished_at"] = datetime.now().isoformat(timespec="seconds")
    write_json(manifest, MANIFEST_PATH)
    print("本次导出结束", manifest["status"], manifest["completed_batches"])
    return MANIFEST_PATH


export_daily_parts()
