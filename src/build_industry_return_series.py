"""用前一月末行业映射构造无前视的行业日收益序列（仅预研究）。

行情来自当前仍可交易主板的搜狐回填，因此结果仍有生存者偏差，绝不标记为
正式回测可用。每个交易日只使用严格早于该日的最近月末行业归属。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
CHINA_TZ = timezone(timedelta(hours=8))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_csv_gz(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    frame.to_csv(temporary, index=False, compression="gzip")
    os.replace(temporary, path)


def _atomic_json(payload: dict, path: Path) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def build_mapping(monthly_industry: pd.DataFrame) -> dict[str, tuple[str, str]]:
    required = {"date", "symbol", "industry_code", "industry_name"}
    missing = required - set(monthly_industry.columns)
    if missing:
        raise ValueError(f"行业映射缺少字段={sorted(missing)}")
    rows = monthly_industry.copy()
    rows["month"] = pd.to_datetime(rows["date"], errors="raise").dt.to_period("M").astype(str)
    if rows.duplicated(["month", "symbol"]).any():
        raise ValueError("行业映射存在重复月度股票记录")
    return {
        f"{row.month}|{row.symbol}": (str(row.industry_code), str(row.industry_name))
        for row in rows[["month", "symbol", "industry_code", "industry_name"]].itertuples(index=False)
    }


def run(
    daily_path: Path,
    industry_path: Path,
    output_path: Path,
    chunksize: int = 500_000,
) -> dict:
    mapping_frame = pd.read_csv(industry_path, compression="infer")
    mapping = build_mapping(mapping_frame)
    previous_close: dict[str, float] = {}
    aggregates: list[pd.DataFrame] = []
    total_return_rows = 0
    mapped_return_rows = 0

    for chunk in pd.read_csv(
        daily_path,
        compression="infer",
        usecols=["date", "symbol", "close"],
        chunksize=chunksize,
    ):
        chunk["date"] = pd.to_datetime(chunk["date"], errors="raise")
        chunk["close"] = pd.to_numeric(chunk["close"], errors="raise")
        prior = chunk.groupby("symbol", sort=False)["close"].shift(1)
        first_for_symbol = ~chunk["symbol"].duplicated()
        prior.loc[first_for_symbol] = chunk.loc[first_for_symbol, "symbol"].map(previous_close)
        chunk["return"] = chunk["close"] / prior - 1.0
        last_rows = chunk.groupby("symbol", sort=False).tail(1)
        previous_close.update(zip(last_rows["symbol"], last_rows["close"].astype(float)))

        valid_return = chunk["return"].notna()
        total_return_rows += int(valid_return.sum())
        prior_month = (chunk["date"].dt.to_period("M") - 1).astype(str)
        keys = prior_month + "|" + chunk["symbol"].astype(str)
        mapped = keys.map(mapping)
        chunk["industry_code"] = mapped.map(lambda value: value[0] if isinstance(value, tuple) else None)
        chunk["industry_name"] = mapped.map(lambda value: value[1] if isinstance(value, tuple) else None)
        usable = chunk[valid_return & chunk["industry_code"].notna()].copy()
        mapped_return_rows += len(usable)
        if usable.empty:
            continue
        usable["positive"] = (usable["return"] > 0).astype(int)
        aggregates.append(
            usable.groupby(["date", "industry_code", "industry_name"], as_index=False)
            .agg(return_sum=("return", "sum"), symbol_count=("return", "size"), positive_count=("positive", "sum"))
        )

    if not aggregates:
        raise ValueError("没有可生成的行业收益记录")
    combined = pd.concat(aggregates, ignore_index=True)
    result = combined.groupby(
        ["date", "industry_code", "industry_name"], as_index=False
    )[["return_sum", "symbol_count", "positive_count"]].sum()
    result["equal_weight_return"] = result["return_sum"] / result["symbol_count"]
    result["positive_ratio"] = result["positive_count"] / result["symbol_count"]
    result["date"] = pd.to_datetime(result["date"]).dt.strftime("%Y-%m-%d")
    result = result[[
        "date", "industry_code", "industry_name", "equal_weight_return",
        "symbol_count", "positive_ratio",
    ]].sort_values(["date", "industry_code"])
    duplicate_rows = int(result.duplicated(["date", "industry_code"]).sum())
    mapping_coverage = mapped_return_rows / total_return_rows if total_return_rows else 0.0
    errors = []
    if duplicate_rows:
        errors.append(f"重复行业日记录={duplicate_rows}")
    if mapping_coverage < 0.90:
        errors.append(f"行业映射覆盖率不足90%={mapping_coverage:.4%}")
    _atomic_csv_gz(result, output_path)
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
        "source": "sohu_current_survivor_daily_plus_previous_month_end_industry",
        "daily_path": str(daily_path),
        "daily_sha256": sha256(daily_path),
        "industry_path": str(industry_path),
        "industry_sha256": sha256(industry_path),
        "output_path": str(output_path),
        "output_sha256": sha256(output_path),
        "first_date": result["date"].min(),
        "last_date": result["date"].max(),
        "industry_daily_rows": len(result),
        "mapped_stock_return_rows": mapped_return_rows,
        "total_stock_return_rows": total_return_rows,
        "mapping_coverage": mapping_coverage,
        "errors": errors,
        "pre_research_ready": not errors,
        "formal_backtest_ready": False,
        "limitations": [
            "股票日线只含当前仍可交易主板，存在生存者偏差",
            "行业采用前一月末归属以避免月内未来函数",
            "等权行业收益仅用于S2预研究，不构成实盘启用依据",
        ],
    }
    _atomic_json(report, output_path.parent / "industry_returns_manifest.json")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="构造无前视行业日收益预研究序列")
    parser.add_argument("--daily", default=str(ROOT / "runtime" / "history_backfill" / "history_daily.csv.gz"))
    parser.add_argument("--industry", default=str(ROOT / "runtime" / "industry_history" / "monthly_industry.csv.gz"))
    parser.add_argument("--output", default=str(ROOT / "runtime" / "industry_history" / "industry_daily_returns.csv.gz"))
    parser.add_argument("--chunksize", type=int, default=500_000)
    args = parser.parse_args()
    report = run(Path(args.daily), Path(args.industry), Path(args.output), args.chunksize)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["errors"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
