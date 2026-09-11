"""合并并验收从SuperMind下载的历史时点行业与股票池快照。"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
CHINA_TZ = timezone(timedelta(hours=8))
YEAR_FILE_RE = re.compile(
    r"^supermind_industry_history_(\d{4})(\.compact)?\.json(?:\.gz)?$"
)


def read_payload(path: Path) -> dict:
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path}顶层必须是对象")
    return payload


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_gzip(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    frame.to_csv(temporary, index=False, compression="gzip")
    os.replace(temporary, path)


def _atomic_json(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def find_missing_snapshot_months(
    snapshot_dates: list[str],
    expected_start_month: str | None = None,
    expected_end_month: str | None = None,
) -> list[str]:
    """返回指定区间内缺失的自然月份（YYYY-MM）。"""
    if not snapshot_dates:
        if expected_start_month and expected_end_month:
            return [
                str(month) for month in pd.period_range(
                    expected_start_month, expected_end_month, freq="M"
                )
            ]
        return []
    actual_months = {
        pd.Timestamp(value).to_period("M") for value in snapshot_dates
    }
    first_month = (
        pd.Period(expected_start_month, freq="M")
        if expected_start_month else min(actual_months)
    )
    last_month = (
        pd.Period(expected_end_month, freq="M")
        if expected_end_month else max(actual_months)
    )
    expected_months = pd.period_range(
        first_month, last_month, freq="M"
    )
    return [str(month) for month in expected_months if month not in actual_months]


def discover_year_files(raw_dir: Path, start_year: int, end_year: int) -> list[Path]:
    """每年只选一个文件；优先完整版gzip，其次完整版JSON，再选精简版。"""
    candidates: dict[int, list[Path]] = {}
    for path in raw_dir.iterdir() if raw_dir.exists() else []:
        match = YEAR_FILE_RE.match(path.name)
        if match:
            candidates.setdefault(int(match.group(1)), []).append(path)

    selected: list[Path] = []
    missing_years: list[int] = []
    for year in range(start_year, end_year + 1):
        year_candidates = candidates.get(year, [])
        if not year_candidates:
            missing_years.append(year)
            continue

        def priority(path: Path) -> tuple[int, str]:
            compact = ".compact." in path.name
            gzip_file = path.suffix.lower() == ".gz"
            return (int(compact) * 2 + int(not gzip_file), path.name)

        selected.append(sorted(year_candidates, key=priority)[0])
    if missing_years:
        raise FileNotFoundError(
            "缺少年度行业历史文件=" + ",".join(map(str, missing_years))
        )
    return selected


def normalize_payloads(payloads: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    industry_rows: list[dict] = []
    universe_rows: list[dict] = []
    source_failures: list[dict] = []
    for payload in payloads:
        if payload.get("industry_type") != "industryid1":
            raise ValueError("仅接受SuperMind一级行业分类历史导出")
        source_failures.extend(payload.get("failures", []))
        for date, rows in payload.get("snapshots", {}).items():
            for row in rows:
                industry_rows.append({
                    "date": str(date),
                    "symbol": str(row["symbol"]),
                    "industry_code": str(row["industry_code"]),
                    "industry_name": str(row["industry_name"]),
                })
        for date, rows in payload.get("universe_snapshots", {}).items():
            for row in rows:
                universe_rows.append({
                    "date": str(date),
                    "symbol": str(row["symbol"]),
                    "name": str(row.get("name", "")),
                    "listed_date": str(row.get("listed_date", "")),
                    "de_listed_date": str(row.get("de_listed_date", "")),
                    "exchange": str(row.get("exchange", "")),
                })
    industry = pd.DataFrame(industry_rows, columns=[
        "date", "symbol", "industry_code", "industry_name"
    ])
    universe = pd.DataFrame(universe_rows, columns=[
        "date", "symbol", "name", "listed_date", "de_listed_date", "exchange"
    ])
    for frame in (industry, universe):
        if not frame.empty:
            frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.strftime("%Y-%m-%d")
    return industry, universe, source_failures


def run(
    paths: list[Path],
    output_dir: Path,
    expected_start_month: str | None = None,
    expected_end_month: str | None = None,
) -> dict:
    payloads = [read_payload(path) for path in paths]
    industry, universe, source_failures = normalize_payloads(payloads)
    duplicate_industry = int(industry.duplicated(["date", "symbol"], keep=False).sum())
    duplicate_universe = int(universe.duplicated(["date", "symbol"], keep=False).sum())
    industry = industry.drop_duplicates(["date", "symbol"], keep="last").sort_values(["date", "symbol"])
    universe = universe.drop_duplicates(["date", "symbol"], keep="last").sort_values(["date", "symbol"])
    industry_keys = set(zip(industry["date"], industry["symbol"]))
    universe_keys = set(zip(universe["date"], universe["symbol"]))
    covered = len(industry_keys & universe_keys)
    coverage = covered / len(universe_keys) if universe_keys else 0.0
    metadata_columns = ["listed_date", "de_listed_date", "exchange"]
    if universe.empty:
        metadata_coverage = 0.0
    else:
        metadata_complete = universe[metadata_columns].fillna("").apply(
            lambda column: column.astype(str).str.strip().ne("")
        ).all(axis=1)
        metadata_coverage = float(metadata_complete.mean())
    snapshot_dates = sorted(set(universe["date"]))
    missing_snapshot_months = find_missing_snapshot_months(
        snapshot_dates, expected_start_month, expected_end_month
    )
    errors = []
    if source_failures:
        errors.append(f"源文件失败快照={len(source_failures)}")
    if duplicate_industry:
        errors.append(f"重复行业时点记录={duplicate_industry}")
    if duplicate_universe:
        errors.append(f"重复股票池时点记录={duplicate_universe}")
    if not snapshot_dates:
        errors.append("没有历史股票池快照")
    if missing_snapshot_months:
        errors.append(
            "历史股票池快照月份不连续=" + ",".join(missing_snapshot_months)
        )
    if coverage < 0.95:
        errors.append(f"行业覆盖率不足95%={coverage:.4%}")

    industry_path = output_dir / "monthly_industry.csv.gz"
    universe_path = output_dir / "monthly_universe.csv.gz"
    _atomic_gzip(industry, industry_path)
    _atomic_gzip(universe, universe_path)
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
        "source": "supermind_point_in_time_month_end",
        "expected_start_month": expected_start_month,
        "expected_end_month": expected_end_month,
        "input_files": [{"path": str(path), "sha256": sha256(path)} for path in paths],
        "snapshot_count": len(snapshot_dates),
        "first_snapshot": snapshot_dates[0] if snapshot_dates else None,
        "last_snapshot": snapshot_dates[-1] if snapshot_dates else None,
        "missing_snapshot_months": missing_snapshot_months,
        "industry_rows": len(industry),
        "universe_rows": len(universe),
        "industry_coverage": coverage,
        "universe_metadata_coverage": metadata_coverage,
        "point_in_time_universe_metadata_ready": metadata_coverage >= 0.95,
        "source_failures": source_failures,
        "errors": errors,
        "point_in_time_industry_ready": not errors,
        "daily_st_paused_ready": False,
        "formal_backtest_ready": False,
        "industry_csv": str(industry_path),
        "industry_sha256": sha256(industry_path),
        "universe_csv": str(universe_path),
        "universe_sha256": sha256(universe_path),
    }
    _atomic_json(report, output_dir / "manifest.json")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="导入SuperMind历史行业和股票池快照")
    parser.add_argument("files", nargs="*", help="按年份下载的json或json.gz文件")
    parser.add_argument(
        "--raw-dir", default=None,
        help="自动发现年度文件的目录；同年优先完整版gzip",
    )
    parser.add_argument("--start-year", type=int, default=2018)
    parser.add_argument("--end-year", type=int, default=2026)
    parser.add_argument("--expected-start-month", default="2018-01")
    parser.add_argument("--expected-end-month", default="2026-08")
    parser.add_argument("--output-dir", default=str(ROOT / "runtime" / "industry_history"))
    args = parser.parse_args()
    if args.raw_dir and args.files:
        parser.error("files 与 --raw-dir 不能同时使用")
    if args.raw_dir:
        paths = discover_year_files(Path(args.raw_dir), args.start_year, args.end_year)
    elif args.files:
        paths = [Path(value) for value in args.files]
    else:
        parser.error("必须提供 files 或 --raw-dir")
    report = run(
        paths,
        Path(args.output_dir),
        args.expected_start_month,
        args.expected_end_month,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["errors"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
