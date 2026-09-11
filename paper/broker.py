"""纸面成交引擎：费用、整手、标记市值。不对接券商。"""
from __future__ import annotations

import csv
import json
import math
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

CHINA = ZoneInfo("Asia/Shanghai")
PAPER_DIR = Path(__file__).resolve().parent
ROOT = PAPER_DIR.parent
S1_CONFIG_PATH = ROOT / "config" / "s1_config.json"
LOT = 100
MIN_NOTIONAL = 4000.0

DEFAULT_COSTS = {
    "commission_rate": 0.0002,
    "minimum_commission": 5.0,
    "stamp_tax_sell": 0.0005,
    "transfer_fee_each_side": 0.00001,
    "slippage_each_side": 0.001,
}


def now_iso() -> str:
    return datetime.now(CHINA).isoformat(timespec="seconds")


def load_costs() -> dict[str, Any]:
    if S1_CONFIG_PATH.exists():
        cfg = json.loads(S1_CONFIG_PATH.read_text(encoding="utf-8"))
        return dict(cfg.get("costs") or DEFAULT_COSTS)
    return dict(DEFAULT_COSTS)


def load_risk() -> dict[str, Any]:
    if S1_CONFIG_PATH.exists():
        cfg = json.loads(S1_CONFIG_PATH.read_text(encoding="utf-8"))
        return dict(cfg.get("risk") or {})
    return {
        "risk_fraction_unvalidated": 0.0125,
        "max_total_exposure_unvalidated": 0.70,
        "max_single_exposure_unvalidated": 0.35,
        "max_positions": 3,
        "max_stop_distance": 0.06,
        "min_stop_distance": 0.03,
        "gap_stress_fraction": 0.08,
        "max_gap_loss_fraction": 0.02,
        "atr_multiple": 1.6,
        "atr_days": 20,
    }


def is_etf_symbol(symbol: str) -> bool:
    code = symbol.split(".")[0]
    return code.startswith(("51", "56", "58", "15", "16", "18"))


def round_lot(qty: float | int) -> int:
    return int(math.floor(float(qty) / LOT) * LOT)


@dataclass
class CostBreakdown:
    commission: float
    stamp_tax: float
    transfer_fee: float
    slippage_cost: float

    @property
    def total_fees(self) -> float:
        return self.commission + self.stamp_tax + self.transfer_fee

    @property
    def total_cost(self) -> float:
        return self.total_fees + self.slippage_cost


def apply_slippage(raw_price: float, side: str, slippage: float) -> float:
    side = side.lower()
    if side == "buy":
        return raw_price * (1.0 + slippage)
    if side == "sell":
        return raw_price * (1.0 - slippage)
    raise ValueError("side must be buy or sell")


def compute_costs(
    notional: float,
    side: str,
    costs: Optional[dict[str, Any]] = None,
    *,
    is_etf: bool = False,
) -> CostBreakdown:
    costs = costs or load_costs()
    notional = abs(float(notional))
    commission = max(notional * float(costs["commission_rate"]), float(costs["minimum_commission"]))
    if notional <= 0:
        commission = 0.0
    transfer = notional * float(costs["transfer_fee_each_side"])
    stamp_rate = 0.0 if is_etf else float(costs["stamp_tax_sell"])
    stamp = notional * stamp_rate if side.lower() == "sell" else 0.0
    slippage_cost = notional * float(costs["slippage_each_side"])
    return CostBreakdown(
        commission=round(commission, 4),
        stamp_tax=round(stamp, 4),
        transfer_fee=round(transfer, 4),
        slippage_cost=round(slippage_cost, 4),
    )


def new_account(
    book: str,
    cash: float,
    strategy: str,
    started_at: Optional[str] = None,
) -> dict[str, Any]:
    ts = started_at or now_iso()
    cash = float(cash)
    return {
        "mode": "virtual",
        "book": book,
        "stage": "U0",
        "strategy": strategy,
        "currency": "CNY",
        "cash": cash,
        "equity": cash,
        "peak_equity": cash,
        "positions_mv": 0.0,
        "exposure_pct": 0.0,
        "drawdown_from_peak": 0.0,
        "positions": [],
        "started_at": ts,
        "updated_at": ts,
        "note": "虚拟纸面账户；禁止真实券商下单。",
    }


def load_account(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_account(account: dict[str, Any], path: Path) -> None:
    account = deepcopy(account)
    account["updated_at"] = now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(account, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mark_to_market(
    account: dict[str, Any],
    marks: Optional[dict[str, float]] = None,
) -> dict[str, Any]:
    account = deepcopy(account)
    marks = marks or {}
    mv = 0.0
    for pos in account.get("positions") or []:
        sym = pos["symbol"]
        if sym in marks:
            pos["last_price"] = float(marks[sym])
        px = float(pos.get("last_price", pos["avg_cost"]))
        pos["market_value"] = round(float(pos["qty"]) * px, 4)
        mv += pos["market_value"]
    cash = float(account["cash"])
    equity = round(cash + mv, 4)
    peak = max(float(account.get("peak_equity", equity)), equity)
    account["equity"] = equity
    account["peak_equity"] = peak
    account["drawdown_from_peak"] = round(1.0 - equity / peak, 6) if peak > 0 else 0.0
    account["positions_mv"] = round(mv, 4)
    account["exposure_pct"] = round(mv / equity, 6) if equity > 0 else 0.0
    return account


LEDGER_FIELDS = [
    "trade_id", "ts", "book", "symbol", "side", "qty", "raw_price", "fill_price",
    "notional", "commission", "stamp_tax", "transfer_fee", "slippage_cost",
    "total_cost", "cash_after", "equity_after", "note",
]

NAV_FIELDS = [
    "date", "cash", "positions_mv", "equity", "peak_equity",
    "drawdown_from_peak", "n_positions", "exposure_pct", "note",
]


def ensure_ledger_header(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.stat().st_size == 0:
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=LEDGER_FIELDS).writeheader()


def append_ledger(path: Path, row: dict[str, Any]) -> None:
    ensure_ledger_header(path)
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_FIELDS)
        w.writerow({k: row.get(k, "") for k in LEDGER_FIELDS})


def upsert_nav(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    if path.exists() and path.stat().st_size > 0:
        with path.open(newline="", encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if r.get("date") != row["date"]]
    rows.append({k: str(row.get(k, "")) for k in NAV_FIELDS})
    rows.sort(key=lambda r: r["date"])
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=NAV_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in NAV_FIELDS})


def record_fill(
    account: dict[str, Any],
    *,
    symbol: str,
    side: str,
    qty: int,
    raw_price: float,
    ledger_path: Path,
    account_path: Path,
    book: str,
    note: str = "",
    marks: Optional[dict[str, float]] = None,
    costs: Optional[dict[str, Any]] = None,
    enforce_max_positions: bool = True,
) -> dict[str, Any]:
    """记录一笔纸面成交。"""
    costs = costs or load_costs()
    side = side.lower()
    qty = int(qty)
    if qty <= 0 or qty % LOT != 0:
        raise ValueError("数量必须为正且为 100 整手")
    etf = is_etf_symbol(symbol)
    slip = float(costs["slippage_each_side"])
    fill_price = apply_slippage(float(raw_price), side, slip)
    notional = qty * fill_price
    bd = compute_costs(notional, side, costs, is_etf=etf)
    account = deepcopy(account)
    positions = {p["symbol"]: p for p in account.get("positions") or []}
    risk = load_risk()

    if side == "buy":
        cash_out = notional + bd.total_fees
        if cash_out > float(account["cash"]) + 1e-6:
            raise ValueError(f"现金不足: need={cash_out:.2f} cash={account['cash']:.2f}")
        account["cash"] = round(float(account["cash"]) - cash_out, 4)
        if symbol in positions:
            pos = positions[symbol]
            new_qty = int(pos["qty"]) + qty
            pos["avg_cost"] = (float(pos["avg_cost"]) * int(pos["qty"]) + notional) / new_qty
            pos["qty"] = new_qty
            pos["last_price"] = fill_price
        else:
            if enforce_max_positions and len(positions) >= int(risk.get("max_positions", 3)):
                raise ValueError("已达最多持仓只数")
            positions[symbol] = {
                "symbol": symbol,
                "qty": qty,
                "avg_cost": round(fill_price, 6),
                "last_price": fill_price,
                "instrument": "etf" if etf else "stock",
            }
    elif side == "sell":
        if symbol not in positions or int(positions[symbol]["qty"]) < qty:
            raise ValueError("可卖数量不足")
        cash_in = notional - bd.total_fees
        account["cash"] = round(float(account["cash"]) + cash_in, 4)
        pos = positions[symbol]
        left = int(pos["qty"]) - qty
        if left == 0:
            del positions[symbol]
        else:
            pos["qty"] = left
            pos["last_price"] = fill_price
    else:
        raise ValueError("side must be buy or sell")

    account["positions"] = list(positions.values())
    account = mark_to_market(account, marks or {symbol: fill_price})
    trade_id = uuid.uuid4().hex[:12]
    append_ledger(
        ledger_path,
        {
            "trade_id": trade_id,
            "ts": now_iso(),
            "book": book,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "raw_price": round(float(raw_price), 6),
            "fill_price": round(fill_price, 6),
            "notional": round(notional, 4),
            "commission": bd.commission,
            "stamp_tax": bd.stamp_tax,
            "transfer_fee": bd.transfer_fee,
            "slippage_cost": bd.slippage_cost,
            "total_cost": bd.total_cost,
            "cash_after": account["cash"],
            "equity_after": account["equity"],
            "note": note,
        },
    )
    save_account(account, account_path)
    return {"trade_id": trade_id, "account": account, "costs": asdict(bd), "fill_price": fill_price}


def nav_row_from_account(account: dict[str, Any], trade_date: str, note: str = "") -> dict[str, Any]:
    return {
        "date": trade_date,
        "cash": f"{float(account['cash']):.2f}",
        "positions_mv": f"{float(account.get('positions_mv', 0.0)):.2f}",
        "equity": f"{float(account['equity']):.2f}",
        "peak_equity": f"{float(account['peak_equity']):.2f}",
        "drawdown_from_peak": f"{float(account.get('drawdown_from_peak', 0.0)):.4f}",
        "n_positions": len(account.get("positions") or []),
        "exposure_pct": f"{float(account.get('exposure_pct', 0.0)):.4f}",
        "note": note,
    }
