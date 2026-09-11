"""命令行查看本地SuperMind行情快照，不需要启动MCP服务。"""

from __future__ import annotations

import argparse
import json

from supermind_market_snapshot import (
    historical_bars,
    market_status,
    realtime_quotes,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="读取SuperMind只读行情快照")
    parser.add_argument("mode", choices=["status", "quote", "daily", "minute"])
    parser.add_argument("symbols", nargs="*", help="例如 601975.SH 601555.SH")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    if args.mode == "status":
        result = market_status()
    elif args.mode == "quote":
        result = realtime_quotes(args.symbols)
    else:
        result = historical_bars(args.symbols, args.mode, args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
