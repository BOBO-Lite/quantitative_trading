"""把 SuperMind 分片转换成冻结 S1 引擎可直接读取的 CSV。"""

from __future__ import annotations

import argparse
import gzip
import json
import re
from pathlib import Path

import pandas as pd


SYMBOL_RE = re.compile(r"^\d{6}\.(?:SH|SZ|BJ)$")
EXPECTED_TOTAL_BATCHES = 1161
MIN_BASELINE_DAILY_SYMBOLS = 5801
DAILY_COLUMNS = [
    "date", "symbol", "open", "high", "low", "close",
    "volume", "amount", "paused", "st", "listing_days",
]


def _bundle_paths(runtime: Path) -> list[Path]:
    plain = sorted(runtime.glob("supermind_daily_bundle_[0-9][0-9].json"))
    compressed = sorted(runtime.glob("supermind_daily_bundle_gz_*.json.gz"))
    return plain + compressed


def _missing_ranges(numbers: list[int]) -> list[str]:
    if not numbers:
        return []
    ranges: list[str] = []
    start = previous = numbers[0]
    for number in numbers[1:]:
        if number != previous + 1:
            ranges.append(str(start) if start == previous else f"{start}-{previous}")
            start = number
        previous = number
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ranges


def _required_bundle_names(missing_batches: list[int]) -> list[str]:
    """按当前导出方案把缺失批次映射为待下载的大分片名。"""
    names: set[str] = set()
    for batch in missing_batches:
        if batch < 300:
            names.add(f"supermind_daily_bundle_{batch // 100:02d}.json")
        else:
            names.add(f"supermind_daily_bundle_gz_{batch // 50:02d}.json.gz")
    return sorted(names)


def inspect_daily_bundle_coverage(
    runtime: Path,
    *,
    expected_total_batches: int = EXPECTED_TOTAL_BATCHES,
    expected_symbol_count: int | None = None,
) -> dict:
    """只读检查正式底库分片是否完整，不加载验收用的零散 part 文件。"""
    expected_count_was_explicit = expected_symbol_count is not None
    universe_symbols: set[str] | None = None
    universe_path = runtime / "supermind_universe_current.json.gz"
    if not universe_path.exists():
        universe_path = runtime / "supermind_universe.json"
    if universe_path.exists():
        universe = _read_json(universe_path)
        securities = universe.get("securities", [])
        universe_symbols = {str(row.get("symbol")) for row in securities}
        declared = universe.get("symbol_count")
        if declared != len(securities) or len(universe_symbols) != len(securities):
            raise ValueError("股票池声明数量、实际数量或唯一代码不一致")
        if expected_symbol_count is None:
            expected_symbol_count = len(universe_symbols)
    if expected_symbol_count is None:
        expected_symbol_count = MIN_BASELINE_DAILY_SYMBOLS
    paths = _bundle_paths(runtime)
    batch_counts: dict[int, int] = {}
    symbol_counts: dict[str, int] = {}
    missing_symbol_references: list[dict] = []
    range_mismatches: list[dict] = []

    for path in paths:
        bundle = _read_json(path)
        if bundle.get("format") != "supermind_daily_bundle":
            raise ValueError(f"不是 SuperMind 日线大分片: {path.name}")
        parts = bundle.get("parts", [])
        actual_batches = [int(part["batch_number"]) for part in parts]
        start = int(bundle.get("start_batch", -1))
        end = int(bundle.get("end_batch_exclusive", -1))
        expected_in_file = list(range(start, end))
        if actual_batches != expected_in_file:
            range_mismatches.append({
                "file": path.name,
                "declared": [start, end],
                "actual": actual_batches,
            })
        for part in parts:
            batch = int(part["batch_number"])
            batch_counts[batch] = batch_counts.get(batch, 0) + 1
            missing = list(part.get("missing_symbols", []))
            if missing:
                missing_symbol_references.append({"batch": batch, "symbols": missing})
            for symbol in part.get("symbols", []):
                symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1

    expected_batches = set(range(expected_total_batches))
    seen_batches = set(batch_counts)
    missing_batches = sorted(expected_batches - seen_batches)
    unexpected_batches = sorted(seen_batches - expected_batches)
    duplicate_batches = sorted(batch for batch, count in batch_counts.items() if count > 1)
    duplicate_symbols = sorted(symbol for symbol, count in symbol_counts.items() if count > 1)
    bundle_symbols = set(symbol_counts)
    missing_bundle_symbols = (
        sorted(universe_symbols - bundle_symbols) if universe_symbols is not None else []
    )
    unexpected_bundle_symbols = (
        sorted(bundle_symbols - universe_symbols) if universe_symbols is not None else []
    )
    complete = (
        bool(paths)
        and not missing_batches
        and not unexpected_batches
        and not duplicate_batches
        and not duplicate_symbols
        and not missing_symbol_references
        and not range_mismatches
        and not missing_bundle_symbols
        and not unexpected_bundle_symbols
        and len(symbol_counts) == expected_symbol_count
        and (expected_count_was_explicit or expected_symbol_count >= MIN_BASELINE_DAILY_SYMBOLS)
    )
    return {
        "status": "COMPLETE" if complete else "INCOMPLETE",
        "expected_total_batches": expected_total_batches,
        "seen_batch_count": len(seen_batches),
        "seen_batch_min": min(seen_batches) if seen_batches else None,
        "seen_batch_max": max(seen_batches) if seen_batches else None,
        "missing_batches": missing_batches,
        "missing_batch_ranges": _missing_ranges(missing_batches),
        "unexpected_batches": unexpected_batches,
        "duplicate_batches": duplicate_batches,
        "expected_symbol_count": expected_symbol_count,
        "symbol_count": len(symbol_counts),
        "duplicate_symbol_count": len(duplicate_symbols),
        "duplicate_symbols": duplicate_symbols,
        "missing_symbol_references": missing_symbol_references,
        "missing_bundle_symbols": missing_bundle_symbols,
        "unexpected_bundle_symbols": unexpected_bundle_symbols,
        "range_mismatches": range_mismatches,
        "source_files": [path.name for path in paths],
        "required_bundle_files": _required_bundle_names(missing_batches),
    }


def require_complete_daily_bundle(runtime: Path) -> dict:
    coverage = inspect_daily_bundle_coverage(runtime)
    if coverage["status"] != "COMPLETE":
        ranges = ", ".join(coverage["missing_batch_ranges"]) or "无"
        raise ValueError(
            "SuperMind 全量底库未通过门槛："
            f"批次 {coverage['seen_batch_count']}/{coverage['expected_total_batches']}，"
            f"行情代码 {coverage['symbol_count']}/{coverage['expected_symbol_count']}，"
            f"缺失批次 {ranges}，重复批次 {coverage['duplicate_batches']}"
        )
    return coverage


def _read_json(path: Path) -> dict:
    if path.name.endswith(".json.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


def load_universe(runtime: Path) -> tuple[dict, dict[str, dict]]:
    current_path = runtime / "supermind_universe_current.json.gz"
    universe_path = (
        current_path if current_path.exists()
        else runtime / "supermind_universe.json"
    )
    payload = _read_json(universe_path)
    securities = payload.get("securities", [])
    if payload.get("symbol_count") != len(securities):
        raise ValueError("股票池数量与 securities 长度不一致")
    metadata = {row["symbol"]: row for row in securities}
    if len(metadata) != len(securities):
        raise ValueError("股票池包含重复代码")
    return payload, metadata


def load_daily_parts(
    runtime: Path,
    *,
    as_of: pd.Timestamp | None = None,
) -> pd.DataFrame:
    _, metadata = load_universe(runtime)
    all_bundle_paths = _bundle_paths(runtime)
    part_paths = sorted(runtime.glob("supermind_daily_part_*.json"))
    if not all_bundle_paths and not part_paths:
        raise FileNotFoundError("没有找到 SuperMind 日线分片")

    # 大分片是受限研究环境的下载传输格式；存在时优先使用，避免与
    # 同目录中保留的少量验收分片（通常为 0000、0001）重复计数。
    payloads: list[tuple[str, dict]] = []
    if all_bundle_paths:
        seen_batch_ranges: set[tuple[int, int]] = set()
        for path in all_bundle_paths:
            bundle = _read_json(path)
            if bundle.get("format") != "supermind_daily_bundle":
                raise ValueError(f"不是 SuperMind 日线大分片: {path.name}")
            batch_range = (
                int(bundle.get("start_batch", -1)),
                int(bundle.get("end_batch_exclusive", -1)),
            )
            if batch_range in seen_batch_ranges:
                raise ValueError(f"重复大分片批次范围: {batch_range}")
            seen_batch_ranges.add(batch_range)
            for payload in bundle.get("parts", []):
                payloads.append((path.name, payload))
    else:
        payloads = [(path.name, _read_json(path)) for path in part_paths]

    seen_batches: set[int] = set()
    rows: list[dict] = []
    for source_name, payload in payloads:
        batch_number = int(payload["batch_number"])
        if batch_number in seen_batches:
            raise ValueError(f"重复批次: {batch_number} ({source_name})")
        seen_batches.add(batch_number)
        if payload.get("missing_symbols"):
            raise ValueError(f"批次 {batch_number} 有缺失股票")
        for symbol in payload["symbols"]:
            if not SYMBOL_RE.fullmatch(symbol):
                raise ValueError(f"非法股票代码: {symbol}")
            if symbol not in metadata:
                raise ValueError(f"股票池中不存在: {symbol}")
            bars = payload["daily_bars"].get(symbol, [])
            if payload["row_counts"].get(symbol) != len(bars):
                raise ValueError(f"股票 {symbol} 行数不一致")
            security = metadata[symbol]
            listed_date = pd.Timestamp(security["listed_date"])
            name = str(security.get("name", "")).upper()
            is_st = "ST" in name
            for bar in bars:
                date = pd.Timestamp(bar["date"])
                volume = bar.get("volume")
                rows.append({
                    "date": date,
                    "symbol": symbol,
                    "open": bar.get("open"),
                    "high": bar.get("high"),
                    "low": bar.get("low"),
                    "close": bar.get("close"),
                    "volume": volume,
                    "amount": bar.get("turnover"),
                    "paused": pd.isna(volume) or float(volume) <= 0,
                    "st": is_st,
                    "listing_days": max((date - listed_date).days, 0),
                })

    daily = pd.DataFrame(rows, columns=DAILY_COLUMNS)
    if as_of is not None:
        cutoff = pd.Timestamp(as_of).normalize()
        daily = daily.loc[daily["date"] <= cutoff].copy()
    if daily.duplicated(["date", "symbol"]).any():
        raise ValueError("日线分片包含重复 date/symbol")
    return daily.sort_values(["date", "symbol"]).reset_index(drop=True)


def load_benchmark(runtime: Path) -> pd.DataFrame:
    payload = _read_json(runtime / "supermind_benchmark.json")
    rows = payload.get("daily_bars", [])
    if payload.get("symbol") != "000905.SH":
        raise ValueError("基准不是冻结配置要求的中证500")
    if payload.get("row_count") != len(rows):
        raise ValueError("基准行数不一致")
    benchmark = pd.DataFrame(rows)
    required = {"date", "close"}
    if not required.issubset(benchmark.columns):
        raise ValueError("基准缺少 date/close")
    benchmark["date"] = pd.to_datetime(benchmark["date"])
    return benchmark.sort_values("date").reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="准备 SuperMind S1 研究扫描输入")
    parser.add_argument("--runtime", default="runtime")
    parser.add_argument("--daily-output", default="runtime/s1_daily.csv")
    parser.add_argument("--benchmark-output", default="runtime/s1_benchmark.csv")
    args = parser.parse_args()
    runtime = Path(args.runtime)
    # 正式输出只能来自完整、唯一且无缺失标的的 0—1160 批底库。
    require_complete_daily_bundle(runtime)
    benchmark = load_benchmark(runtime)
    daily = load_daily_parts(runtime, as_of=benchmark["date"].max())
    Path(args.daily_output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.benchmark_output).parent.mkdir(parents=True, exist_ok=True)
    daily.to_csv(args.daily_output, index=False)
    benchmark.to_csv(args.benchmark_output, index=False)
    print(f"日线 {len(daily)} 行，股票 {daily['symbol'].nunique()} 只")
    print(f"中证500 {len(benchmark)} 行")


if __name__ == "__main__":
    main()
