from __future__ import annotations

import math

import numpy as np
import pandas as pd


def trade_metrics(trades: pd.DataFrame) -> dict[str, float]:
    if trades.empty:
        return {
            "trades": 0,
            "win_rate": float("nan"),
            "profit_factor": float("nan"),
            "expectancy_r": float("nan"),
            "net_pnl": 0.0,
        }
    pnl = trades["net_pnl"].astype(float)
    wins = pnl[pnl > 0].sum()
    losses = -pnl[pnl < 0].sum()
    return {
        "trades": int(len(trades)),
        "win_rate": float((pnl > 0).mean()),
        "profit_factor": float(wins / losses) if losses > 0 else float("inf"),
        "expectancy_r": float(trades["r_multiple"].mean()),
        "net_pnl": float(pnl.sum()),
        "avg_mae_pct": float(trades["mae_pct"].mean()),
        "avg_mfe_pct": float(trades["mfe_pct"].mean()),
        "avg_holding_days": float(trades["holding_days"].mean()),
    }


def equity_metrics(equity: pd.DataFrame, periods_per_year: int = 252) -> dict[str, float]:
    if equity.empty or len(equity) < 2:
        return {}
    values = equity["total_equity"].astype(float)
    returns = values.pct_change().dropna()
    running_max = values.cummax()
    drawdown = values / running_max - 1
    years = max(len(returns) / periods_per_year, 1 / periods_per_year)
    cagr = (values.iloc[-1] / values.iloc[0]) ** (1 / years) - 1
    vol = returns.std(ddof=1) * math.sqrt(periods_per_year)
    sharpe = returns.mean() / returns.std(ddof=1) * math.sqrt(periods_per_year) if returns.std(ddof=1) > 0 else np.nan
    downside = returns[returns < 0].std(ddof=1)
    sortino = returns.mean() / downside * math.sqrt(periods_per_year) if downside and downside > 0 else np.nan
    max_dd = float(drawdown.min())
    return {
        "cagr": float(cagr),
        "annual_volatility": float(vol),
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "max_drawdown": max_dd,
        "calmar": float(cagr / abs(max_dd)) if max_dd < 0 else np.nan,
    }

