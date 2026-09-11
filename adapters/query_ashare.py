"""A股只读接口命令行验收工具。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from eastmoney_readonly import historical_daily as eastmoney_daily
from eastmoney_readonly import market_status as eastmoney_status
from eastmoney_readonly import realtime_minutes as eastmoney_minutes
from eastmoney_readonly import realtime_quotes as eastmoney_quotes
from supermind_market_snapshot import historical_bars as supermind_bars
from supermind_market_snapshot import market_status as supermind_status
from supermind_market_snapshot import realtime_minutes as supermind_minutes
from supermind_market_snapshot import realtime_quotes as supermind_quotes
from supermind_market_snapshot import SuperMindSnapshotError


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _provider() -> str:
    requested = os.environ.get("ASHARE_PROVIDER", "auto").lower().strip()
    if requested in {"eastmoney", "supermind"}:
        return requested
    snapshot = Path(os.environ.get("ASHARE_MARKET_SNAPSHOT", "runtime/supermind_market_snapshot.json"))
    return "supermind" if snapshot.resolve().is_file() else "eastmoney"


def main() -> None:
    parser = argparse.ArgumentParser(description="查询只读A股行情")
    parser.add_argument("command", choices=["status", "quote", "minute", "daily"])
    parser.add_argument("symbols", nargs="*", default=["000001.SZ"])
    parser.add_argument("--limit", type=int, default=120)
    args = parser.parse_args()
    provider = _provider()
    if args.command == "status":
        result = supermind_status() if provider == "supermind" else eastmoney_status()
    elif args.command == "quote":
        if provider != "supermind":
            result = eastmoney_quotes(args.symbols)
        else:
            try:
                result = supermind_quotes(args.symbols)
            except SuperMindSnapshotError:
                if os.environ.get("ASHARE_PROVIDER", "auto").lower().strip() != "auto":
                    raise
                result = eastmoney_quotes(args.symbols)
    elif args.command == "minute":
        if provider != "supermind":
            rows = eastmoney_minutes(args.symbols)
        else:
            try:
                rows = supermind_minutes(args.symbols)
            except SuperMindSnapshotError:
                if os.environ.get("ASHARE_PROVIDER", "auto").lower().strip() != "auto":
                    raise
                rows = eastmoney_minutes(args.symbols)
        result = rows[-args.limit :]
    else:
        result = (
            supermind_bars(args.symbols, "daily", args.limit)
            if provider == "supermind"
            else eastmoney_daily(args.symbols, args.limit)
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
