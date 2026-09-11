"""Run inside a logged-in SuperMind research environment.

Set ACCOUNT_ID and OUTPUT_PATH locally before execution. The output contains no
account id or token; it is a read-only snapshot consumed by the MCP bridge.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from tick_trade_api.api import TradeAPI


ACCOUNT_ID = "REPLACE_LOCALLY"
OUTPUT_PATH = Path("account_snapshot.json")


def export_snapshot() -> None:
    if ACCOUNT_ID == "REPLACE_LOCALLY":
        raise RuntimeError("Set ACCOUNT_ID locally before running")
    api = TradeAPI(account_id=ACCOUNT_ID, retry_query_exception=3, delay_query_exception=3)
    portfolio = dict(api.portfolio)
    fields = [
        "symbol", "name", "amount", "available_amount", "frozen_amount",
        "cost_basis", "last_price", "market_value", "pnl", "profit_rate",
    ]
    positions = []
    for _, info in api.positions.items():
        positions.append({field: info[field] for field in fields})
    snapshot = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "portfolio": portfolio,
        "positions": positions,
    }
    OUTPUT_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")


export_snapshot()

