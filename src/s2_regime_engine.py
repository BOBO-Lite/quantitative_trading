"""S2 多环境研究路由；只生成环境报告，不产生自动交易指令。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class RegimeState:
    date: str
    regime: str
    label: str
    benchmark_close: float
    ma20: float
    ma60: float
    ma20_slope_5: float
    return_20: float
    target_exposure: float
    max_single_exposure: float
    max_positions: int
    live_enabled: bool
    route_status: str


def load_regime_config(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def classify_regime(benchmark: pd.DataFrame, cfg: dict[str, Any]) -> RegimeState:
    frame = benchmark.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame = frame.sort_values("date").drop_duplicates("date", keep="last")
    if len(frame) < 60:
        raise ValueError("S2环境识别至少需要60个交易日基准数据")
    close = frame["close"].astype(float)
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    c = cfg["classifier"]
    slope_days = int(c["trend_ma_slope_days"])
    ma20_slope = float(ma20.iloc[-1] / ma20.iloc[-1 - slope_days] - 1)
    ret20 = float(close.iloc[-1] / close.iloc[-21] - 1)
    last = float(close.iloc[-1])
    m20 = float(ma20.iloc[-1])
    m60 = float(ma60.iloc[-1])

    if c.get("weak_market_cash_first", False) and last < m60 and m20 < m60 and ma20_slope < 0 and ret20 < 0:
        regime = "defensive_cash"
    elif last > m20 > m60 and ma20_slope > 0:
        regime = "trend_breakout"
    elif (
        abs(last / m20 - 1) <= float(c["range_close_to_ma20_max"])
        and abs(last / m60 - 1) <= float(c["range_close_to_ma60_max"])
        and abs(m20 / m60 - 1) <= float(c["range_ma20_to_ma60_max"])
        and abs(ma20_slope) <= float(c["range_ma20_slope_abs_max"])
        and ret20 >= float(c["range_min_return_20"])
    ):
        regime = "range_mean_reversion"
    elif last > m60 and ret20 >= float(c["rotation_min_return_20"]):
        regime = "industry_rotation"
    else:
        regime = "defensive_cash"

    strategy = cfg["strategies"][regime]
    route_status = "RESEARCH_ROUTE_ONLY"
    if regime == "industry_rotation":
        route_status = "WAITING_FOR_POINT_IN_TIME_INDUSTRY_DATA"
    elif regime == "defensive_cash":
        route_status = "CASH_DEFENSE_ACTIVE"
    return RegimeState(
        date=frame.iloc[-1]["date"].strftime("%Y-%m-%d"),
        regime=regime,
        label=str(strategy["label"]),
        benchmark_close=round(last, 4),
        ma20=round(m20, 4),
        ma60=round(m60, 4),
        ma20_slope_5=round(ma20_slope, 6),
        return_20=round(ret20, 6),
        target_exposure=float(strategy["target_exposure"]),
        max_single_exposure=float(strategy["max_single_exposure"]),
        max_positions=int(strategy["max_positions"]),
        live_enabled=bool(strategy["live_enabled"]),
        route_status=route_status,
    )


def state_dict(state: RegimeState) -> dict[str, Any]:
    return asdict(state)
