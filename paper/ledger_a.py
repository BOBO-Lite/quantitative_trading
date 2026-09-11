"""账本 A：红利 ETF 510880 买入持有 + 日终 MTM。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from broker import (
    PAPER_DIR,
    LOT,
    load_account,
    load_costs,
    mark_to_market,
    nav_row_from_account,
    record_fill,
    round_lot,
    save_account,
    upsert_nav,
    compute_costs,
    apply_slippage,
)
from data_feed import latest_close, load_or_fetch_bars

ACCOUNT_A = PAPER_DIR / "accounts" / "A_main.json"
LEDGER_A = PAPER_DIR / "ledger_A.csv"
NAV_A = PAPER_DIR / "nav_A.csv"
SYMBOL = "510880"


def initialize_buy_if_flat(asof: Optional[str] = None) -> dict[str, Any]:
    """若空仓则尽量买入 510880（100 份整手）。"""
    account = load_account(ACCOUNT_A)
    result: dict[str, Any] = {
        "book": "A_main",
        "symbol": SYMBOL,
        "action": "hold",
        "filled": False,
        "messages": [],
    }
    if account.get("positions"):
        result["messages"].append("已有持仓，跳过建仓")
        return result

    try:
        df, src = load_or_fetch_bars(SYMBOL, start_date="20180101")
        dt, raw_px = latest_close(df, asof=asof)
        result["price_date"] = str(dt.date())
        result["raw_price"] = raw_px
        result["source"] = src
    except Exception as exc:  # noqa: BLE001
        result["action"] = "buy_failed"
        result["messages"].append(f"无法获取 510880 价格: {exc}")
        return result

    costs = load_costs()
    cash = float(account["cash"])
    # 迭代估计整手：成交价含滑点，另扣佣金+过户
    slip = float(costs["slippage_each_side"])
    fill_est = apply_slippage(raw_px, "buy", slip)
    # 粗算最大整手
    qty = round_lot(cash / fill_est)
    while qty >= LOT:
        notional = qty * fill_est
        bd = compute_costs(notional, "buy", costs, is_etf=True)
        need = notional + bd.total_fees
        if need <= cash + 1e-6:
            break
        qty -= LOT
    if qty < LOT:
        result["action"] = "buy_failed"
        result["messages"].append(
            f"现金不足以买入 1 手: cash={cash:.2f} fill_est={fill_est:.4f}"
        )
        return result

    try:
        fill = record_fill(
            account,
            symbol=SYMBOL,
            side="buy",
            qty=qty,
            raw_price=raw_px,
            ledger_path=LEDGER_A,
            account_path=ACCOUNT_A,
            book="A_main",
            note=f"初始建仓 buy-and-hold; px_date={result['price_date']}; src={src}",
            marks={SYMBOL: fill_est},
            costs=costs,
            enforce_max_positions=False,
        )
        result["action"] = "buy"
        result["filled"] = True
        result["qty"] = qty
        result["fill_price"] = fill["fill_price"]
        result["trade_id"] = fill["trade_id"]
        result["account"] = fill["account"]
        result["messages"].append(f"纸面买入 {qty} 份 @ {fill['fill_price']:.4f}")
    except Exception as exc:  # noqa: BLE001
        result["action"] = "buy_failed"
        result["messages"].append(f"成交记账失败: {exc}")
    return result


def daily_mtm(asof: Optional[str] = None, note: str = "") -> dict[str, Any]:
    account = load_account(ACCOUNT_A)
    marks: dict[str, float] = {}
    src = ""
    px_date = ""
    try:
        df, src = load_or_fetch_bars(SYMBOL, start_date="20180101")
        dt, px = latest_close(df, asof=asof)
        marks[SYMBOL] = px
        px_date = str(dt.date())
    except Exception as exc:  # noqa: BLE001
        note = (note + f" | MTM价格失败:{exc}").strip(" |")
    account = mark_to_market(account, marks)
    save_account(account, ACCOUNT_A)
    trade_date = asof or px_date or ""
    if trade_date:
        upsert_nav(NAV_A, nav_row_from_account(account, trade_date, note=note or f"MTM src={src}"))
    return {
        "account": account,
        "marks": marks,
        "price_date": px_date,
        "source": src,
    }
