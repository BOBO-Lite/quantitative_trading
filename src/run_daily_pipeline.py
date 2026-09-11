"""半自动量化系统的唯一收盘入口：底库门禁、增量更新、研究候选。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from generate_candidates import generate_research_outputs
from generate_s2_regime_report import generate_s2_regime_report
from prepare_supermind_scan_data import (
    inspect_daily_bundle_coverage,
    load_benchmark,
    load_daily_parts,
)
from update_daily_incremental import CHINA_TZ, run_update


ROOT = Path(__file__).resolve().parents[1]


def _atomic_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    frame.to_csv(temporary, index=False)
    os.replace(temporary, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sync_new_bundles(download_dir: Path | None, runtime: Path) -> list[str]:
    """只导入新下载分片；同名内容冲突时拒绝覆盖。"""
    if download_dir is None or not download_dir.exists():
        return []
    runtime.mkdir(parents=True, exist_ok=True)
    imported: list[str] = []
    patterns = ["supermind_daily_bundle_[0-9][0-9].json", "supermind_daily_bundle_gz_*.json.gz"]
    for pattern in patterns:
        for source in sorted(download_dir.glob(pattern)):
            destination = runtime / source.name
            if source.resolve() == destination.resolve():
                continue
            if destination.exists():
                if _sha256(source) != _sha256(destination):
                    raise ValueError(f"下载目录与runtime存在同名不同内容：{source.name}")
                continue
            temporary = destination.with_name(f".{destination.name}.importing")
            shutil.copy2(source, temporary)
            if _sha256(source) != _sha256(temporary):
                temporary.unlink(missing_ok=True)
                raise ValueError(f"分片复制后哈希不一致：{source.name}")
            os.replace(temporary, destination)
            imported.append(source.name)
    return imported


def _write_bundle_hashes(runtime: Path, date_label: str) -> Path:
    paths = sorted(runtime.glob("supermind_daily_bundle_[0-9][0-9].json"))
    paths += sorted(runtime.glob("supermind_daily_bundle_gz_*.json.gz"))
    output = runtime / f"supermind_download_sha256_{date_label}.txt"
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in paths), encoding="utf-8"
    )
    os.replace(temporary, output)
    return output


def _prepare_base_if_needed(
    runtime: Path,
    daily_path: Path,
    benchmark_path: Path,
    coverage: dict[str, Any],
) -> str:
    manifest_path = runtime / "s1_base_manifest.json"
    if daily_path.exists() and benchmark_path.exists():
        if not manifest_path.exists():
            raise ValueError("正式底库缺少s1_base_manifest.json来源清单")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("source_status") != "COMPLETE":
            raise ValueError("正式底库来源清单未标记COMPLETE")
        update_manifests = sorted((runtime / "daily_updates").glob("*.json"))
        if update_manifests:
            latest = json.loads(update_manifests[-1].read_text(encoding="utf-8"))
            expected_daily = latest.get("daily_sha256_after")
            expected_benchmark = latest.get("benchmark_sha256_after")
        else:
            expected_daily = manifest.get("daily_sha256")
            expected_benchmark = manifest.get("benchmark_sha256")
        if expected_daily != _sha256(daily_path):
            raise ValueError("正式日线哈希与最新清单不一致")
        if expected_benchmark != _sha256(benchmark_path):
            raise ValueError("中证500哈希与最新清单不一致")
        daily_dates = pd.to_datetime(pd.read_csv(daily_path, usecols=["date"])["date"])
        benchmark_dates = pd.to_datetime(pd.read_csv(benchmark_path, usecols=["date"])["date"])
        if daily_dates.empty or benchmark_dates.empty or daily_dates.max() != benchmark_dates.max():
            raise ValueError("现有正式日线与中证500末日不一致")
        return "ALREADY_PREPARED"

    if daily_path.exists() != benchmark_path.exists():
        raise ValueError("正式日线和中证500只存在一个，拒绝部分重建")
    benchmark = load_benchmark(runtime)
    daily = load_daily_parts(runtime, as_of=benchmark["date"].max())
    _atomic_csv(daily, daily_path)
    _atomic_csv(benchmark, benchmark_path)
    _atomic_json(
        {
            "schema_version": 1,
            "generated_at": datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
            "source_status": coverage["status"],
            "source_batch_count": coverage["seen_batch_count"],
            "source_symbol_count": coverage["symbol_count"],
            "daily_rows": len(daily),
            "daily_symbols": int(daily["symbol"].nunique()),
            "as_of": pd.Timestamp(benchmark["date"].max()).strftime("%Y-%m-%d"),
            "daily_sha256": _sha256(daily_path),
            "benchmark_sha256": _sha256(benchmark_path),
        },
        manifest_path,
    )
    return "PREPARED"


def run_pipeline(
    runtime: Path,
    reports_root: Path,
    config_path: Path,
    download_dir: Path | None = None,
) -> dict[str, Any]:
    started = datetime.now(CHINA_TZ)
    latest_path = runtime / "latest_pipeline_status.json"
    imported = _sync_new_bundles(download_dir, runtime)
    coverage = inspect_daily_bundle_coverage(runtime)
    _atomic_json(coverage, runtime / "supermind_base_status.json")
    if coverage["status"] != "COMPLETE":
        result = {
            "schema_version": 1,
            "generated_at": started.isoformat(timespec="seconds"),
            "status": "WAITING_FOR_COMPLETE_BASE",
            "read_only_market_data": True,
            "automatic_trading": False,
            "imported_bundle_files": imported,
            "base": coverage,
            "message": (
                f"底库未通过{coverage.get('expected_total_batches', 1161)}批/"
                f"当前股票池{coverage.get('expected_symbol_count', '未知')}代码门槛，"
                "未更新日线、未生成候选。"
            ),
        }
        _atomic_json(result, latest_path)
        return result

    daily_path = runtime / "s1_daily.csv"
    benchmark_path = runtime / "s1_benchmark.csv"
    try:
        hash_manifest = _write_bundle_hashes(runtime, started.strftime("%Y-%m-%d"))
        base_action = _prepare_base_if_needed(runtime, daily_path, benchmark_path, coverage)
        update = run_update(
            daily_path,
            benchmark_path,
            runtime,
            runtime / "daily_updates",
            config_path=config_path,
        )
        signal_date = pd.Timestamp(update["target_date"])
        report_dir = reports_root / signal_date.strftime("%Y-%m-%d")
        scan = generate_research_outputs(
            daily_path, benchmark_path, config_path, signal_date, report_dir
        )
        s2_config_path = ROOT / "config" / "s2_regime_config.json"
        s2 = generate_s2_regime_report(
            benchmark_path,
            report_dir,
            s2_config_path,
            runtime / "industry_history" / "manifest.json",
            runtime / "industry_history" / "industry_daily_returns.csv.gz",
        )
        result = {
            "schema_version": 1,
            "generated_at": datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
            "status": "COMPLETE",
            "read_only_market_data": True,
            "automatic_trading": False,
            "base_action": base_action,
            "imported_bundle_files": imported,
            "base_sha256_manifest": str(hash_manifest),
            "base_batch_count": coverage["seen_batch_count"],
            "base_symbol_count": coverage["symbol_count"],
            "incremental_update": {
                "status": update["status"],
                "target_date": update["target_date"],
                "coverage": update["coverage"],
                "manifest": str(runtime / "daily_updates" / f"{update['target_date']}.json"),
            },
            "research_scan": {
                "signal_date": scan["signal_date"],
                "market_gate": scan["market_gate"],
                "observation_count": scan["observation_count"],
                "candidate_count": scan["candidate_count"],
                "report_dir": str(report_dir),
            },
            "s2_regime_research": s2["state"],
            "elapsed_seconds": round((datetime.now(CHINA_TZ) - started).total_seconds(), 3),
        }
    except Exception as exc:
        result = {
            "schema_version": 1,
            "generated_at": datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
            "status": "FAILED_CLOSED",
            "read_only_market_data": True,
            "automatic_trading": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "message": "流水线已停止，未执行任何交易操作。",
        }
        _atomic_json(result, latest_path)
        raise

    _atomic_json(result, latest_path)
    run_path = runtime / "pipeline_runs" / f"{started.strftime('%Y%m%d_%H%M%S')}.json"
    _atomic_json(result, run_path)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="A股半自动系统收盘流水线（只读行情）")
    parser.add_argument("--runtime", default=str(ROOT / "runtime"))
    parser.add_argument("--reports-root", default=str(ROOT / "reports" / "daily"))
    parser.add_argument("--config", default=str(ROOT / "config" / "s1_config.json"))
    parser.add_argument(
        "--supermind-download-dir",
        default=r"D:\steam\SuperMindTYB",
        help="SuperMind下载目录；只导入新分片，同名冲突会停止",
    )
    args = parser.parse_args()
    try:
        result = run_pipeline(
            Path(args.runtime),
            Path(args.reports_root),
            Path(args.config),
            Path(args.supermind_download_dir) if args.supermind_download_dir else None,
        )
    except Exception as exc:
        print(json.dumps({"status": "FAILED_CLOSED", "error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
