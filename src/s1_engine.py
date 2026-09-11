from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REQUIRED_DAILY = {
    "date", "symbol", "open", "high", "low", "close",
    "volume", "amount", "paused", "st", "listing_days",
}
REQUIRED_INTRADAY = {
    "datetime", "symbol", "open", "high", "low", "close", "volume", "amount",
}


@dataclass(frozen=True)
class Entry:
    symbol: str
    signal_date: pd.Timestamp
    entry_datetime: pd.Timestamp
    entry_price: float
    signal_close: float
    signal_high: float
    atr20: float
    structure_low10: float
    score: float


@dataclass(frozen=True)
class PositionPlan:
    quantity: int
    entry_price: float
    stop_price: float
    stop_distance: float
    normal_risk_amount: float
    gap_stress_amount: float
    estimated_entry_cost: float


@dataclass(frozen=True)
class TradeResult:
    symbol: str
    signal_date: str
    entry_datetime: str
    entry_price: float
    quantity: int
    initial_stop: float
    exit_date: str
    exit_price: float
    exit_reason: str
    gross_pnl: float
    net_pnl: float
    return_pct: float
    r_multiple: float
    mae_pct: float
    mfe_pct: float
    holding_days: int
    buy_cost: float
    sell_cost: float


def load_config(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _boolify(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series
    return series.astype(str).str.lower().isin({"1", "true", "yes", "y"})


def validate_daily(df: pd.DataFrame) -> None:
    missing = REQUIRED_DAILY - set(df.columns)
    if missing:
        raise ValueError(f"daily data missing columns: {sorted(missing)}")
    if df.duplicated(["date", "symbol"]).any():
        raise ValueError("daily data contains duplicate date/symbol rows")
    if (df[["open", "high", "low", "close", "volume", "amount"]] < 0).any().any():
        raise ValueError("daily price/volume fields must be non-negative")


def validate_intraday(df: pd.DataFrame) -> None:
    missing = REQUIRED_INTRADAY - set(df.columns)
    if missing:
        raise ValueError(f"intraday data missing columns: {sorted(missing)}")
    if df.duplicated(["datetime", "symbol"]).any():
        raise ValueError("intraday data contains duplicate datetime/symbol rows")


def buy_cost(value: float, cfg: dict[str, Any], stress: float = 1.0) -> float:
    c = cfg["costs"]
    commission = max(value * c["commission_rate"], c["minimum_commission"])
    transfer = value * c["transfer_fee_each_side"]
    return stress * (commission + transfer)


def sell_cost(value: float, cfg: dict[str, Any], stress: float = 1.0) -> float:
    c = cfg["costs"]
    commission = max(value * c["commission_rate"], c["minimum_commission"])
    transfer = value * c["transfer_fee_each_side"]
    stamp = value * c["stamp_tax_sell"]
    return stress * (commission + transfer + stamp)


def _features_one_symbol(g: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    s = cfg["signal"]
    r = cfg["risk"]
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

    g["ma20"] = g["close"].rolling(s["ma_fast"], min_periods=s["ma_fast"]).mean()
    g["ma60"] = g["close"].rolling(s["ma_slow"], min_periods=s["ma_slow"]).mean()
    g["ma10"] = g["close"].rolling(10, min_periods=10).mean()
    g["ma20_prev"] = g["ma20"].shift(s["ma_slope_days"])
    g["prior_high_close20"] = (
        g["close"].shift(1).rolling(s["breakout_days"], min_periods=s["breakout_days"]).max()
    )
    g["prior_volume20"] = (
        g["volume"].shift(1).rolling(s["volume_lookback"], min_periods=s["volume_lookback"]).mean()
    )
    g["avg_amount20"] = g["amount"].shift(1).rolling(20, min_periods=20).mean()
    g["structure_low10"] = (
        g["low"].shift(1).rolling(s["compression_days"], min_periods=s["compression_days"]).min()
    )
    g["prior_high10"] = (
        g["high"].shift(1).rolling(s["compression_days"], min_periods=s["compression_days"]).max()
    )
    g["atr20"] = tr.rolling(r["atr_days"], min_periods=r["atr_days"]).mean()
    g["ret20"] = g["close"] / g["close"].shift(s["relative_strength_days"]) - 1
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
    return g


def prepare_daily_features(
    daily: pd.DataFrame,
    benchmark: pd.DataFrame,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    daily = daily.copy()
    benchmark = benchmark.copy()
    daily["date"] = pd.to_datetime(daily["date"]).dt.normalize()
    benchmark["date"] = pd.to_datetime(benchmark["date"]).dt.normalize()
    daily["paused"] = _boolify(daily["paused"])
    daily["st"] = _boolify(daily["st"])
    validate_daily(daily)

    parts = [_features_one_symbol(g, cfg) for _, g in daily.groupby("symbol", sort=False)]
    out = pd.concat(parts, ignore_index=True)

    b = benchmark.sort_values("date").copy()
    b["benchmark_ma20"] = b["close"].rolling(20, min_periods=20).mean()
    b["benchmark_ma60"] = b["close"].rolling(60, min_periods=60).mean()
    b["benchmark_ret20"] = b["close"] / b["close"].shift(20) - 1
    b["benchmark_ret60"] = b["close"] / b["close"].shift(60) - 1
    out = out.merge(
        b[["date", "close", "benchmark_ma20", "benchmark_ma60", "benchmark_ret20", "benchmark_ret60"]]
        .rename(columns={"close": "benchmark_close"}),
        on="date",
        how="left",
        validate="many_to_one",
    )
    out["excess20"] = out["ret20"] - out["benchmark_ret20"]
    out["excess60"] = out["ret60"] - out["benchmark_ret60"]
    u = cfg["universe"]
    excluded_prefixes = tuple(str(item) for item in u.get("excluded_symbol_prefixes", []))
    excluded_exchanges = tuple(str(item).upper() for item in u.get("excluded_exchanges", []))
    account_tradable = (
        ~out["symbol"].astype(str).str.startswith(excluded_prefixes)
        if excluded_prefixes
        else pd.Series(True, index=out.index)
    )
    if excluded_exchanges:
        account_tradable &= ~out["symbol"].astype(str).str.rsplit(".", n=1).str[-1].str.upper().isin(
            excluded_exchanges
        )
    base_eligible = (
        account_tradable
        & (~out["paused"])
        & (~out["st"])
        & (out["listing_days"] >= u["min_listing_days"])
        & (out["avg_amount20"] >= u["min_avg_turnover_20"])
    )

    for source, target, ascending in [
        ("excess20", "excess20_pct", True),
        ("excess60", "excess60_pct", True),
        ("volume_ratio", "volume_ratio_pct", True),
        ("ma20_slope", "ma20_slope_pct", True),
        ("atr_fraction", "atr_fraction_pct", True),
    ]:
        rank_source = out[source].where(base_eligible)
        out[target] = rank_source.groupby(out["date"]).rank(pct=True, ascending=ascending)

    out["score"] = (
        35 * out["excess20_pct"]
        + 20 * out["excess60_pct"]
        + 20 * out["volume_ratio_pct"]
        + 15 * out["ma20_slope_pct"]
        + 10 * (1 - out["atr_fraction_pct"])
    )

    s = cfg["signal"]
    rs_cutoff = 1 - s["relative_strength_top_fraction"]
    out["market_gate"] = (
        (out["benchmark_close"] > out["benchmark_ma20"])
        & (out["benchmark_ma20"] > out["benchmark_ma60"])
        & out["benchmark_ma20"].notna()
    )
    out["eligible"] = base_eligible
    out["signal"] = (
        out["eligible"]
        & out["market_gate"]
        & (out["close"] > out["ma20"])
        & (out["ma20"] > out["ma60"])
        & (out["ma20"] > out["ma20_prev"])
        & (out["excess20_pct"] >= rs_cutoff)
        & (out["close"] > out["prior_high_close20"])
        & out["volume_ratio"].between(s["volume_ratio_min"], s["volume_ratio_max"], inclusive="both")
        & (out["close_location"] >= s["close_location_min"])
        & (out["compression10"] <= s["compression_max"])
    )
    return out.sort_values(["date", "score"], ascending=[True, False]).reset_index(drop=True)


def find_entry(
    signal_row: pd.Series,
    intraday: pd.DataFrame,
    cfg: dict[str, Any],
) -> Entry | None:
    data = intraday.copy()
    data["datetime"] = pd.to_datetime(data["datetime"])
    validate_intraday(data)
    data = data[data["symbol"] == signal_row["symbol"]].sort_values("datetime")
    data = data[data["datetime"].dt.normalize() > pd.Timestamp(signal_row["date"]).normalize()]
    if data.empty:
        return None
    entry_date = data["datetime"].dt.normalize().min()
    data = data[data["datetime"].dt.normalize() == entry_date].copy()
    if data.empty:
        return None

    open_price = float(data.iloc[0]["open"])
    gap = open_price / float(signal_row["close"]) - 1
    e = cfg["entry"]
    if not (e["open_gap_min"] <= gap <= e["open_gap_max"]):
        return None

    data["cum_amount"] = data["amount"].cumsum()
    data["cum_volume"] = data["volume"].cumsum()
    data["vwap"] = data["cum_amount"] / data["cum_volume"].replace(0, np.nan)
    times = data["datetime"].dt.strftime("%H:%M")
    window = data[(times >= e["start_time"]) & (times <= e["end_time"])].copy()
    if window.empty:
        return None

    full_index = list(data.index)
    for idx, bar in window.iterrows():
        confirmed = bar["close"] > signal_row["high"] and bar["close"] > bar["vwap"]
        if not confirmed:
            continue
        pos = full_index.index(idx)
        if pos + 1 >= len(full_index):
            return None
        next_bar = data.loc[full_index[pos + 1]]
        raw_fill = float(next_bar["open"])
        fill = raw_fill * (1 + cfg["costs"]["slippage_each_side"])
        if fill > float(signal_row["close"]) * (1 + e["max_price_above_signal_close"]):
            return None
        return Entry(
            symbol=str(signal_row["symbol"]),
            signal_date=pd.Timestamp(signal_row["date"]),
            entry_datetime=pd.Timestamp(next_bar["datetime"]),
            entry_price=round(fill, 4),
            signal_close=float(signal_row["close"]),
            signal_high=float(signal_row["high"]),
            atr20=float(signal_row["atr20"]),
            structure_low10=float(signal_row["structure_low10"]),
            score=float(signal_row["score"]),
        )
    return None


def size_position(
    entry: Entry,
    equity: float,
    cash: float,
    cfg: dict[str, Any],
) -> PositionPlan | None:
    r = cfg["risk"]
    structure_distance = max((entry.entry_price - entry.structure_low10) / entry.entry_price, 0)
    atr_distance = r["atr_multiple"] * entry.atr20 / entry.entry_price
    stop_distance = max(structure_distance, atr_distance, r["min_stop_distance"])
    if not np.isfinite(stop_distance) or stop_distance > r["max_stop_distance"]:
        return None
    stop_price = entry.entry_price * (1 - stop_distance)
    per_share_risk = entry.entry_price - stop_price
    risk_budget = equity * r["risk_fraction_unvalidated"]
    gap_qty = math.floor(
        equity * r["max_gap_loss_fraction"]
        / (entry.entry_price * r["gap_stress_fraction"])
        / 100
    ) * 100
    single_qty = math.floor(
        equity * r["max_single_exposure_unvalidated"] / entry.entry_price / 100
    ) * 100
    cash_qty = math.floor(cash / entry.entry_price / 100) * 100
    max_qty = min(gap_qty, single_qty, cash_qty)
    qty = 0
    estimated_entry_cost = 0.0
    estimated_risk = 0.0
    for candidate in range(max_qty, 99, -100):
        entry_value = candidate * entry.entry_price
        stop_value = candidate * stop_price
        bcost = buy_cost(entry_value, cfg)
        scost = sell_cost(stop_value, cfg)
        stop_slippage = stop_value * cfg["costs"]["slippage_each_side"]
        total_risk = candidate * per_share_risk + bcost + scost + stop_slippage
        if total_risk <= risk_budget:
            qty = candidate
            estimated_entry_cost = bcost
            estimated_risk = total_risk
            break
    if qty < 100 or qty * entry.entry_price < 4000:
        return None
    return PositionPlan(
        quantity=qty,
        entry_price=entry.entry_price,
        stop_price=round(stop_price, 4),
        stop_distance=stop_distance,
        normal_risk_amount=estimated_risk,
        gap_stress_amount=qty * entry.entry_price * r["gap_stress_fraction"],
        estimated_entry_cost=estimated_entry_cost,
    )


def simulate_trade(
    entry: Entry,
    plan: PositionPlan,
    daily_symbol: pd.DataFrame,
    cfg: dict[str, Any],
) -> TradeResult | None:
    data = daily_symbol.copy()
    data["date"] = pd.to_datetime(data["date"]).dt.normalize()
    entry_date = entry.entry_datetime.normalize()
    data = data[data["date"] >= entry_date].sort_values("date").copy()
    if len(data) < 2:
        return None

    qty = plan.quantity
    initial_r = entry.entry_price - plan.stop_price
    effective_stop = plan.stop_price
    highest_close = entry.entry_price
    pending_reason: str | None = None
    exit_date = None
    exit_price = None
    exit_reason = None
    holding_days = 0

    lows = [entry.entry_price]
    highs = [entry.entry_price]
    for _, row in data.iterrows():
        date = pd.Timestamp(row["date"])
        if date == entry_date:
            lows.append(float(row["low"]))
            highs.append(float(row["high"]))
            continue
        holding_days += 1
        if pending_reason is not None:
            exit_date = date
            exit_price = float(row["open"]) * (1 - cfg["costs"]["slippage_each_side"])
            exit_reason = pending_reason
            break

        if float(row["open"]) <= effective_stop:
            exit_date = date
            exit_price = float(row["open"]) * (1 - cfg["costs"]["slippage_each_side"])
            exit_reason = "gap_or_open_stop"
            break
        if float(row["low"]) <= effective_stop:
            exit_date = date
            exit_price = effective_stop * (1 - cfg["costs"]["slippage_each_side"])
            exit_reason = "hard_stop"
            break

        lows.append(float(row["low"]))
        highs.append(float(row["high"]))
        highest_close = max(highest_close, float(row["close"]))
        close_r = (float(row["close"]) - entry.entry_price) / initial_r

        if close_r >= cfg["exit"]["trailing_at_r"]:
            trailing = max(float(row.get("ma10", np.nan)), highest_close - cfg["exit"]["trailing_atr_multiple"] * float(row["atr20"]))
            if np.isfinite(trailing):
                effective_stop = max(effective_stop, trailing)
        elif close_r >= cfg["exit"]["breakeven_at_r"]:
            round_trip = (
                buy_cost(qty * entry.entry_price, cfg)
                + sell_cost(qty * entry.entry_price, cfg)
            ) / qty
            effective_stop = max(effective_stop, entry.entry_price + round_trip)

        if holding_days >= cfg["exit"]["max_holding_days"]:
            pending_reason = "max_holding"
        elif holding_days >= cfg["exit"]["time_stop_days"] and close_r < cfg["exit"]["time_stop_min_r"]:
            pending_reason = "time_stop"

    if exit_price is None:
        last = data.iloc[-1]
        exit_date = pd.Timestamp(last["date"])
        exit_price = float(last["close"]) * (1 - cfg["costs"]["slippage_each_side"])
        exit_reason = "data_end"

    buy_value = qty * entry.entry_price
    sell_value = qty * exit_price
    bcost = buy_cost(buy_value, cfg)
    scost = sell_cost(sell_value, cfg)
    gross = sell_value - buy_value
    net = gross - bcost - scost
    mae = min(lows) / entry.entry_price - 1
    mfe = max(highs) / entry.entry_price - 1
    return TradeResult(
        symbol=entry.symbol,
        signal_date=entry.signal_date.strftime("%Y-%m-%d"),
        entry_datetime=entry.entry_datetime.strftime("%Y-%m-%d %H:%M:%S"),
        entry_price=entry.entry_price,
        quantity=qty,
        initial_stop=plan.stop_price,
        exit_date=pd.Timestamp(exit_date).strftime("%Y-%m-%d"),
        exit_price=round(float(exit_price), 4),
        exit_reason=str(exit_reason),
        gross_pnl=round(gross, 2),
        net_pnl=round(net, 2),
        return_pct=net / (buy_value + bcost),
        r_multiple=net / (qty * initial_r + bcost),
        mae_pct=mae,
        mfe_pct=mfe,
        holding_days=holding_days,
        buy_cost=round(bcost, 2),
        sell_cost=round(scost, 2),
    )


def results_frame(results: list[TradeResult]) -> pd.DataFrame:
    return pd.DataFrame([asdict(x) for x in results])
