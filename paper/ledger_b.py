"""账本 B：中证500 市场开关 + 缩减宇宙 S1 日线候选扫描（UNIVERSE_REDUCED）。"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from broker import (
    PAPER_DIR,
    LOT,
    MIN_NOTIONAL,
    load_account,
    load_costs,
    load_risk,
    mark_to_market,
    nav_row_from_account,
    record_fill,
    round_lot,
    save_account,
    upsert_nav,
    compute_costs,
)
from data_feed import (
    build_reduced_universe,
    fetch_universe_bars,
    latest_close,
    load_or_fetch_bars,
    market_gate_csi500,
)

ACCOUNT_B = PAPER_DIR / "accounts" / "B_s1.json"
LEDGER_B = PAPER_DIR / "ledger_B.csv"
NAV_B = PAPER_DIR / "nav_B.csv"
ROOT = PAPER_DIR.parent
S1_CONFIG = ROOT / "config" / "s1_config.json"


def _load_s1_signal_cfg() -> dict[str, Any]:
    cfg = json.loads(S1_CONFIG.read_text(encoding="utf-8")) if S1_CONFIG.exists() else {}
    return cfg


def _features(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("date").copy()
    prev_close = g["close"].shift(1)
    tr = pd.concat(
        [
            g["high"] - g["low"],
            (g["high"] - prev_close).abs(),
            (g["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    g["ma20"] = g["close"].rolling(20, min_periods=20).mean()
    g["ma60"] = g["close"].rolling(60, min_periods=60).mean()
    g["ma20_prev"] = g["ma20"].shift(5)
    g["prior_high_close20"] = g["close"].shift(1).rolling(20, min_periods=20).max()
    g["prior_volume20"] = g["volume"].shift(1).rolling(20, min_periods=20).mean()
    g["avg_amount20"] = g["amount"].shift(1).rolling(20, min_periods=20).mean()
    g["structure_low10"] = g["low"].shift(1).rolling(10, min_periods=10).min()
    g["prior_high10"] = g["high"].shift(1).rolling(10, min_periods=10).max()
    g["atr20"] = tr.rolling(20, min_periods=20).mean()
    g["ret20"] = g["close"] / g["close"].shift(20) - 1
    g["ret60"] = g["close"] / g["close"].shift(60) - 1
    g["volume_ratio"] = g["volume"] / g["prior_volume20"]
    g["close_location"] = np.where(
        g["high"] > g["low"],
        (g["close"] - g["low"]) / (g["high"] - g["low"]),
        np.nan,
    )
    g["compression10"] = g["prior_high10"] / g["structure_low10"] - 1
    g["atr_fraction"] = g["atr20"] / g["close"]
    g["ma20_slope"] = g["ma20"] / g["ma20_prev"] - 1
    g["listing_days"] = np.arange(1, len(g) + 1)
    return g


def scan_candidates(
    asof: Optional[str] = None,
    max_names: int = 40,
) -> dict[str, Any]:
    """日线近似 S1 §2；标注 UNIVERSE_REDUCED。分时入场规则延后说明见 deferred_rules。"""
    out: dict[str, Any] = {
        "tag": "UNIVERSE_REDUCED",
        "asof": asof,
        "gate": {},
        "universe_source": "",
        "universe_size": 0,
        "candidates": [],
        "errors": [],
        "deferred_rules": [
            "T+1 09:45-10:30 分时首次站上 T 日最高且高于当日 VWAP：公开日线不可复现，默认只出卡片",
            "下一分钟开盘成交 / 禁止同K线最优价：延后",
            "开盘涨跌幅 -1.5%~+3% 过滤：仅在 --auto-paper-fill 用次日开盘近似时部分检查",
            "一字涨停与次日不可成交状态：数据不足时跳过",
        ],
        "messages": [],
    }
    gate = market_gate_csi500(asof=asof)
    out["gate"] = gate
    if not gate.get("ok"):
        out["messages"].append(gate.get("reason") or "市场开关数据失败")
        return out
    if not gate.get("gate_on"):
        out["universe_source"] = "skipped_gate_off|UNIVERSE_REDUCED"
        out["messages"].append("市场开关 OFF，不产生新买入候选（仍标注 UNIVERSE_REDUCED）")
        return out

    uni, uni_src = build_reduced_universe(max_names=max_names)
    out["universe_source"] = uni_src
    out["universe_size"] = len(uni)
    symbols = [u["symbol"] for u in uni]
    bars, fetch_errs = fetch_universe_bars(symbols, start_date="20250101")
    out["errors"].extend(fetch_errs)
    if bars.empty:
        out["messages"].append("缩减宇宙日线全部拉取失败")
        return out

    # 基准超额
    try:
        bdf, _ = load_or_fetch_bars("000905", start_date="20250101")
        b = bdf.copy()
        b["date"] = pd.to_datetime(b["date"])
        b = b.sort_values("date")
        b["benchmark_ret20"] = b["close"] / b["close"].shift(20) - 1
        b["benchmark_ret60"] = b["close"] / b["close"].shift(60) - 1
        bref = b[["date", "benchmark_ret20", "benchmark_ret60"]]
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"benchmark:{exc}")
        bref = None

    parts = []
    for sym, g in bars.groupby("symbol"):
        g = g.copy()
        g["date"] = pd.to_datetime(g["date"])
        if asof:
            g = g[g["date"] <= pd.Timestamp(asof)]
        if len(g) < 60:
            continue
        parts.append(_features(g))
    if not parts:
        out["messages"].append("无足够历史的标的可扫描")
        return out
    feat = pd.concat(parts, ignore_index=True)
    if bref is not None:
        feat = feat.merge(bref, on="date", how="left")
        feat["excess20"] = feat["ret20"] - feat["benchmark_ret20"]
        feat["excess60"] = feat["ret60"] - feat["benchmark_ret60"]
    else:
        feat["excess20"] = feat["ret20"]
        feat["excess60"] = feat["ret60"]

    # 取 asof 当日截面
    if asof:
        day = feat[feat["date"] == pd.Timestamp(asof)]
        if day.empty:
            day = feat[feat["date"] == feat["date"].max()]
    else:
        day = feat[feat["date"] == feat["date"].max()]
    signal_date = str(pd.Timestamp(day["date"].iloc[0]).date())
    out["signal_date"] = signal_date

    # 流动性与上市过滤（amount 为近似值；标注）
    eligible = day[
        (day["listing_days"] >= 120)
        & (day["avg_amount20"].fillna(0) >= 50_000_000)
        & day["ma20"].notna()
        & day["ma60"].notna()
    ].copy()
    if eligible.empty:
        # 放宽：若 amount 单位可疑，退回仅用 listing+均线，并注明
        eligible = day[(day["listing_days"] >= 60) & day["ma20"].notna()].copy()
        out["messages"].append(
            "流动性阈值在缩减数据上过严或 amount 单位不确定，已部分放宽并保持 UNIVERSE_REDUCED"
        )
    if eligible.empty:
        out["messages"].append("截面无合格标的")
        return out

    for col, ascending in [
        ("excess20", True),
        ("excess60", True),
        ("volume_ratio", True),
        ("ma20_slope", True),
        ("atr_fraction", True),
    ]:
        eligible[f"{col}_pct"] = eligible[col].rank(pct=True, ascending=ascending)

    eligible["score"] = (
        35 * eligible["excess20_pct"]
        + 20 * eligible["excess60_pct"]
        + 20 * eligible["volume_ratio_pct"]
        + 15 * eligible["ma20_slope_pct"]
        + 10 * (1 - eligible["atr_fraction_pct"])
    )
    rs_cut = 1 - 0.35
    mask = (
        (eligible["close"] > eligible["ma20"])
        & (eligible["ma20"] > eligible["ma60"])
        & (eligible["ma20"] > eligible["ma20_prev"])
        & (eligible["excess20_pct"] >= rs_cut)
        & (eligible["close"] > eligible["prior_high_close20"])
        & eligible["volume_ratio"].between(1.3, 3.0, inclusive="both")
        & (eligible["close_location"] >= 0.65)
        & (eligible["compression10"] <= 0.15)
    )
    cands = eligible.loc[mask].sort_values("score", ascending=False)
    cards = []
    for _, r in cands.iterrows():
        atr = float(r["atr20"]) if pd.notna(r["atr20"]) else float("nan")
        structure = float(r["structure_low10"]) if pd.notna(r["structure_low10"]) else float("nan")
        close = float(r["close"])
        # 预估止损距离（按冻结规格思路，入场价暂用收盘近似）
        structure_dist = max((close - structure) / close, 0) if structure == structure else 0
        atr_dist = 1.6 * atr / close if atr == atr and close else 0
        stop_dist = max(structure_dist, atr_dist, 0.03)
        card = {
            "symbol": str(r["symbol"]),
            "signal_date": signal_date,
            "close": close,
            "high": float(r["high"]),
            "score": round(float(r["score"]), 4),
            "volume_ratio": round(float(r["volume_ratio"]), 4) if pd.notna(r["volume_ratio"]) else None,
            "excess20": round(float(r["excess20"]), 4) if pd.notna(r["excess20"]) else None,
            "stop_distance_est": round(float(stop_dist), 4),
            "abandon_if_stop_gt_6pct": bool(stop_dist > 0.06),
            "entry_mode": "CARD_ONLY_DEFAULT",
            "approx_next_open_fill": "仅当 --auto-paper-fill：用次日开盘价近似，并检查相对信号收盘涨跌幅约 -1.5%~+3% 与 ≤104%*signal_close",
            "tag": "UNIVERSE_REDUCED",
        }
        cards.append(card)
    out["candidates"] = cards
    out["messages"].append(f"扫描完成 candidates={len(cards)} universe={out['universe_size']}")
    return out


def size_u0(entry_price: float, stop_price: float, equity: float, cash: float, n_pos: int, exposure: float) -> Optional[dict[str, Any]]:
    risk = load_risk()
    costs = load_costs()
    if n_pos >= int(risk.get("max_positions", 3)):
        return None
    if entry_price <= 0 or stop_price <= 0 or stop_price >= entry_price:
        return None
    stop_distance = (entry_price - stop_price) / entry_price
    if stop_distance > float(risk.get("max_stop_distance", 0.06)):
        return None
    per_share = entry_price - stop_price
    risk_budget = equity * float(risk.get("risk_fraction_unvalidated", 0.0125))
    max_total = float(risk.get("max_total_exposure_unvalidated", 0.70))
    max_single = float(risk.get("max_single_exposure_unvalidated", 0.35))
    remaining = max(0.0, equity * max_total - exposure)
    gap_qty = round_lot(equity * float(risk.get("max_gap_loss_fraction", 0.02)) / (entry_price * float(risk.get("gap_stress_fraction", 0.08))))
    single_qty = round_lot(equity * max_single / entry_price)
    cash_qty = round_lot(cash / entry_price)
    exposure_qty = round_lot(remaining / entry_price)
    max_qty = min(gap_qty, single_qty, cash_qty, exposure_qty)
    qty = 0
    for candidate in range(max_qty, LOT - 1, -LOT):
        entry_value = candidate * entry_price
        stop_value = candidate * stop_price
        b = compute_costs(entry_value, "buy", costs, is_etf=False)
        s = compute_costs(stop_value, "sell", costs, is_etf=False)
        total_risk = candidate * per_share + b.total_fees + s.total_fees + s.slippage_cost
        cash_needed = entry_value + b.total_fees + b.slippage_cost
        if total_risk <= risk_budget and cash_needed <= cash + 1e-6:
            qty = candidate
            break
    if qty < LOT or qty * entry_price < MIN_NOTIONAL:
        return None
    return {"quantity": qty, "stop_distance": stop_distance, "stop_price": stop_price}


def maybe_auto_fill(
    scan: dict[str, Any],
    asof: Optional[str] = None,
) -> dict[str, Any]:
    """仅 --auto-paper-fill：对未放弃的候选用次日开盘近似成交。"""
    result = {"filled": [], "skipped": [], "tag": "UNIVERSE_REDUCED"}
    if not scan.get("gate", {}).get("gate_on"):
        result["skipped"].append("gate_off")
        return result
    account = load_account(ACCOUNT_B)
    for card in scan.get("candidates") or []:
        if card.get("abandon_if_stop_gt_6pct"):
            result["skipped"].append({card["symbol"]: "stop>6%"})
            continue
        sym = card["symbol"]
        try:
            df, _ = load_or_fetch_bars(sym, start_date="20250101")
            d = df.copy()
            d["date"] = pd.to_datetime(d["date"])
            sig_dt = pd.Timestamp(card["signal_date"])
            nxt = d[d["date"] > sig_dt].sort_values("date")
            if nxt.empty:
                result["skipped"].append({sym: "无次日K线"})
                continue
            row = nxt.iloc[0]
            open_px = float(row["open"])
            signal_close = float(card["close"])
            gap = open_px / signal_close - 1
            if not (-0.015 <= gap <= 0.03):
                result["skipped"].append({sym: f"开盘涨跌幅超限 gap={gap:.4f}"})
                continue
            if open_px > signal_close * 1.04:
                result["skipped"].append({sym: "超过信号收盘104%"})
                continue
            stop_dist = float(card["stop_distance_est"])
            stop_price = open_px * (1 - stop_dist)
            account = mark_to_market(account)
            plan = size_u0(
                open_px,
                stop_price,
                float(account["equity"]),
                float(account["cash"]),
                len(account.get("positions") or []),
                float(account.get("positions_mv") or 0),
            )
            if not plan:
                result["skipped"].append({sym: "定仓失败/风控"})
                continue
            fill = record_fill(
                account,
                symbol=sym,
                side="buy",
                qty=int(plan["quantity"]),
                raw_price=open_px,
                ledger_path=LEDGER_B,
                account_path=ACCOUNT_B,
                book="B_s1",
                note=f"auto-paper-fill next-open approx; signal={card['signal_date']}; UNIVERSE_REDUCED",
            )
            account = fill["account"]
            result["filled"].append(
                {"symbol": sym, "qty": plan["quantity"], "fill_price": fill["fill_price"], "trade_id": fill["trade_id"]}
            )
        except Exception as exc:  # noqa: BLE001
            result["skipped"].append({sym: str(exc)})
    return result


def daily_mtm(asof: Optional[str] = None, note: str = "") -> dict[str, Any]:
    account = load_account(ACCOUNT_B)
    marks: dict[str, float] = {}
    errors: list[str] = []
    px_date = asof or ""
    for pos in account.get("positions") or []:
        sym = pos["symbol"]
        try:
            df, _ = load_or_fetch_bars(sym, start_date="20250101")
            dt, px = latest_close(df, asof=asof)
            marks[sym] = px
            px_date = str(dt.date())
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{sym}:{exc}")
    account = mark_to_market(account, marks)
    save_account(account, ACCOUNT_B)
    trade_date = asof or px_date
    if trade_date:
        upsert_nav(
            NAV_B,
            nav_row_from_account(
                account,
                trade_date,
                note=(note or "MTM") + (" | " + ";".join(errors) if errors else ""),
            ),
        )
    return {"account": account, "marks": marks, "errors": errors, "price_date": px_date}
