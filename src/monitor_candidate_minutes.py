"""只读监视研究候选的次日分钟触发，不连接券商、不下单。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, time as clock_time, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "adapters"))

from adapters.eastmoney_readonly import realtime_minutes, realtime_quotes  # noqa: E402
from s1_engine import Entry, load_config, size_position  # noqa: E402


CHINA_TZ = timezone(timedelta(hours=8))


def load_account_snapshot(path: Path, now: datetime | None = None) -> tuple[float, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    generated = pd.Timestamp(payload["generated_at"])
    if generated.tzinfo is None:
        raise ValueError("账户快照generated_at必须带时区")
    current = pd.Timestamp(now or datetime.now(CHINA_TZ))
    if current.tzinfo is None:
        current = current.tz_localize(CHINA_TZ)
    age = current - generated.tz_convert(current.tz)
    if age < pd.Timedelta(0) or age > pd.Timedelta(minutes=15):
        raise ValueError("账户快照超过15分钟或时间在未来")
    portfolio = payload.get("portfolio", {})
    equity = float(portfolio["total_value"])
    cash = float(portfolio["available_cash"])
    if equity <= 0 or cash < 0 or cash > equity * 1.01:
        raise ValueError("账户快照资金字段不合理")
    return equity, cash


def load_event_calendar(path: Path) -> pd.DataFrame:
    rows = pd.read_csv(path, dtype={"symbol": str})
    required = {"symbol", "next_periodic_report_date", "coverage_through", "verified_at", "source_url"}
    missing = required - set(rows.columns)
    if missing:
        raise ValueError(f"财报日历缺少字段：{sorted(missing)}")
    if rows["symbol"].duplicated().any():
        raise ValueError("财报日历存在重复股票")
    return rows.set_index("symbol", drop=False)


def event_gate(symbol: str, entry_date: pd.Timestamp, calendar: pd.DataFrame | None) -> dict[str, Any]:
    if calendar is None or symbol not in calendar.index:
        return {"passed": False, "status": "WAITING_FOR_EVENT_CALENDAR"}
    row = calendar.loc[symbol]
    verified = pd.Timestamp(row["verified_at"])
    if verified.tzinfo is not None:
        verified = verified.tz_convert(CHINA_TZ).tz_localize(None)
    horizon = entry_date.normalize() + pd.Timedelta(days=31)
    if verified.normalize() < entry_date.normalize() - pd.Timedelta(days=7):
        return {"passed": False, "status": "STALE_EVENT_CALENDAR"}
    coverage = pd.Timestamp(row["coverage_through"])
    if coverage.normalize() < horizon:
        return {"passed": False, "status": "EVENT_CALENDAR_COVERAGE_TOO_SHORT"}
    event_raw = row["next_periodic_report_date"]
    if pd.notna(event_raw) and str(event_raw).strip():
        event_date = pd.Timestamp(event_raw).normalize()
        if entry_date.normalize() <= event_date <= horizon:
            return {
                "passed": False,
                "status": "PERIODIC_REPORT_WITHIN_MAX_HOLDING_HORIZON",
                "next_periodic_report_date": event_date.strftime("%Y-%m-%d"),
            }
    return {"passed": True, "status": "EVENT_GATE_PASSED"}


def evaluate_candidate(
    candidate: pd.Series,
    quote: dict[str, Any],
    minute_rows: list[dict[str, Any]],
    cfg: dict[str, Any],
    equity: float | None = None,
    cash: float | None = None,
    event_calendar: pd.DataFrame | None = None,
) -> dict[str, Any]:
    symbol = str(candidate["symbol"])
    base = {
        "symbol": symbol,
        "signal_date": str(pd.Timestamp(candidate["date"]).date()),
        "automatic_trading": False,
        "classification": "RESEARCH_MONITOR_ONLY",
    }
    if not quote.get("actionable_for_new_orders", False):
        return {**base, "status": "STALE_OR_CLOSED_MARKET_DATA"}
    bars = pd.DataFrame([row for row in minute_rows if row.get("ts_code") == symbol])
    if bars.empty:
        return {**base, "status": "NO_MINUTE_DATA"}
    bars["datetime"] = pd.to_datetime(bars["datetime"], errors="raise")
    bars = bars.sort_values("datetime").reset_index(drop=True)
    signal_date = pd.Timestamp(candidate["date"]).normalize()
    bars = bars[bars["datetime"].dt.normalize() > signal_date].reset_index(drop=True)
    if bars.empty:
        return {**base, "status": "NO_NEXT_TRADING_DAY_DATA"}

    entry_cfg = cfg["entry"]
    first_open = float(bars.iloc[0]["open"])
    signal_close = float(candidate["close"])
    gap = first_open / signal_close - 1
    if not entry_cfg["open_gap_min"] <= gap <= entry_cfg["open_gap_max"]:
        return {**base, "status": "OPEN_GAP_REJECTED", "open_gap": gap}

    times = bars["datetime"].dt.time
    start = clock_time.fromisoformat(entry_cfg["start_time"])
    end = clock_time.fromisoformat(entry_cfg["end_time"])
    for index in bars.index[(times >= start) & (times <= end)]:
        bar = bars.loc[index]
        vwap = float(bar.get("average") or 0)
        if vwap <= 0:
            continue
        confirmed = float(bar["close"]) > float(candidate["high"]) and float(bar["close"]) > vwap
        if not confirmed:
            continue
        if index + 1 >= len(bars):
            return {**base, "status": "TRIGGER_CONFIRMED_WAITING_NEXT_BAR"}
        next_bar = bars.loc[index + 1]
        fill = float(next_bar["open"]) * (1 + float(cfg["costs"]["slippage_each_side"]))
        max_price = signal_close * (1 + float(entry_cfg["max_price_above_signal_close"]))
        if fill > max_price:
            return {
                **base, "status": "NEXT_BAR_ABOVE_PRICE_CAP",
                "estimated_fill": round(fill, 4), "max_price": round(max_price, 4),
            }
        entry = Entry(
            symbol=symbol,
            signal_date=signal_date,
            entry_datetime=pd.Timestamp(next_bar["datetime"]),
            entry_price=round(fill, 4),
            signal_close=signal_close,
            signal_high=float(candidate["high"]),
            atr20=float(candidate["atr20"]),
            structure_low10=float(candidate["structure_low10"]),
            score=float(candidate["score"]),
        )
        result = {
            **base,
            "status": "TRIGGERED_WAITING_FOR_ACCOUNT_SNAPSHOT",
            "confirmed_at": pd.Timestamp(bar["datetime"]).isoformat(),
            "next_bar_at": entry.entry_datetime.isoformat(),
            "estimated_fill": entry.entry_price,
            "max_price": round(max_price, 4),
            "open_gap": gap,
        }
        if equity is not None and cash is not None:
            gate = event_gate(symbol, entry.entry_datetime.normalize(), event_calendar)
            result["event_gate"] = gate
            if not gate["passed"]:
                result["status"] = gate["status"]
            else:
                plan = size_position(entry, equity, cash, cfg)
                if plan is None:
                    result["status"] = "RISK_SIZING_REJECTED"
                else:
                    result.update({
                        "status": "READY_FOR_MANUAL_DECISION",
                        "planned_qty": plan.quantity,
                        "initial_stop": plan.stop_price,
                        "normal_risk_amount": round(plan.normal_risk_amount, 2),
                        "gap_stress_amount": round(plan.gap_stress_amount, 2),
                    })
        return result
    now_time = pd.Timestamp(bars.iloc[-1]["datetime"]).time()
    status = "ENTRY_WINDOW_EXPIRED" if now_time > end else "MONITORING_NO_TRIGGER"
    return {**base, "status": status, "open_gap": gap}


def run(
    candidates_path: Path,
    output_path: Path,
    config_path: Path,
    equity: float | None = None,
    cash: float | None = None,
    event_calendar: pd.DataFrame | None = None,
) -> dict[str, Any]:
    candidates = pd.read_csv(candidates_path)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
        "read_only_market_data": True,
        "automatic_trading": False,
        "candidate_count": len(candidates),
        "results": [],
    }
    if candidates.empty:
        payload["status"] = "NO_RESEARCH_CANDIDATES"
    else:
        symbols = candidates["symbol"].astype(str).tolist()
        quotes = {row["ts_code"]: row for row in realtime_quotes(symbols)}
        minutes = realtime_minutes(symbols)
        cfg = load_config(config_path)
        payload["results"] = [
            evaluate_candidate(
                row, quotes[str(row["symbol"])], minutes, cfg, equity, cash, event_calendar
            )
            for _, row in candidates.iterrows()
        ]
        payload["status"] = "COMPLETE"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, output_path)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="只读监视S1研究候选分钟触发")
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default=str(ROOT / "config" / "s1_config.json"))
    parser.add_argument("--equity", type=float)
    parser.add_argument("--cash", type=float)
    parser.add_argument("--account-snapshot", help="本地只读账户快照JSON；必须在15分钟内生成")
    parser.add_argument("--event-calendar", help="已人工核对的定期报告日历CSV")
    args = parser.parse_args()
    if (args.equity is None) != (args.cash is None):
        parser.error("--equity和--cash必须同时提供")
    if args.account_snapshot and args.equity is not None:
        parser.error("--account-snapshot不能与--equity/--cash同时使用")
    equity, cash = args.equity, args.cash
    if args.account_snapshot:
        equity, cash = load_account_snapshot(Path(args.account_snapshot))
    calendar = load_event_calendar(Path(args.event_calendar)) if args.event_calendar else None
    payload = run(
        Path(args.candidates), Path(args.output), Path(args.config), equity, cash, calendar
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
