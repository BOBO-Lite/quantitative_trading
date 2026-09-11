from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return next(csv.reader(f))


def main() -> None:
    errors: list[str] = []
    required_files = [
        "README.md",
        "CURRENT_LIVE_PROTOCOL.md",
        "S1_FROZEN_SPEC.md",
        "RISK_POLICY.md",
        "BACKTEST_ACCEPTANCE.md",
        "S2_REGIME_SPEC.md",
        "config/s1_config.json",
        "config/s2_regime_config.json",
        "logs/trades.csv",
        "logs/deviations.csv",
        "logs/daily_equity.csv",
        "logs/current_positions.csv",
    ]
    for rel in required_files:
        if not (ROOT / rel).exists():
            errors.append(f"missing {rel}")

    cfg = json.loads((ROOT / "config/s1_config.json").read_text(encoding="utf-8"))
    if cfg["status"] != "frozen_pending_backtest":
        errors.append("S1 status must remain frozen_pending_backtest before acceptance")
    if cfg["risk"]["risk_fraction_unvalidated"] > 0.0125:
        errors.append("unvalidated risk exceeds 1.25%")
    if cfg["risk"]["max_total_exposure_unvalidated"] > 0.70:
        errors.append("unvalidated total exposure exceeds 70%")
    if not cfg["entry"]["fill_on_next_bar"]:
        errors.append("same-bar fill would create look-ahead bias")
    excluded_prefixes = set(cfg["universe"].get("excluded_symbol_prefixes", []))
    if not {"300", "301", "688", "689"}.issubset(excluded_prefixes):
        errors.append("unconfirmed ChiNext/STAR permissions must fail closed")
    excluded_exchanges = set(cfg["universe"].get("excluded_exchanges", []))
    if "BJ" not in excluded_exchanges:
        errors.append("unconfirmed Beijing Stock Exchange permission must fail closed")

    s2 = json.loads((ROOT / "config/s2_regime_config.json").read_text(encoding="utf-8"))
    if s2["status"] != "research_only_pending_backtest":
        errors.append("S2 must remain research-only before separate acceptance")
    if s2["drawdown_control"]["hard_stop"] != 0.15:
        errors.append("S2 hard drawdown stop must remain 15%")
    if max(item["target_exposure"] for item in s2["strategies"].values()) > 0.90:
        errors.append("S2 research target exposure exceeds 90%")
    if s2["market_neutral"]["enabled"]:
        errors.append("market-neutral route requires verified hedge permission")

    trade_columns = set(read_header(ROOT / "logs/trades.csv"))
    for col in {
        "trade_id", "strategy_version", "planned_qty", "actual_qty",
        "actual_price", "initial_stop", "net_pnl", "mae_pct", "mfe_pct",
        "benchmark_return_pct", "rule_compliant",
    }:
        if col not in trade_columns:
            errors.append(f"trades.csv missing {col}")

    protocol = (ROOT / "CURRENT_LIVE_PROTOCOL.md").read_text(encoding="utf-8")
    if "唯一盘中入口" not in protocol:
        errors.append("live protocol is not marked as the sole intraday entry")
    if "禁止新开仓" not in protocol:
        errors.append("current overexposure guard is missing")

    result = {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "frozen_strategy": cfg["version"],
        "unvalidated_risk_fraction": cfg["risk"]["risk_fraction_unvalidated"],
        "max_total_exposure": cfg["risk"]["max_total_exposure_unvalidated"],
        "s2_status": s2["status"],
        "s2_max_target_exposure": max(
            item["target_exposure"] for item in s2["strategies"].values()
        ),
        "s2_hard_drawdown_stop": s2["drawdown_control"]["hard_stop"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
