#!/usr/bin/env python3
"""S1.1 research-grade APPROX_NEXT_OPEN daily backtest (public data).

mode=APPROX_NEXT_OPEN: signal-day close candidates → next open fill with gap checks.
Does NOT claim frozen 09:45–10:30 minute confirmation.

Tags: NOT_VALIDATED | APPROX_NEXT_OPEN | UNIVERSE_REDUCED
"""
from __future__ import annotations

import json
import math
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from paper import data_feed  # noqa: E402
from s1_engine import (  # noqa: E402
    buy_cost,
    load_config,
    prepare_daily_features,
    sell_cost,
)

OUT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT / "paper" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

CAPITAL = 100_000.0
START = "20190101"
ENTRY_MODE = "APPROX_NEXT_OPEN"

# Expanded high-liquidity mainboard static universe (UNIVERSE_REDUCED)
STATIC_UNIVERSE = [
    "600519", "601318", "600036", "601166", "600900", "601288", "601398",
    "600028", "601088", "600030", "601628", "600276", "601012", "600887",
    "601668", "600031", "601857", "600050", "601225", "600309", "600585",
    "601601", "600104", "601766", "600019", "600048", "601919", "600690",
    "601328", "600000", "601211", "600016", "601818", "600406", "601688",
    "600893", "601390", "600660", "601186", "600547",
    "000001", "000002", "000063", "000333", "000651", "000858", "002415",
    "002594", "002714", "000725", "002304", "000538", "002142", "000776",
    "002027", "000166", "002236", "000568", "002352", "000338", "002475",
    "000100", "002230", "000157", "002241", "000425", "002008", "000983",
    "002050", "000895", "002001", "000768", "002179", "000625", "002460",
]


@dataclass
class Position:
    symbol: str
    entry_date: pd.Timestamp
    entry_price: float
    quantity: int
    stop_price: float
    initial_r: float
    signal_close: float
    atr20_at_entry: float
    structure_low10: float
    buy_cost: float
    effective_stop: float
    highest_close: float
    holding_days: int = 0
    pending_exit_reason: Optional[str] = None
    score: float = 0.0


@dataclass
class BacktestResult:
    label: str
    nav: pd.DataFrame
    trades: pd.DataFrame
    metrics: dict[str, Any]
    notes: list[str] = field(default_factory=list)


def _ts_code(code: str) -> str:
    c = str(code).split(".")[0].zfill(6)
    return f"{c}.SH" if c.startswith(("5", "6", "9")) else f"{c}.SZ"


def build_universe(max_names: int = 80) -> tuple[list[str], str, dict]:
    meta: dict[str, Any] = {"tag": "UNIVERSE_REDUCED"}
    codes: list[str] = []
    source = "static"
    try:
        rows, tag = data_feed.build_reduced_universe(max_names=max_names)
        codes = [str(r["symbol"]).zfill(6) for r in rows if r.get("symbol")]
        source = tag
        meta["akshare_or_spot"] = tag
    except Exception as exc:  # noqa: BLE001
        meta["universe_error"] = str(exc)
    # merge static to stabilize history coverage
    for c in STATIC_UNIVERSE:
        if c not in codes:
            codes.append(c)
    # filter prefixes
    filtered = []
    for c in codes:
        c = c.zfill(6)
        if c.startswith(("300", "301", "688", "689", "4", "8")):
            continue
        if not c.startswith(("600", "601", "603", "605", "000", "001", "002", "003")):
            continue
        filtered.append(c)
    # dedupe preserve order
    seen = set()
    out = []
    for c in filtered:
        if c not in seen:
            seen.add(c)
            out.append(c)
        if len(out) >= max_names:
            break
    meta["n_symbols_requested"] = len(out)
    meta["source"] = source
    return out, "UNIVERSE_REDUCED", meta


def fetch_bars_robust(symbol: str, start_date: str = "20180101") -> tuple[pd.DataFrame, str]:
    """Prefer data_feed cache/tencent; tolerate failures."""
    end = datetime.now().strftime("%Y%m%d")
    cache = DATA_DIR / f"research_{symbol}.parquet"
    if cache.exists():
        df = pd.read_parquet(cache)
        df["date"] = pd.to_datetime(df["date"])
        last = df["date"].max()
        if (pd.Timestamp(end) - last).days <= 5 and df["date"].min() <= pd.Timestamp("2019-06-01"):
            return df.sort_values("date").reset_index(drop=True), f"cache:{cache.name}"
    df, src = data_feed.load_or_fetch_bars(
        symbol, start_date=start_date, end_date=end, cache_name=f"research_{symbol}.parquet"
    )
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["symbol"] = symbol.zfill(6)
    if "amount" not in df.columns or df["amount"].isna().all():
        df["amount"] = df["close"] * df["volume"] * 100.0
    df.to_parquet(cache, index=False)
    return df.sort_values("date").reset_index(drop=True), src


def load_panel(symbols: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    info: dict[str, Any] = {"sources": {}, "errors": [], "ok_symbols": []}
    # benchmark
    bdf, bsrc = fetch_bars_robust("000905", start_date="20180101")
    info["sources"]["000905"] = bsrc
    frames = []
    for i, sym in enumerate(symbols):
        try:
            df, src = fetch_bars_robust(sym)
            if df.empty or len(df) < 150:
                info["errors"].append(f"{sym}:too_short:{len(df)}")
                continue
            # drop days with bad OHLC (qfq 偶发负价，如除权异常)
            df = df.dropna(subset=["open", "high", "low", "close"]).copy()
            df = df[
                (df["high"] >= df["low"])
                & (df["close"] > 0)
                & (df["open"] > 0)
                & (df["high"] > 0)
                & (df["low"] > 0)
                & (df["volume"] >= 0)
            ].copy()
            df.loc[df["amount"] < 0, "amount"] = df["close"] * df["volume"] * 100.0
            frames.append(df)
            info["sources"][sym] = src
            info["ok_symbols"].append(sym)
            print(f"[{i+1}/{len(symbols)}] {sym} n={len(df)} {df['date'].min().date()}→{df['date'].max().date()} src={src}")
        except Exception as exc:  # noqa: BLE001
            info["errors"].append(f"{sym}:{exc}")
            print(f"[{i+1}/{len(symbols)}] FAIL {sym}: {exc}")
        time.sleep(0.08)
    if not frames:
        raise RuntimeError(f"no stock bars loaded: {info['errors'][:10]}")
    panel = pd.concat(frames, ignore_index=True)
    # attach listing_days / paused / st approximations
    parts = []
    for sym, g in panel.groupby("symbol", sort=False):
        g = g.sort_values("date").copy()
        # listing_days: bars since first available; stocks listed before sample start are underestimated
        # bump by 120 so pre-2019 liquid names pass listing filter (documented)
        g["listing_days"] = np.arange(1, len(g) + 1) + 120
        g["paused"] = (g["volume"].fillna(0) <= 0) | (g["amount"].fillna(0) <= 0)
        g["st"] = False
        parts.append(g)
    panel = pd.concat(parts, ignore_index=True)
    bench = bdf.rename(columns={"symbol": "bench_symbol"}).copy()
    if "symbol" not in bench.columns:
        bench["symbol"] = "000905"
    info["panel_start"] = str(panel["date"].min().date())
    info["panel_end"] = str(panel["date"].max().date())
    info["n_ok"] = len(info["ok_symbols"])
    return panel, bench, info


def prepare_features(panel: pd.DataFrame, bench: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    daily = panel.copy()
    # s1_engine expects symbol possibly with exchange; keep 6-digit
    daily["symbol"] = daily["symbol"].astype(str).str.zfill(6)
    for c in ("open", "high", "low", "close", "volume", "amount"):
        daily = daily[daily[c] >= 0]
    daily = daily[(daily["close"] > 0) & (daily["open"] > 0)].copy()
    b = bench.copy()
    b = b[["date", "close"]].drop_duplicates("date")
    b = b[b["close"] > 0]
    feat = prepare_daily_features(daily, b, cfg)
    # one-word limit-up approx: close ~ prior*1.095 (主板) → exclude signal day
    feat = feat.sort_values(["symbol", "date"]).copy()
    feat["prev_close"] = feat.groupby("symbol")["close"].shift(1)
    limit_up = feat["close"] >= feat["prev_close"] * 1.095
    # also near-zero range
    flat = (feat["high"] - feat["low"]) <= 1e-8
    feat.loc[limit_up | flat, "signal"] = False
    return feat


def size_qty(
    *,
    entry_price: float,
    stop_distance: float,
    equity: float,
    cash: float,
    cfg: dict,
    risk_fraction: float,
    max_single_exposure: float,
    max_total_exposure: float,
    current_exposure: float,
) -> tuple[int, float, float]:
    """Return (qty, stop_price, planned_risk)."""
    r = cfg["risk"]
    if not np.isfinite(stop_distance) or stop_distance > r["max_stop_distance"] or stop_distance <= 0:
        return 0, 0.0, 0.0
    stop_price = entry_price * (1 - stop_distance)
    per_share = entry_price - stop_price
    risk_budget = equity * risk_fraction
    remaining_exp = max(0.0, equity * max_total_exposure - current_exposure)
    gap_qty = math.floor(equity * r["max_gap_loss_fraction"] / (entry_price * r["gap_stress_fraction"]) / 100) * 100
    single_qty = math.floor(equity * max_single_exposure / entry_price / 100) * 100
    exp_qty = math.floor(remaining_exp / entry_price / 100) * 100
    cash_qty = math.floor(cash / (entry_price * 1.002) / 100) * 100  # leave room for costs
    max_qty = min(gap_qty, single_qty, exp_qty, cash_qty)
    qty = 0
    planned_risk = 0.0
    for candidate in range(max_qty, 99, -100):
        entry_value = candidate * entry_price
        bcost = buy_cost(entry_value, cfg)
        scost = sell_cost(candidate * stop_price, cfg)
        stop_slip = candidate * stop_price * cfg["costs"]["slippage_each_side"]
        total_risk = candidate * per_share + bcost + scost + stop_slip
        if total_risk <= risk_budget and entry_value + bcost <= cash:
            qty = candidate
            planned_risk = total_risk
            break
    if qty < 100 or qty * entry_price < 4000:
        return 0, 0.0, 0.0
    return qty, stop_price, planned_risk


def run_portfolio(
    feat: pd.DataFrame,
    cfg: dict,
    *,
    label: str,
    risk_fraction: float,
    max_single_exposure: float,
    max_total_exposure: float,
    max_positions: int,
    capital: float = CAPITAL,
) -> BacktestResult:
    notes = [
        f"entry_mode={ENTRY_MODE}",
        "NOT frozen minute confirm 09:45-10:30",
        f"risk_fraction={risk_fraction}",
        f"max_single={max_single_exposure}",
        f"max_total={max_total_exposure}",
        f"max_positions={max_positions}",
    ]
    # index by date for speed
    feat = feat.copy()
    feat["date"] = pd.to_datetime(feat["date"]).dt.normalize()
    dates = sorted(feat["date"].unique())
    by_date_sym = {(pd.Timestamp(r.date), str(r.symbol)): r for r in feat.itertuples(index=False)}
    # next-date map
    next_date = {dates[i]: dates[i + 1] for i in range(len(dates) - 1)}

    # signals by date
    sig = feat[feat["signal"] == True].copy()  # noqa: E712
    signals_by_date: dict[pd.Timestamp, pd.DataFrame] = {
        d: g.sort_values("score", ascending=False) for d, g in sig.groupby("date")
    }

    cash = capital
    positions: dict[str, Position] = {}
    pending_entries: list[dict] = []  # filled next open
    trades: list[dict] = []
    nav_rows: list[dict] = []

    slip = cfg["costs"]["slippage_each_side"]
    e_cfg = cfg["entry"]

    def mtm_equity(asof: pd.Timestamp) -> float:
        total = cash
        for sym, pos in positions.items():
            row = by_date_sym.get((asof, sym))
            px = float(row.close) if row is not None else pos.entry_price
            total += pos.quantity * px
        return total

    def exposure_value(asof: pd.Timestamp) -> float:
        exp = 0.0
        for sym, pos in positions.items():
            row = by_date_sym.get((asof, sym))
            px = float(row.close) if row is not None else pos.entry_price
            exp += pos.quantity * px
        return exp

    for di, dt in enumerate(dates):
        # --- OPEN: execute pending exits first, then pending entries ---
        # 1) pending time/max exits & stop checks for existing positions
        to_close: list[tuple[str, str, float]] = []  # sym, reason, price
        for sym, pos in list(positions.items()):
            row = by_date_sym.get((dt, sym))
            if row is None:
                continue
            # T+1: cannot sell on entry day
            if pd.Timestamp(pos.entry_date).normalize() == dt:
                continue
            open_px = float(row.open)
            low_px = float(row.low)
            # pending open exit (time/max)
            if pos.pending_exit_reason:
                fill = open_px * (1 - slip)
                to_close.append((sym, pos.pending_exit_reason, fill))
                continue
            # gap/open stop
            if open_px <= pos.effective_stop:
                fill = open_px * (1 - slip)
                to_close.append((sym, "gap_or_open_stop", fill))
                continue
            if low_px <= pos.effective_stop:
                fill = pos.effective_stop * (1 - slip)
                to_close.append((sym, "hard_stop", fill))
                continue

        for sym, reason, fill in to_close:
            pos = positions.pop(sym)
            sell_val = pos.quantity * fill
            scost = sell_cost(sell_val, cfg)
            cash += sell_val - scost
            buy_val = pos.quantity * pos.entry_price
            gross = sell_val - buy_val
            net = gross - pos.buy_cost - scost
            trades.append(
                {
                    "symbol": sym,
                    "signal_close_ref": pos.signal_close,
                    "entry_date": str(pos.entry_date.date()),
                    "entry_price": round(pos.entry_price, 4),
                    "quantity": pos.quantity,
                    "initial_stop": round(pos.stop_price, 4),
                    "exit_date": str(dt.date()),
                    "exit_price": round(fill, 4),
                    "exit_reason": reason,
                    "gross_pnl": round(gross, 2),
                    "net_pnl": round(net, 2),
                    "buy_cost": round(pos.buy_cost, 2),
                    "sell_cost": round(scost, 2),
                    "holding_days": pos.holding_days,
                    "r_multiple": round(net / max(pos.quantity * pos.initial_r, 1e-9), 4),
                    "score": pos.score,
                    "label": label,
                }
            )

        # 2) pending APPROX entries from prior signal day
        still_pending = []
        equity_now = cash + sum(
            positions[s].quantity
            * (
                float(by_date_sym[(dt, s)].close)
                if (dt, s) in by_date_sym
                else positions[s].entry_price
            )
            for s in positions
        )
        # use open for exposure estimate for entries
        cur_exp = 0.0
        for s, pos in positions.items():
            row = by_date_sym.get((dt, s))
            px = float(row.open) if row is not None else pos.entry_price
            cur_exp += pos.quantity * px

        for pe in pending_entries:
            sym = pe["symbol"]
            if sym in positions:
                continue
            if len(positions) >= max_positions:
                still_pending.append(pe)  # drop? actually expire — only valid for this open
                continue
            row = by_date_sym.get((dt, sym))
            if row is None:
                continue
            # only fill on the intended entry date (= next day after signal)
            if dt != pe["entry_date"]:
                # expired / mismatch
                continue
            signal_close = pe["signal_close"]
            open_px = float(row.open)
            gap = open_px / signal_close - 1.0
            if not (e_cfg["open_gap_min"] <= gap <= e_cfg["open_gap_max"]):
                continue
            fill = open_px * (1 + slip)
            if fill > signal_close * (1 + e_cfg["max_price_above_signal_close"]):
                continue
            # stop distance at fill
            structure_distance = max((fill - pe["structure_low10"]) / fill, 0.0)
            atr_distance = cfg["risk"]["atr_multiple"] * pe["atr20"] / fill
            stop_distance = max(structure_distance, atr_distance, cfg["risk"]["min_stop_distance"])
            qty, stop_price, planned_risk = size_qty(
                entry_price=fill,
                stop_distance=stop_distance,
                equity=equity_now,
                cash=cash,
                cfg=cfg,
                risk_fraction=risk_fraction,
                max_single_exposure=max_single_exposure,
                max_total_exposure=max_total_exposure,
                current_exposure=cur_exp,
            )
            if qty < 100:
                continue
            buy_val = qty * fill
            bcost = buy_cost(buy_val, cfg)
            if buy_val + bcost > cash:
                continue
            cash -= buy_val + bcost
            cur_exp += buy_val
            positions[sym] = Position(
                symbol=sym,
                entry_date=dt,
                entry_price=fill,
                quantity=qty,
                stop_price=stop_price,
                initial_r=fill - stop_price,
                signal_close=signal_close,
                atr20_at_entry=pe["atr20"],
                structure_low10=pe["structure_low10"],
                buy_cost=bcost,
                effective_stop=stop_price,
                highest_close=fill,
                holding_days=0,
                score=pe["score"],
            )
        pending_entries = []  # all candidates were for this open only

        # --- CLOSE: update stops / holding / schedule exits; collect new signals ---
        for sym, pos in list(positions.items()):
            row = by_date_sym.get((dt, sym))
            if row is None:
                continue
            if pd.Timestamp(pos.entry_date).normalize() == dt:
                # entry day: track high/low but no sell / no holding day count for exits yet
                pos.highest_close = max(pos.highest_close, float(row.close))
                continue
            pos.holding_days += 1
            pos.highest_close = max(pos.highest_close, float(row.close))
            close_px = float(row.close)
            close_r = (close_px - pos.entry_price) / max(pos.initial_r, 1e-9)
            # trailing / breakeven (effective next day)
            if close_r >= cfg["exit"]["trailing_at_r"]:
                ma10 = float(row.ma10) if hasattr(row, "ma10") and pd.notna(row.ma10) else np.nan
                atr20 = float(row.atr20) if hasattr(row, "atr20") and pd.notna(row.atr20) else pos.atr20_at_entry
                trailing = max(
                    ma10 if np.isfinite(ma10) else -np.inf,
                    pos.highest_close - cfg["exit"]["trailing_atr_multiple"] * atr20,
                )
                if np.isfinite(trailing):
                    pos.effective_stop = max(pos.effective_stop, trailing)
            elif close_r >= cfg["exit"]["breakeven_at_r"]:
                round_trip = (
                    buy_cost(pos.quantity * pos.entry_price, cfg)
                    + sell_cost(pos.quantity * pos.entry_price, cfg)
                ) / pos.quantity
                pos.effective_stop = max(pos.effective_stop, pos.entry_price + round_trip)

            if pos.holding_days >= cfg["exit"]["max_holding_days"]:
                pos.pending_exit_reason = "max_holding"
            elif (
                pos.holding_days >= cfg["exit"]["time_stop_days"]
                and close_r < cfg["exit"]["time_stop_min_r"]
            ):
                pos.pending_exit_reason = "time_stop"

        # schedule new entries for next open if market gate & slots
        nd = next_date.get(dt)
        if nd is not None and len(positions) < max_positions:
            day_sigs = signals_by_date.get(dt)
            if day_sigs is not None and not day_sigs.empty:
                # market_gate already in signal
                slots = max_positions - len(positions)
                # also account for already pending — none at this point
                picked = 0
                for _, srow in day_sigs.iterrows():
                    if picked >= slots:
                        break
                    sym = str(srow["symbol"]).zfill(6)
                    if sym in positions:
                        continue
                    if any(p["symbol"] == sym for p in pending_entries):
                        continue
                    # need atr / structure
                    if not np.isfinite(srow.get("atr20", np.nan)) or not np.isfinite(
                        srow.get("structure_low10", np.nan)
                    ):
                        continue
                    pending_entries.append(
                        {
                            "symbol": sym,
                            "entry_date": nd,
                            "signal_date": dt,
                            "signal_close": float(srow["close"]),
                            "signal_high": float(srow["high"]),
                            "atr20": float(srow["atr20"]),
                            "structure_low10": float(srow["structure_low10"]),
                            "score": float(srow["score"]) if pd.notna(srow["score"]) else 0.0,
                        }
                    )
                    picked += 1

        eq = mtm_equity(dt)
        nav_rows.append(
            {
                "date": str(dt.date()),
                "equity": round(eq, 2),
                "cash": round(cash, 2),
                "n_positions": len(positions),
                "exposure": round(exposure_value(dt), 2),
            }
        )

    # force close remaining at last close
    if dates:
        last = dates[-1]
        for sym, pos in list(positions.items()):
            row = by_date_sym.get((last, sym))
            fill = float(row.close) * (1 - slip) if row is not None else pos.entry_price * (1 - slip)
            sell_val = pos.quantity * fill
            scost = sell_cost(sell_val, cfg)
            cash += sell_val - scost
            buy_val = pos.quantity * pos.entry_price
            gross = sell_val - buy_val
            net = gross - pos.buy_cost - scost
            trades.append(
                {
                    "symbol": sym,
                    "signal_close_ref": pos.signal_close,
                    "entry_date": str(pos.entry_date.date()),
                    "entry_price": round(pos.entry_price, 4),
                    "quantity": pos.quantity,
                    "initial_stop": round(pos.stop_price, 4),
                    "exit_date": str(last.date()),
                    "exit_price": round(fill, 4),
                    "exit_reason": "data_end",
                    "gross_pnl": round(gross, 2),
                    "net_pnl": round(net, 2),
                    "buy_cost": round(pos.buy_cost, 2),
                    "sell_cost": round(scost, 2),
                    "holding_days": pos.holding_days,
                    "r_multiple": round(net / max(pos.quantity * pos.initial_r, 1e-9), 4),
                    "score": pos.score,
                    "label": label,
                }
            )
        positions.clear()
        if nav_rows:
            nav_rows[-1]["equity"] = round(cash, 2)
            nav_rows[-1]["cash"] = round(cash, 2)
            nav_rows[-1]["n_positions"] = 0
            nav_rows[-1]["exposure"] = 0.0

    nav = pd.DataFrame(nav_rows)
    trades_df = pd.DataFrame(trades)
    metrics = compute_metrics(nav, trades_df, capital=capital, label=label)
    return BacktestResult(label=label, nav=nav, trades=trades_df, metrics=metrics, notes=notes)


def compute_metrics(nav: pd.DataFrame, trades: pd.DataFrame, capital: float, label: str) -> dict:
    if nav.empty:
        return {
            "label": label,
            "error": "empty_nav",
            "initial_capital": capital,
            "final_equity": None,
            "total_return": None,
            "n_trades": 0,
        }
    nav = nav.copy()
    nav["date"] = pd.to_datetime(nav["date"])
    eq0 = float(nav.iloc[0]["equity"])
    eq1 = float(nav.iloc[-1]["equity"])
    # use capital as start
    total_return = eq1 / capital - 1.0
    days = (nav["date"].iloc[-1] - nav["date"].iloc[0]).days
    years = max(days / 365.25, 1e-9)
    cagr = (eq1 / capital) ** (1 / years) - 1.0 if eq1 > 0 else float("nan")
    # max dd
    peak = nav["equity"].cummax()
    dd = nav["equity"] / peak - 1.0
    max_dd = float(dd.min()) if len(dd) else None
    # yearly returns
    nav["year"] = nav["date"].dt.year
    yearly = {}
    for y, g in nav.groupby("year"):
        yearly[str(y)] = round(float(g.iloc[-1]["equity"] / g.iloc[0]["equity"] - 1.0), 6)

    n_trades = int(len(trades)) if trades is not None and not trades.empty else 0
    win_rate = None
    avg_net = None
    if n_trades > 0:
        win_rate = float((trades["net_pnl"] > 0).mean())
        avg_net = float(trades["net_pnl"].mean())

    return {
        "label": label,
        "entry_mode": ENTRY_MODE,
        "status": "NOT_VALIDATED",
        "universe_tag": "UNIVERSE_REDUCED",
        "initial_capital": capital,
        "final_equity": round(eq1, 2),
        "total_return": round(total_return, 6),
        "total_return_pct": round(total_return * 100, 4),
        "CAGR": round(cagr, 6) if np.isfinite(cagr) else None,
        "CAGR_pct": round(cagr * 100, 4) if np.isfinite(cagr) else None,
        "MaxDD": round(max_dd, 6) if max_dd is not None else None,
        "MaxDD_pct": round(max_dd * 100, 4) if max_dd is not None else None,
        "n_trades": n_trades,
        "win_rate": round(win_rate, 4) if win_rate is not None else None,
        "avg_net_pnl": round(avg_net, 2) if avg_net is not None else None,
        "start_date": str(nav["date"].iloc[0].date()),
        "end_date": str(nav["date"].iloc[-1].date()),
        "n_nav_days": int(len(nav)),
        "yearly_returns": yearly,
        "first_nav_equity": round(eq0, 2),
    }


def write_summary(
    path: Path,
    *,
    meta: dict,
    metrics_a: dict,
    metrics_b: Optional[dict],
    diffs: list[str],
    failures: list[str],
) -> None:
    lines = []
    lines.append("# S1.1 研究级公开行情近似回测 SUMMARY")
    lines.append("")
    lines.append("> ## **NOT_VALIDATED** · **APPROX_NEXT_OPEN** · **UNIVERSE_REDUCED** · **非冻结分钟入场**")
    lines.append(">")
    lines.append("> 本报告**不是**冻结 S1.1 分钟确认回测验收。公开分钟历史不可靠，默认「信号日收盘候选 → 次日开盘成交」，")
    lines.append("> 并检查开盘相对信号收盘约 -1.5%~+3% 与成交价 ≤104%×signal_close。**禁止**将其解读为已完成 09:45–10:30 分时确认。")
    lines.append("")
    lines.append(f"- 生成时间（Asia/Seoul）: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} KST")
    lines.append(f"- 本金: {CAPITAL:,.0f} CNY")
    lines.append(f"- 入场模式: `{ENTRY_MODE}`")
    lines.append(f"- 数据源: 腾讯日K前复权（`paper/data_feed.py`），缓存 `paper/data/research_*.parquet`（不提交）")
    lines.append(f"- 宇宙: {meta.get('n_ok')}/{meta.get('n_symbols_requested')} 只主板缩减池；tag=`UNIVERSE_REDUCED`")
    lines.append(f"- 区间: {meta.get('panel_start')} → {meta.get('panel_end')}")
    lines.append(f"- 基准: 中证500 (000905) 市场开关 close>MA20 且 MA20>MA60")
    lines.append("")
    lines.append("## 与冻结 S1.1 差异清单")
    for d in diffs:
        lines.append(f"- {d}")
    lines.append("")
    lines.append("## A / B 关键指标")
    lines.append("")
    lines.append("| 版本 | 期末权益 | 总收益 | CAGR | MaxDD | 交易笔数 |")
    lines.append("|---|---:|---:|---:|---:|---:|")

    def row(m: Optional[dict], name: str) -> str:
        if not m or m.get("final_equity") is None:
            return f"| {name} | N/A | N/A | N/A | N/A | N/A |"
        return (
            f"| {name} | {m['final_equity']:,.2f} | {m.get('total_return_pct')}% "
            f"| {m.get('CAGR_pct')}% | {m.get('MaxDD_pct')}% | {m.get('n_trades')} |"
        )

    lines.append(row(metrics_a, "A U0"))
    lines.append(row(metrics_b, "B 决策官硬闸门"))
    lines.append("")
    lines.append("### A 版细节（策略层 U0）")
    lines.append("```json")
    lines.append(json.dumps(metrics_a, ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    if metrics_b:
        lines.append("### B 版细节（叠决策官硬闸门）")
        lines.append("```json")
        lines.append(json.dumps(metrics_b, ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
        lines.append(
            "- B 闸门：单票市值≤20%；单笔风险≤预算1%（1000元/@10万）；总仓≤70%；"
            "**申万一级行业≤35%：无公开申万行业历史映射，本回测无法执行该条并已跳过（INDUSTRY_GATE_SKIPPED）。**"
        )
    lines.append("")
    lines.append("## 日线退出简化点")
    lines.append("- 止损：开盘跌破则开盘价滑点卖出；日内低点触及则按止损价滑点卖出（无分钟路径）")
    lines.append("- +1R 保本 / +2R 跟踪：按收盘判定，下一交易日生效")
    lines.append("- 8日时间退出 / 20日强制：收盘触发，次日开盘卖出")
    lines.append("- T+1：买入当日不可卖")
    lines.append("- 成本：佣金万2最低5、卖出印花税0.05%、过户双边0.001%、滑点单边0.1%")
    lines.append("")
    lines.append("## 失败 / 缺口")
    if failures:
        for f in failures:
            lines.append(f"- {f}")
    else:
        lines.append("- （无致命失败）")
    if meta.get("errors"):
        lines.append(f"- 拉数失败/过短标的数: {len(meta['errors'])}")
        for e in meta["errors"][:30]:
            lines.append(f"  - {e}")
    lines.append("")
    lines.append("## 输出文件")
    lines.append("- `SUMMARY.md`（本文件）")
    lines.append("- `metrics_A.json` / `metrics_B.json`")
    lines.append("- `nav_A.csv` / `nav_B.csv`")
    lines.append("- `trades_A.csv` / `trades_B.csv`")
    lines.append("- `run_meta.json`")
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    cfg = load_config(ROOT / "config" / "s1_config.json")
    # research capital override note — sizing uses runtime equity; initial = CAPITAL
    failures: list[str] = []
    diffs = [
        "入场：冻结为 09:45–10:30 分钟确认后下一分钟开盘；本回测为 APPROX_NEXT_OPEN（次日开盘+缺口检查），**未做分时确认**",
        "宇宙：公开数据缩减高流动性主板池，非全市场扫描（UNIVERSE_REDUCED）",
        "listing_days：样本起点前已上市标的用「样本内交易日+120」近似，可能低估真实上市天数过滤误差",
        "ST/停牌：无完整历史状态字段；paused≈成交量/额为0；ST 仅在选池时按现货名称排除（历史 ST 变迁未还原）",
        "成交额：腾讯 volume 按「手」×close×100 近似，流动性过滤为近似",
        "一字涨停：用 close≥prev_close×1.095 近似排除，非交易所涨停标记",
        "本金：研究用 100,000 CNY（config 历史参考权益不同）",
        "行业约束（B）：无申万行业历史，跳过",
        "状态：NOT_VALIDATED — 不得当作实盘/纸面验收通过证据",
    ]

    print("Building universe...")
    symbols, tag, uni_meta = build_universe(max_names=80)
    print(f"Universe {tag}: {len(symbols)} symbols", flush=True)

    print("Fetching bars...")
    try:
        panel, bench, info = load_panel(symbols)
    except Exception as exc:  # noqa: BLE001
        failures.append(f"load_panel fatal: {exc}")
        traceback.print_exc()
        write_summary(
            OUT_DIR / "SUMMARY.md",
            meta={**uni_meta, "errors": [str(exc)]},
            metrics_a={"label": "A", "error": str(exc), "final_equity": None, "n_trades": 0},
            metrics_b=None,
            diffs=diffs,
            failures=failures,
        )
        return 1

    meta = {**uni_meta, **info}
    print(f"Panel {meta['panel_start']} → {meta['panel_end']} n_ok={meta['n_ok']}")

    # Restrict feature window: need warmup before 2019 for MA60 — keep from 2018 data in fetch
    print("Preparing features...")
    feat = prepare_features(panel, bench, cfg)
    # backtest nav from first date >= 2019-01-01 where we have features
    feat = feat[feat["date"] >= pd.Timestamp("2019-01-01")].copy()
    n_sig = int(feat["signal"].sum())
    print(f"Signal rows in sample: {n_sig}")
    meta["n_signal_rows"] = n_sig

    print("Running A (U0)...")
    res_a = run_portfolio(
        feat,
        cfg,
        label="A_U0",
        risk_fraction=0.0125,
        max_single_exposure=0.35,
        max_total_exposure=0.70,
        max_positions=3,
        capital=CAPITAL,
    )
    print("A metrics:", json.dumps({k: res_a.metrics[k] for k in ("final_equity", "total_return_pct", "CAGR_pct", "MaxDD_pct", "n_trades")}, ensure_ascii=False))

    print("Running B (decision gates)...")
    res_b = run_portfolio(
        feat,
        cfg,
        label="B_DECISION_GATES",
        risk_fraction=0.01,  # ≤1000 CNY on 100k
        max_single_exposure=0.20,
        max_total_exposure=0.70,
        max_positions=3,
        capital=CAPITAL,
    )
    res_b.notes.append("INDUSTRY_GATE_SKIPPED: no SW industry history")
    print("B metrics:", json.dumps({k: res_b.metrics[k] for k in ("final_equity", "total_return_pct", "CAGR_pct", "MaxDD_pct", "n_trades")}, ensure_ascii=False))

    # write outputs
    (OUT_DIR / "metrics_A.json").write_text(
        json.dumps({**res_a.metrics, "notes": res_a.notes, "warnings": ["NOT_VALIDATED", "APPROX_NEXT_OPEN", "UNIVERSE_REDUCED"]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUT_DIR / "metrics_B.json").write_text(
        json.dumps({**res_b.metrics, "notes": res_b.notes, "warnings": ["NOT_VALIDATED", "APPROX_NEXT_OPEN", "UNIVERSE_REDUCED", "INDUSTRY_GATE_SKIPPED"]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    res_a.nav[["date", "equity"]].to_csv(OUT_DIR / "nav_A.csv", index=False)
    res_b.nav[["date", "equity"]].to_csv(OUT_DIR / "nav_B.csv", index=False)
    if not res_a.trades.empty:
        ta = res_a.trades.copy()
        ta["symbol"] = ta["symbol"].astype(str).str.zfill(6)
        ta.to_csv(OUT_DIR / "trades_A.csv", index=False)
    else:
        failures.append("A: zero trades")
        (OUT_DIR / "trades_A.csv").write_text("symbol,entry_date,exit_date,net_pnl\n", encoding="utf-8")
    if not res_b.trades.empty:
        tb = res_b.trades.copy()
        tb["symbol"] = tb["symbol"].astype(str).str.zfill(6)
        tb.to_csv(OUT_DIR / "trades_B.csv", index=False)
    else:
        failures.append("B: zero trades")
        (OUT_DIR / "trades_B.csv").write_text("symbol,entry_date,exit_date,net_pnl\n", encoding="utf-8")

    meta_out = {
        "generated_at_kst": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "entry_mode": ENTRY_MODE,
        "warnings": ["NOT_VALIDATED", "APPROX_NEXT_OPEN", "UNIVERSE_REDUCED", "非冻结分钟入场"],
        "capital": CAPITAL,
        "data": meta,
        "diffs_vs_frozen_s1": diffs,
        "failures": failures,
    }
    (OUT_DIR / "run_meta.json").write_text(json.dumps(meta_out, ensure_ascii=False, indent=2), encoding="utf-8")

    write_summary(
        OUT_DIR / "SUMMARY.md",
        meta=meta,
        metrics_a=res_a.metrics,
        metrics_b=res_b.metrics,
        diffs=diffs,
        failures=failures,
    )
    print("Wrote outputs to", OUT_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
