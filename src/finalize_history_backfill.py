"""等待历史回填结束后自动运行质量验收和合并。"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from validate_history_backfill import run as validate_and_merge


ROOT = Path(__file__).resolve().parents[1]
CHINA_TZ = timezone(timedelta(hours=8))


def wait_and_finalize(input_dir: Path, poll_seconds: float, timeout_hours: float) -> dict:
    manifest_path = input_dir / "manifest.json"
    deadline = time.monotonic() + timeout_hours * 3600
    last_completed = None
    while time.monotonic() < deadline:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(poll_seconds)
            continue
        completed = len(manifest.get("completed", []))
        if completed != last_completed:
            print(
                datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
                f"下载状态={manifest.get('status')} 批次={completed}/{manifest.get('total_batches')} "
                f"失败={len(manifest.get('failures', []))}",
                flush=True,
            )
            last_completed = completed
        status = manifest.get("status")
        if status in {"COMPLETE", "COMPLETE_WITH_FAILURES"}:
            if status != "COMPLETE" or manifest.get("failures"):
                raise RuntimeError("历史回填存在失败批次；请续传补齐后再验收")
            report = validate_and_merge(input_dir, merge=True)
            if not report["pre_backtest_ready"]:
                raise RuntimeError("历史回填质量验收未通过，请查看quality_report.json")
            print(
                json.dumps({
                    "status": "FINALIZED",
                    "rows": report["total_rows"],
                    "merged_path": report["merged_path"],
                    "merged_sha256": report["merged_sha256"],
                    "formal_backtest_ready": report["formal_backtest_ready"],
                }, ensure_ascii=False, indent=2),
                flush=True,
            )
            return report
        time.sleep(poll_seconds)
    raise TimeoutError(f"等待历史回填超过{timeout_hours}小时")


def main() -> None:
    parser = argparse.ArgumentParser(description="自动等待、验收并合并历史回填")
    parser.add_argument("--input-dir", default=str(ROOT / "runtime" / "history_backfill"))
    parser.add_argument("--poll-seconds", type=float, default=30)
    parser.add_argument("--timeout-hours", type=float, default=6)
    args = parser.parse_args()
    wait_and_finalize(Path(args.input_dir), args.poll_seconds, args.timeout_hours)


if __name__ == "__main__":
    main()
