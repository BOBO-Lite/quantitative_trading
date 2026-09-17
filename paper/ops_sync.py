#!/usr/bin/env python3
"""Sync sanitized paper runtime artifacts into paper/ops for GitHub."""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "paper" / "runtime"
OPS = ROOT / "paper" / "ops"
SH = ZoneInfo("Asia/Shanghai")


def _copy_if(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def sync_runtime() -> dict:
    OPS.mkdir(parents=True, exist_ok=True)
    (OPS / "reports").mkdir(parents=True, exist_ok=True)
    (OPS / "evening").mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for name in ("account.json", "daily_nav.csv", "ledger.csv"):
        src = RUNTIME / name
        dst_name = "account_snapshot.json" if name == "account.json" else name
        if _copy_if(src, OPS / dst_name):
            copied.append(dst_name)
    reports = RUNTIME / "reports"
    if reports.exists():
        for day_dir in sorted(p for p in reports.iterdir() if p.is_dir()):
            for f in day_dir.iterdir():
                if f.suffix.lower() in {".md", ".json", ".csv", ".txt"}:
                    rel = f"reports/{day_dir.name}/{f.name}"
                    if _copy_if(f, OPS / rel):
                        copied.append(rel)
    manifest = {
        "synced_at": datetime.now(SH).isoformat(timespec="seconds"),
        "source": "paper/runtime",
        "copied_count": len(copied),
        "note": "sanitized ops mirror; no parquet/secrets",
    }
    (OPS / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def write_evening(md: str, day: str | None = None) -> Path:
    day = day or datetime.now(SH).strftime("%Y-%m-%d")
    path = OPS / "evening" / f"{day}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md.rstrip() + "\n", encoding="utf-8")
    sync_runtime()
    return path


def main() -> None:
    p = argparse.ArgumentParser(description="Sync paper ops to paper/ops")
    p.add_argument("--evening-file", help="optional evening markdown path to ingest")
    p.add_argument("--day", help="YYYY-MM-DD for evening filename")
    args = p.parse_args()
    if args.evening_file:
        text = Path(args.evening_file).read_text(encoding="utf-8")
        path = write_evening(text, args.day)
        print(f"[ops] evening={path}")
    m = sync_runtime()
    print(f"[ops] synced_at={m['synced_at']} copied={m['copied_count']}")


if __name__ == "__main__":
    main()
