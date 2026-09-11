"""虚拟纸面账户：标记市值、成交记账、成本模型与 U0 定仓。

不对接券商；成交只写入 paper/ 下本地账本。成本与风控对齐
config/s1_config.json 与 RISK_POLICY.md。
"""
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
ROOT = Path(__file__).resolve().parents[1]
PAPER_DIR = ROOT / "paper"
ACCOUNT_PATH = PAPER_DIR / "runtime" / "account.json"
LEDGER_PATH = PAPER_DIR / "runtime" / "ledger.csv"
NAV_PATH = PAPER_DIR / "runtime" / "daily_nav.csv"
S1_CONFIG_PATH = ROOT / "config" / "s1_config.json"
OVERRIDE_PATH = PAPER_DIR / "config" / "default_s1_100k.json"

LOT = 100
MIN_NOTIONAL = 4000.0


def now_iso() -> str:
    return datetime.now(CHINA).isoformat(timespec="seconds")


def load_s1_config() -> dict[str, Any]:
    cfg = json.loads(S1_CONFIG_PATH.read_text(encoding="utf-8"))
    if OVERRIDE_PATH.exists():
        ov = json.loads(OVERRIDE_PATH.read_text(encoding="utf-8"))
        if "capital" in ov:
            cfg["capital"] = float(ov["capital"])
        cfg["paper_mode"] = bool(ov.get("paper_mode", True))
    return cfg


def load_account(path: Path = ACCOUNT_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_account(account: dict[str, Any], path: Path = ACCOUNT_PATH) -> None:
    account = deepcopy(account)
    account["updated_at"] = now_iso()
    path.write_text(json.dumps(account, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def compute_costs(notional: float, side: str, costs: dict[str, Any]) -> CostBreakdown:
    notional = abs(float(notional))
    commission = max(notional * float(costs["commission_rate"]), float(costs["minimum_commission"]))
    if notional <= 0:
        commission = 0.0
    transfer = notional * float(costs["transfer_fee_each_side"])
    stamp = notional * float(costs["stamp_tax_sell"]) if side.lower() == "sell" else 0.0
    slippage_cost = notional * float(costs["slippage_each_side"])
    return CostBreakdown(
        commission=round(commission, 4),
        stamp_tax=round(stamp, 4),
        transfer_fee=round(transfer, 4),
        slippage_cost=round(slippage_cost, 4),
    )


def round_lot(qty: int | float) -> int:
    return int(math.floor(float(qty) / LOT) * LOT)


def size_position_u0(
    entry_price: float,
    stop_price: float,
    equity: float,
    cash: float,
    cfg: Optional[dict[str, Any]] = None,
    current_exposure: float = 0.0,
    n_positions: int = 0,
) -> Optional[dict[str, Any]]:
    """按 RISK_POLICY / s1_engine.size_position 的 U0 双重约束定仓。"""
    cfg = cfg or load_s1_config()
    r = cfg["risk"]
    costs = cfg["costs"]
    entry_price = float(entry_price)
    stop_price = float(stop_price)
    if entry_price <= 0 or stop_price <= 0 or stop_price >= entry_price:
        return None
    if n_positions >= int(r["max_positions"]):
        return None

    stop_distance = (entry_price - stop_price) / entry_price
    if stop_distance > float(r["max_stop_distance"]) or stop_distance < float(r["min_stop_distance"]) * 0.999:
        # 允许传入已按 max(结构, ATR, 3%) 算好的止损；此处仅拦 >6%
        if stop_distance > float(r["max_stop_distance"]):
            return None

    per_share_risk = entry_price - stop_price
    risk_budget = equity * float(r["risk_fraction_unvalidated"])
    max_total = float(r["max_total_exposure_unvalidated"])
    max_single = float(r["max_single_exposure_unvalidated"])

    remaining_exposure_cash = max(0.0, equity * max_total - current_exposure)
    gap_qty = round_lot(
        equity * float(r["max_gap_loss_fraction"]) / (entry_price * float(r["gap_stress_fraction"]))
    )
    single_qty = round_lot(equity * max_single / entry_price)
    cash_qty = round_lot(cash / entry_price)
    exposure_qty = round_lot(remaining_exposure_cash / entry_price)
    max_qty = min(gap_qty, single_qty, cash_qty, exposure_qty)

    qty = 0
    estimated_entry_cost = 0.0
    estimated_risk = 0.0
    for candidate in range(max_qty, LOT - 1, -LOT):
        entry_value = candidate * entry_price
        stop_value = candidate * stop_price
        b = compute_costs(entry_value, "buy", costs)
        s = compute_costs(stop_value, "sell", costs)
        total_risk = candidate * per_share_risk + b.total_fees + s.total_fees + s.slippage_cost
        # 买入还需预留费用与滑点占用现金
        cash_needed = entry_value + b.total_fees + b.slippage_cost
        if total_risk <= risk_budget and cash_needed <= cash + 1e-6:
            qty = candidate
            estimated_entry_cost = b.total_fees
            estimated_risk = total_risk
            break

    if qty < LOT or qty * entry_price < MIN_NOTIONAL:
        return None
    return {
        "quantity": qty,
        "entry_price": entry_price,
        "stop_price": round(stop_price, 4),
        "stop_distance": round(stop_distance, 6),
        "normal_risk_amount": round(estimated_risk, 4),
        "gap_stress_amount": round(qty * entry_price * float(r["gap_stress_fraction"]), 4),
        "estimated_entry_cost": round(estimated_entry_cost, 4),
        "notional": round(qty * entry_price, 4),
    }


def positions_market_value(account: dict[str, Any], marks: Optional[dict[str, float]] = None) -> float:
    total = 0.0
    marks = marks or {}
    for pos in account.get("positions") or []:
        sym = pos["symbol"]
        px = float(marks.get(sym, pos.get("last_price", pos["avg_cost"])))
        total += float(pos["qty"]) * px
    return total


def mark_to_market(
    account: dict[str, Any],
    marks: Optional[dict[str, float]] = None,
) -> dict[str, Any]:
    """用 marks 更新持仓 last_price，重算 equity / peak / drawdown。"""
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


def _append_ledger_row(row: dict[str, Any], path: Path = LEDGER_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    fieldnames = [
        "trade_id", "ts", "book", "symbol", "side", "qty", "raw_price", "fill_price",
        "notional", "commission", "stamp_tax", "transfer_fee", "slippage_cost",
        "total_cost", "cash_after", "equity_after", "note",
    ]
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in fieldnames})


def record_fill(
    account: dict[str, Any],
    symbol: str,
    side: str,
    qty: int,
    raw_price: float,
    cfg: Optional[dict[str, Any]] = None,
    book: str = "s1_paper",
    note: str = "",
    marks: Optional[dict[str, float]] = None,
) -> dict[str, Any]:
    """记录一笔纸面成交并更新账户。整手校验；费用按 s1_config。"""
    cfg = cfg or load_s1_config()
    if cfg.get("paper_mode") is False:
        raise RuntimeError("config 未处于 paper_mode，拒绝记账以防误用")
    side = side.lower()
    qty = int(qty)
    if qty <= 0 or qty % LOT != 0:
        raise ValueError("数量必须为正且为 100 股整手")
    costs = cfg["costs"]
    slip = float(costs["slippage_each_side"])
    fill_price = apply_slippage(float(raw_price), side, slip)
    notional = qty * fill_price
    bd = compute_costs(notional, side, costs)
    account = deepcopy(account)
    positions = {p["symbol"]: p for p in account.get("positions") or []}

    if side == "buy":
        cash_out = notional + bd.total_fees
        if cash_out > float(account["cash"]) + 1e-6:
            raise ValueError("现金不足")
        account["cash"] = round(float(account["cash"]) - cash_out, 4)
        if symbol in positions:
            pos = positions[symbol]
            new_qty = int(pos["qty"]) + qty
            pos["avg_cost"] = (float(pos["avg_cost"]) * int(pos["qty"]) + notional) / new_qty
            pos["qty"] = new_qty
            pos["last_price"] = fill_price
        else:
            if len(positions) >= int(cfg["risk"]["max_positions"]):
                raise ValueError("已达最多持仓只数")
            positions[symbol] = {
                "symbol": symbol,
                "qty": qty,
                "avg_cost": round(fill_price, 6),
                "last_price": fill_price,
                "book": book,
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
    _append_ledger_row(
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
        }
    )
    save_account(account)
    return {"trade_id": trade_id, "account": account, "costs": asdict(bd), "fill_price": fill_price}


def append_daily_nav(
    account: dict[str, Any],
    trade_date: str,
    market_gate: Optional[bool] = None,
    note: str = "",
    path: Path = NAV_PATH,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "date", "cash", "positions_mv", "equity", "peak_equity",
        "drawdown_from_peak", "n_positions", "exposure_pct", "market_gate", "note",
    ]
    write_header = not path.exists() or path.stat().st_size == 0
    gate_str = "" if market_gate is None else ("ON" if market_gate else "OFF")
    row = {
        "date": trade_date,
        "cash": f"{float(account['cash']):.2f}",
        "positions_mv": f"{float(account.get('positions_mv', 0.0)):.2f}",
        "equity": f"{float(account['equity']):.2f}",
        "peak_equity": f"{float(account['peak_equity']):.2f}",
        "drawdown_from_peak": f"{float(account.get('drawdown_from_peak', 0.0)):.4f}",
        "n_positions": len(account.get("positions") or []),
        "exposure_pct": f"{float(account.get('exposure_pct', 0.0)):.4f}",
        "market_gate": gate_str,
        "note": note,
    }
    # 同日覆盖：读入后替换同 date 行
    rows: list[dict[str, str]] = []
    if path.exists() and path.stat().st_size > 0:
        with path.open(newline="", encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if r.get("date") != trade_date]
    rows.append(row)
    rows.sort(key=lambda r: r["date"])
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def drawdown_actions(account: dict[str, Any]) -> list[str]:
    dd = float(account.get("drawdown_from_peak") or 0.0)
    actions = []
    if dd >= 0.12:
        actions.append("回撤≥12%：停止纸面新交易，退回规则复验")
    elif dd >= 0.08:
        actions.append("回撤≥8%：已有持仓风险减半，仅管理退出")
    elif dd >= 0.06:
        actions.append("回撤≥6%：停止新开仓，检查数据/规则/执行")
    return actions
