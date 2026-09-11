"""可续传下载当前可交易主板2018年至今历史日线，供预回测使用。

该数据不包含历史退市股票和完整时点状态，不能单独用于正式样本外验收。
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from s1_engine import load_config
from update_daily_incremental import account_tradable_symbols, load_universe


ROOT = Path(__file__).resolve().parents[1]
CHINA_TZ = timezone(timedelta(hours=8))
SOHU_URL = "https://q.stock.sohu.com/hisHq"
COLUMNS = ["date", "symbol", "open", "high", "low", "close", "volume", "amount"]


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("gb18030")


def fetch_batch(
    symbols: list[str], start_date: str, end_date: str, attempts: int = 3
) -> pd.DataFrame:
    by_code = {symbol[:6]: symbol for symbol in symbols}
    params = {
        "code": ",".join(f"cn_{code}" for code in by_code),
        "start": start_date.replace("-", ""),
        "end": end_date.replace("-", ""),
        "stat": 1,
        "order": "D",
        "period": "d",
        "rt": "json",
    }
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = Request(
                f"{SOHU_URL}?{urlencode(params)}",
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://q.stock.sohu.com/"},
            )
            with urlopen(request, timeout=30) as response:
                payload = json.loads(_decode(response.read()))
            rows = []
            for block in payload or []:
                symbol = by_code.get(str(block.get("code") or "").replace("cn_", ""))
                if symbol is None or int(block.get("status", -1)) not in (0, 2):
                    continue
                for item in block.get("hq") or []:
                    if len(item) < 9 or item[1] in ("", "-"):
                        continue
                    rows.append({
                        "date": item[0],
                        "symbol": symbol,
                        "open": float(item[1]),
                        "high": float(item[6]),
                        "low": float(item[5]),
                        "close": float(item[2]),
                        "volume": float(item[7]) * 100.0,
                        "amount": float(item[8]) * 10000.0,
                    })
            frame = pd.DataFrame(rows, columns=COLUMNS)
            if not frame.empty:
                frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
                frame = frame.sort_values(["date", "symbol"]).reset_index(drop=True)
            return frame
        except Exception as exc:
            last_error = exc
            time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"搜狐历史批次失败：{last_error}") from last_error


def fetch_batch_resilient(
    symbols: list[str], start_date: str, end_date: str
) -> pd.DataFrame:
    """整批失败时递归拆分，直到单股；避免一个500错误丢掉五只。"""
    try:
        return fetch_batch(symbols, start_date, end_date)
    except Exception:
        if len(symbols) <= 1:
            raise
        middle = len(symbols) // 2
        left = fetch_batch_resilient(symbols[:middle], start_date, end_date)
        right = fetch_batch_resilient(symbols[middle:], start_date, end_date)
        return pd.concat([left, right], ignore_index=True).sort_values(
            ["date", "symbol"]
        ).reset_index(drop=True)


def _atomic_gzip_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with gzip.open(temporary, "wt", encoding="utf-8", newline="") as handle:
        frame.to_csv(handle, index=False)
    os.replace(temporary, path)


def _atomic_json(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(10):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            # Windows上监视进程短暂读取manifest时可能阻止原子替换。
            time.sleep(0.05 * (attempt + 1))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(
    output_dir: Path,
    start_date: str,
    end_date: str,
    batch_size: int,
    start_batch: int,
    end_batch: int | None,
    delay_seconds: float,
    workers: int,
) -> dict:
    _, metadata = load_universe(ROOT / "runtime")
    cfg = load_config(ROOT / "config" / "s1_config.json")
    symbols = account_tradable_symbols(metadata, cfg)
    total_batches = (len(symbols) + batch_size - 1) // batch_size
    stop_batch = total_batches if end_batch is None else min(end_batch, total_batches)
    parts_dir = output_dir / "parts"
    manifest_path = output_dir / "manifest.json"
    completed: list[dict] = []
    failures: list[dict] = []
    pending: list[tuple[int, list[str], Path]] = []
    for batch_number in range(start_batch, stop_batch):
        selected = symbols[batch_number * batch_size:(batch_number + 1) * batch_size]
        part_path = parts_dir / f"history_{batch_number:04d}.csv.gz"
        if part_path.exists() and part_path.stat().st_size > 100:
            completed.append({
                "batch": batch_number,
                "symbols": selected,
                "path": str(part_path),
                "bytes": part_path.stat().st_size,
                "sha256": _sha256(part_path),
                "reused": True,
            })
        else:
            pending.append((batch_number, selected, part_path))

    def manifest_payload(status: str) -> dict:
        return {
            "schema_version": 1,
            "generated_at": datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
            "status": status,
            "source": "sohu_public_history",
            "formal_backtest_ready": False,
            "start_date": start_date,
            "end_date": end_date,
            "batch_size": batch_size,
            "workers": workers,
            "total_symbols": len(symbols),
            "total_batches": total_batches,
            "requested_start_batch": start_batch,
            "requested_end_batch": stop_batch,
            "completed": sorted(completed, key=lambda item: item["batch"]),
            "failures": sorted(failures, key=lambda item: item["batch"]),
            "limitations": [
                "仅覆盖当前账户可交易主板股票，存在生存者偏差",
                "缺少历史时点ST、退市、停牌股票池和历史行业归属",
                "只能用于预回测和数据交叉核验，不能用于正式样本外验收",
            ],
        }

    _atomic_json(manifest_payload("RUNNING"), manifest_path)

    def download(job: tuple[int, list[str], Path]) -> dict:
        batch_number, selected, part_path = job
        frame = fetch_batch_resilient(selected, start_date, end_date)
        returned = set(frame["symbol"]) if not frame.empty else set()
        missing = sorted(set(selected) - returned)
        _atomic_gzip_csv(frame, part_path)
        return {
            "batch": batch_number,
            "symbols": selected,
            "rows": len(frame),
            "missing_symbols": missing,
            "path": str(part_path),
            "bytes": part_path.stat().st_size,
            "sha256": _sha256(part_path),
            "reused": False,
        }

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(download, job): job for job in pending}
        for completed_count, future in enumerate(as_completed(futures), 1):
            batch_number, selected, _ = futures[future]
            try:
                completed.append(future.result())
            except Exception as exc:
                failures.append({
                    "batch": batch_number,
                    "symbols": selected,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                })
            _atomic_json(manifest_payload("RUNNING"), manifest_path)
            print(
                f"history progress: {completed_count}/{len(pending)} pending; "
                f"completed={len(completed)} failures={len(failures)}",
                flush=True,
            )
            time.sleep(delay_seconds)

    manifest = manifest_payload(
        "COMPLETE" if not failures else "COMPLETE_WITH_FAILURES"
    )
    manifest["finished_at"] = datetime.now(CHINA_TZ).isoformat(timespec="seconds")
    _atomic_json(manifest, manifest_path)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="下载当前主板股票多年日线（预回测）")
    parser.add_argument("--output-dir", default=str(ROOT / "runtime" / "history_backfill"))
    parser.add_argument("--start-date", default="2018-01-01")
    parser.add_argument("--end-date", default=datetime.now(CHINA_TZ).date().isoformat())
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--start-batch", type=int, default=0)
    parser.add_argument("--end-batch", type=int)
    parser.add_argument("--delay-seconds", type=float, default=0.25)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 20:
        raise ValueError("batch-size必须为1到20")
    if not 1 <= args.workers <= 6:
        raise ValueError("workers必须为1到6")
    result = run(
        Path(args.output_dir), args.start_date, args.end_date,
        args.batch_size, args.start_batch, args.end_batch, args.delay_seconds,
        args.workers,
    )
    print(json.dumps({
        "status": result["status"],
        "completed_batches": len(result["completed"]),
        "failed_batches": len(result["failures"]),
        "manifest": str(Path(args.output_dir) / "manifest.json"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
