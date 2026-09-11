import importlib.util
from types import SimpleNamespace
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "adapters" / "supermind_s1_minute_backtest.py"
SPEC = importlib.util.spec_from_file_location("supermind_s1_minute_backtest", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def frame(symbol="600001.SH", breakout=True):
    close = np.linspace(8.0, 10.0, 130)
    if breakout:
        close[-1] = close[-2] * 1.03
    high = close * 1.01
    low = close * 0.99
    volume = np.full(130, 1000000.0)
    volume[-1] = 1500000.0
    turnover = np.full(130, 80000000.0)
    return pd.DataFrame({
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "turnover": turnover,
        "is_st": False,
        "is_paused": False,
    }, index=pd.date_range("2026-01-01", periods=130, freq="B"))


class SuperMindMinuteBacktestTests(unittest.TestCase):
    def test_frozen_execution_and_account_boundaries(self):
        self.assertEqual(MODULE.BENCHMARK, "000905.SH")
        self.assertEqual(MODULE.EXCLUDED_PREFIXES, ("300", "301", "688", "689"))
        self.assertEqual(MODULE.RISK_FRACTION, 0.0125)
        self.assertEqual(MODULE.MAX_TOTAL_EXPOSURE, 0.70)
        self.assertEqual(MODULE.SLIPPAGE_ROUND_TRIP, 0.002)
        source = PATH.read_text(encoding="utf-8")
        self.assertIn('set_execution("next_open")', source)
        self.assertIn("g.triggered_symbols", source)

    def test_feature_prior_windows_exclude_signal_day(self):
        data = frame()
        row = MODULE._feature_row("600001.SH", data)
        self.assertAlmostEqual(row["prior_high_close20"], data["close"].iloc[-21:-1].max())
        self.assertAlmostEqual(row["structure_low10_adjusted"], data["low"].iloc[-11:-1].min())
        self.assertAlmostEqual(row["volume_ratio"], 1.5)

    def test_untradeable_boards_are_excluded(self):
        benchmark = pd.DataFrame({"close": np.linspace(100, 140, 130)})
        table, gate = MODULE.build_signal_table({
            "300001.SZ": frame(),
            "688001.SH": frame(),
            "920001.BJ": frame(),
            "600001.SH": frame(),
        }, benchmark)
        self.assertTrue(gate)
        self.assertEqual(table["symbol"].tolist(), ["600001.SH"])

    def test_benchmark_gate_can_skip_full_universe_fetch(self):
        benchmark = pd.DataFrame({"close": np.linspace(140, 100, 130)})
        gate, _, _ = MODULE._benchmark_context(benchmark)
        self.assertFalse(gate)
        source = PATH.read_text(encoding="utf-8")
        self.assertLess(source.index("if not market_gate:"), source.index("history_by_symbol = history("))

    def test_position_size_obeys_all_caps(self):
        candidate = MODULE._feature_row("600001.SH", frame())
        candidate["signal_close_adjusted"] = candidate["close_adjusted"]
        plan = MODULE._size_for_entry(candidate, 10.0, 30000.0, 30000.0, 0.0)
        self.assertIsNotNone(plan)
        self.assertLessEqual(plan["quantity"] * 10.0, 30000.0 * MODULE.MAX_SINGLE_EXPOSURE)
        self.assertEqual(plan["quantity"] % 100, 0)

    def test_platform_candidate_maps_adjusted_signal_close(self):
        source = PATH.read_text(encoding="utf-8")
        self.assertIn(
            'item["signal_close_adjusted"] = float(row["close_adjusted"])',
            source,
        )

    def test_partial_entry_fills_use_weighted_average(self):
        candidate = MODULE._feature_row("600001.SH", frame())
        candidate["signal_close_adjusted"] = candidate["close_adjusted"]
        first = MODULE._merge_entry_fill(candidate, 10.0, 100, None, "20260102")
        merged = MODULE._merge_entry_fill(candidate, 10.4, 200, first, "20260102")
        self.assertEqual(merged["filled_quantity"], 300)
        self.assertAlmostEqual(merged["entry_price"], (10.0 * 100 + 10.4 * 200) / 300)
        self.assertAlmostEqual(
            merged["initial_r"], merged["entry_price"] - merged["initial_stop"]
        )

    def test_exit_orders_have_per_symbol_pending_gate(self):
        source = PATH.read_text(encoding="utf-8")
        self.assertIn("g.exit_pending_symbols = set()", source)
        self.assertIn("symbol in g.exit_pending_symbols", source)
        self.assertIn("trade.last_quantity", source)

    def test_exit_intent_exists_before_synchronous_order_callback(self):
        previous_g = getattr(MODULE, "g", None)
        previous_order = getattr(MODULE, "order", None)
        previous_log = getattr(MODULE, "log", None)
        MODULE.g = SimpleNamespace(
            exit_pending_symbols=set(), exit_intents={}, exit_orders={}
        )
        MODULE.log = SimpleNamespace(info=lambda *_: None)
        observed = {}

        def synchronous_order(symbol, quantity):
            observed["pending"] = symbol in MODULE.g.exit_pending_symbols
            observed["intent"] = symbol in MODULE.g.exit_intents
            return "order-1"

        MODULE.order = synchronous_order
        try:
            self.assertTrue(MODULE._submit_exit("600001.SH", 100, "stop", "now"))
            self.assertTrue(observed["pending"])
            self.assertTrue(observed["intent"])
            self.assertEqual(MODULE.g.exit_orders["order-1"]["symbol"], "600001.SH")
        finally:
            if previous_g is None:
                del MODULE.g
            else:
                MODULE.g = previous_g
            if previous_order is None:
                del MODULE.order
            else:
                MODULE.order = previous_order
            if previous_log is None:
                del MODULE.log
            else:
                MODULE.log = previous_log

    def test_entry_intent_is_registered_before_order_call(self):
        source = PATH.read_text(encoding="utf-8")
        intent_index = source.index("g.entry_intents[symbol] = intent")
        order_index = source.index('oid = order(symbol, plan["quantity"], price=max_price)')
        self.assertLess(intent_index, order_index)


if __name__ == "__main__":
    unittest.main()
