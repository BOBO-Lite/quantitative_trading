from pathlib import Path
import sys
import unittest

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from s1_engine import (  # noqa: E402
    Entry,
    PositionPlan,
    buy_cost,
    find_entry,
    load_config,
    prepare_daily_features,
    sell_cost,
    simulate_trade,
    size_position,
)


CFG = load_config(ROOT / "config" / "s1_config.json")


class SystemTests(unittest.TestCase):
    def test_config_guards(self):
        self.assertEqual(CFG["status"], "frozen_pending_backtest")
        self.assertLessEqual(CFG["risk"]["risk_fraction_unvalidated"], 0.0125)
        self.assertLessEqual(CFG["risk"]["max_total_exposure_unvalidated"], 0.70)
        self.assertTrue(CFG["entry"]["fill_on_next_bar"])
        self.assertEqual(CFG["costs"]["minimum_commission"], 5.0)
        self.assertGreaterEqual(CFG["risk"]["gap_stress_fraction"], 0.08)
        self.assertEqual(CFG["risk"]["capital_authorized_fraction"], 1.0)
        self.assertLessEqual(CFG["risk"]["max_total_exposure_validated"], 0.90)

    def test_minimum_commission_and_tax(self):
        self.assertEqual(round(buy_cost(5000, CFG), 2), 5.05)
        self.assertEqual(round(sell_cost(5000, CFG), 2), 7.55)

    def test_daily_windows_exclude_current_bar_and_st_from_ranking(self):
        dates = pd.bdate_range("2025-01-02", periods=90)
        rows = []
        for symbol, is_st, base_step in [
            ("GOOD.SH", False, 0.03),
            ("OTHER.SH", False, 0.02),
            ("STOCKST.SH", True, 0.20),
            ("688001.SH", False, 0.20),
            ("300001.SZ", False, 0.20),
            ("430001.BJ", False, 0.20),
        ]:
            for i, date in enumerate(dates):
                close = 10 + base_step * i
                volume = 1000
                if symbol == "GOOD.SH" and i == len(dates) - 1:
                    close += 1.0
                    volume = 100000
                rows.append(
                    [
                        date, symbol, close - 0.05, close + 0.10, close - 0.10,
                        close, volume, 100000000, False, is_st, 500,
                    ]
                )
        daily = pd.DataFrame(
            rows,
            columns=[
                "date", "symbol", "open", "high", "low", "close",
                "volume", "amount", "paused", "st", "listing_days",
            ],
        )
        benchmark = pd.DataFrame(
            {
                "date": dates,
                "close": [100 + 0.1 * i for i in range(len(dates))],
            }
        )
        features = prepare_daily_features(daily, benchmark, CFG)
        last = dates[-1]
        good = features[(features["date"] == last) & (features["symbol"] == "GOOD.SH")].iloc[0]
        st = features[(features["date"] == last) & (features["symbol"] == "STOCKST.SH")].iloc[0]
        star = features[(features["date"] == last) & (features["symbol"] == "688001.SH")].iloc[0]
        chinext = features[(features["date"] == last) & (features["symbol"] == "300001.SZ")].iloc[0]
        beijing = features[(features["date"] == last) & (features["symbol"] == "430001.BJ")].iloc[0]
        self.assertEqual(good["prior_volume20"], 1000)
        self.assertLess(good["prior_high_close20"], good["close"])
        self.assertFalse(bool(st["eligible"]))
        self.assertTrue(pd.isna(st["excess20_pct"]))
        self.assertFalse(bool(star["eligible"]))
        self.assertTrue(pd.isna(star["excess20_pct"]))
        self.assertFalse(bool(chinext["eligible"]))
        self.assertTrue(pd.isna(chinext["excess20_pct"]))
        self.assertFalse(bool(beijing["eligible"]))
        self.assertTrue(pd.isna(beijing["excess20_pct"]))

    def test_position_size_respects_risk_limits(self):
        entry = Entry(
            symbol="TEST.SH",
            signal_date=pd.Timestamp("2026-01-02"),
            entry_datetime=pd.Timestamp("2026-01-05 09:51"),
            entry_price=10.0,
            signal_close=9.9,
            signal_high=9.98,
            atr20=0.20,
            structure_low10=9.65,
            score=80.0,
        )
        plan = size_position(entry, equity=36574.55, cash=36574.55, cfg=CFG)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.quantity % 100, 0)
        self.assertLessEqual(plan.quantity * plan.entry_price, 36574.55 * 0.35)
        self.assertLessEqual(plan.gap_stress_amount, 36574.55 * 0.02)
        self.assertLessEqual(plan.normal_risk_amount, 36574.55 * 0.0125)

    def test_entry_uses_next_bar(self):
        signal = pd.Series(
            {
                "symbol": "TEST.SH",
                "date": pd.Timestamp("2026-01-02"),
                "close": 10.0,
                "high": 10.20,
                "atr20": 0.20,
                "structure_low10": 9.70,
                "score": 88.0,
            }
        )
        bars = pd.DataFrame(
            [
                ["2026-01-05 09:30", "TEST.SH", 10.0, 10.05, 9.98, 10.02, 100, 1002],
                ["2026-01-05 09:45", "TEST.SH", 10.10, 10.26, 10.08, 10.25, 100, 1025],
                ["2026-01-05 09:46", "TEST.SH", 10.24, 10.30, 10.23, 10.28, 100, 1028],
            ],
            columns=["datetime", "symbol", "open", "high", "low", "close", "volume", "amount"],
        )
        entry = find_entry(signal, bars, CFG)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.entry_datetime, pd.Timestamp("2026-01-05 09:46"))
        self.assertGreater(entry.entry_price, 10.24)

    def test_t_plus_one_ignores_entry_day_stop(self):
        entry = Entry(
            symbol="TEST.SH",
            signal_date=pd.Timestamp("2026-01-02"),
            entry_datetime=pd.Timestamp("2026-01-05 09:51"),
            entry_price=10.0,
            signal_close=9.9,
            signal_high=9.98,
            atr20=0.20,
            structure_low10=9.70,
            score=80.0,
        )
        plan = PositionPlan(
            quantity=500,
            entry_price=10.0,
            stop_price=9.70,
            stop_distance=0.03,
            normal_risk_amount=155.0,
            gap_stress_amount=400.0,
            estimated_entry_cost=5.05,
        )
        daily = pd.DataFrame(
            [
                ["2026-01-05", "TEST.SH", 10.0, 10.1, 9.50, 9.80, 9.9, 0.2],
                ["2026-01-06", "TEST.SH", 9.8, 9.9, 9.60, 9.65, 9.85, 0.2],
            ],
            columns=["date", "symbol", "open", "high", "low", "close", "ma10", "atr20"],
        )
        result = simulate_trade(entry, plan, daily, CFG)
        self.assertIsNotNone(result)
        self.assertEqual(result.exit_date, "2026-01-06")
        self.assertEqual(result.exit_reason, "hard_stop")


if __name__ == "__main__":
    unittest.main(verbosity=2)
