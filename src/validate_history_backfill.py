"""验收并可选合并搜狐历史日线分片。

该工具只验证文件完整性和行情字段质量；即使全部通过，也不会把存在
生存者偏差的数据标记为正式回测可用。
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
CHINA_TZ = timezone(timedelta(hours=8))
REQUIRED_COLUMNS = [
    "date", "symbol", "open", "high", "low", "close", "volume", "amount"
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_frame(
    frame: pd.DataFrame,
    expected_symbols: set[str],
    start_date: str,
    end_date: str,
) -> dict:
    errors: list[str] = []
    missing_columns = sorted(set(REQUIRED_COLUMNS) - set(frame.columns))
    if missing_columns:
        return {
            "rows": len(frame),
            "errors": [f"缺少字段: {','.join(missing_columns)}"],
        }

    data = frame[REQUIRED_COLUMNS].copy()
    dates = pd.to_datetime(data["date"], errors="coerce")
    numeric_columns = ["open", "high", "low", "close", "volume", "amount"]
    numeric = data[numeric_columns].apply(pd.to_numeric, errors="coerce")
    null_rows = int(data.isna().any(axis=1).sum())
    invalid_date_rows = int(dates.isna().sum())
    invalid_numeric_rows = int(numeric.isna().any(axis=1).sum())
    duplicate_rows = int(data.duplicated(["date", "symbol"]).sum())
    returned_symbols = set(data["symbol"].dropna().astype(str))
    unexpected_symbols = sorted(returned_symbols - expected_symbols)
    missing_symbols = sorted(expected_symbols - returned_symbols)

    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    out_of_range_rows = int(((dates < start) | (dates > end)).fillna(False).sum())
    positive_price_failure = int((numeric[["open", "high", "low", "close"]] <= 0).any(axis=1).sum())
    negative_trade_failure = int((numeric[["volume", "amount"]] < 0).any(axis=1).sum())
    high_relation_failure = int(
        (numeric["high"] < numeric[["open", "low", "close"]].max(axis=1)).sum()
    )
    low_relation_failure = int(
        (numeric["low"] > numeric[["open", "high", "close"]].min(axis=1)).sum()
    )

    counters = {
        "null_rows": null_rows,
        "invalid_date_rows": invalid_date_rows,
        "invalid_numeric_rows": invalid_numeric_rows,
        "duplicate_date_symbol_rows": duplicate_rows,
        "out_of_range_rows": out_of_range_rows,
        "nonpositive_price_rows": positive_price_failure,
        "negative_volume_or_amount_rows": negative_trade_failure,
        "high_relation_failure_rows": high_relation_failure,
        "low_relation_failure_rows": low_relation_failure,
    }
    for name, count in counters.items():
        if count:
            errors.append(f"{name}={count}")
    if unexpected_symbols:
        errors.append(f"出现批次外股票={len(unexpected_symbols)}")

    valid_dates = dates.dropna()
    return {
        "rows": len(data),
        "symbols": len(returned_symbols),
        "missing_symbols": missing_symbols,
        "unexpected_symbols": unexpected_symbols,
        "min_date": valid_dates.min().strftime("%Y-%m-%d") if not valid_dates.empty else None,
        "max_date": valid_dates.max().strftime("%Y-%m-%d") if not valid_dates.empty else None,
        **counters,
        "errors": errors,
    }


def _atomic_json(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def run(input_dir: Path, merge: bool = False) -> dict:
    manifest_path = input_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    completed = {int(item["batch"]): item for item in manifest.get("completed", [])}
    expected_batches = set(range(int(manifest["total_batches"])))
    missing_batches = sorted(expected_batches - set(completed))
    extra_batches = sorted(set(completed) - expected_batches)
    part_results: list[dict] = []
    hash_failures: list[int] = []
    read_failures: list[dict] = []
    all_missing_symbols: set[str] = set()
    total_rows = 0
    total_quality_errors = 0
    merged_path = input_dir / "history_daily.csv.gz"
    temporary_merged = merged_path.with_name(f".{merged_path.name}.tmp")

    if merge and temporary_merged.exists():
        temporary_merged.unlink()

    for batch_number in sorted(completed):
        item = completed[batch_number]
        part_path = Path(item["path"])
        if not part_path.is_absolute():
            candidate = ROOT / part_path
            part_path = candidate if candidate.exists() else input_dir / "parts" / part_path.name
        result = {"batch": batch_number, "path": str(part_path)}
        if not part_path.exists():
            result["errors"] = ["文件不存在"]
            read_failures.append({"batch": batch_number, "error": "文件不存在"})
            part_results.append(result)
            continue
        actual_hash = sha256(part_path)
        result["bytes"] = part_path.stat().st_size
        result["sha256"] = actual_hash
        if actual_hash != item.get("sha256"):
            hash_failures.append(batch_number)
            result["hash_matches_manifest"] = False
        else:
            result["hash_matches_manifest"] = True
        try:
            frame = pd.read_csv(part_path, compression="gzip")
            quality = validate_frame(
                frame,
                set(item.get("symbols", [])),
                manifest["start_date"],
                manifest["end_date"],
            )
            result.update(quality)
            total_rows += int(quality["rows"])
            total_quality_errors += len(quality["errors"])
            all_missing_symbols.update(quality.get("missing_symbols", []))
            if merge:
                with gzip.open(temporary_merged, "at", encoding="utf-8", newline="") as handle:
                    frame[REQUIRED_COLUMNS].to_csv(
                        handle, index=False, header=(batch_number == min(completed))
                    )
        except Exception as exc:
            result["errors"] = [f"读取失败: {type(exc).__name__}: {exc}"]
            read_failures.append({"batch": batch_number, "error": str(exc)})
        part_results.append(result)

    if merge and not (missing_batches or read_failures or hash_failures or total_quality_errors):
        os.replace(temporary_merged, merged_path)
    elif merge and temporary_merged.exists():
        temporary_merged.unlink()

    complete_download = (
        manifest.get("status") == "COMPLETE"
        and not manifest.get("failures")
        and not missing_batches
        and not extra_batches
    )
    data_quality_pass = not (
        hash_failures or read_failures or total_quality_errors or all_missing_symbols
    )
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
        "source_manifest": str(manifest_path),
        "source_status": manifest.get("status"),
        "complete_download": complete_download,
        "data_quality_pass": data_quality_pass,
        "pre_backtest_ready": complete_download and data_quality_pass,
        "formal_backtest_ready": False,
        "total_batches_expected": len(expected_batches),
        "total_batches_present": len(completed),
        "total_rows": total_rows,
        "missing_batches": missing_batches,
        "extra_batches": extra_batches,
        "failed_batches_in_source": manifest.get("failures", []),
        "hash_failure_batches": hash_failures,
        "read_failures": read_failures,
        "missing_symbols": sorted(all_missing_symbols),
        "quality_error_part_count": sum(bool(item.get("errors")) for item in part_results),
        "merged_path": str(merged_path) if merge and merged_path.exists() else None,
        "merged_sha256": sha256(merged_path) if merge and merged_path.exists() else None,
        "limitations": manifest.get("limitations", []),
        "parts": part_results,
    }
    _atomic_json(report, input_dir / "quality_report.json")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="验收并合并历史日线分片")
    parser.add_argument("--input-dir", default=str(ROOT / "runtime" / "history_backfill"))
    parser.add_argument("--merge", action="store_true", help="质量通过后生成合并gzip文件")
    args = parser.parse_args()
    report = run(Path(args.input_dir), merge=args.merge)
    print(json.dumps({key: report[key] for key in [
        "source_status", "complete_download", "data_quality_pass",
        "pre_backtest_ready", "formal_backtest_ready", "total_batches_present",
        "total_batches_expected", "total_rows", "quality_error_part_count",
        "merged_path",
    ]}, ensure_ascii=False, indent=2))
    if not report["pre_backtest_ready"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
