from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from metrics import trade_metrics
from s1_engine import (
    find_entry,
    load_config,
    prepare_daily_features,
    results_frame,
    simulate_trade,
    size_position,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="S1 frozen-spec event-study validator")
    parser.add_argument("--daily", required=True)
    parser.add_argument("--intraday", required=True)
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--config", default="../config/s1_config.json")
    parser.add_argument("--output", default="../reports/event_study_trades.csv")
    args = parser.parse_args()

    cfg = load_config(args.config)
    daily = pd.read_csv(args.daily)
    intraday = pd.read_csv(args.intraday)
    benchmark = pd.read_csv(args.benchmark)
    features = prepare_daily_features(daily, benchmark, cfg)
    signals = features[features["signal"]].copy()

    results = []
    for _, signal in signals.iterrows():
        entry = find_entry(signal, intraday, cfg)
        if entry is None:
            continue
        plan = size_position(entry, cfg["capital"], cfg["capital"], cfg)
        if plan is None:
            continue
        symbol_daily = features[features["symbol"] == entry.symbol]
        result = simulate_trade(entry, plan, symbol_daily, cfg)
        if result is not None:
            results.append(result)

    frame = results_frame(results)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False)
    print(json.dumps(trade_metrics(frame), ensure_ascii=False, indent=2))
    print(f"wrote {output}")


if __name__ == "__main__":
    main()

