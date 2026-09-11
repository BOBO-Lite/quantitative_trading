import json
import sys
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from s2_regime_engine import classify_regime  # noqa: E402


class S2RegimeEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = json.loads((ROOT / "config" / "s2_regime_config.json").read_text(encoding="utf-8"))

    @staticmethod
    def _benchmark(values):
        return pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=len(values), freq="B"),
            "close": values,
        })

    def test_rising_market_routes_to_trend(self):
        state = classify_regime(self._benchmark(range(100, 180)), self.cfg)
        self.assertEqual(state.regime, "trend_breakout")
        self.assertEqual(state.target_exposure, 0.90)
        self.assertFalse(state.live_enabled)

    def test_falling_market_routes_to_cash_defense(self):
        state = classify_regime(self._benchmark(range(180, 100, -1)), self.cfg)
        self.assertEqual(state.regime, "defensive_cash")
        self.assertEqual(state.target_exposure, 0.0)
        self.assertTrue(state.live_enabled)

    def test_flat_averages_do_not_hide_material_20_day_decline(self):
        values = [100.0] * 60 + [100.0 - 0.25 * i for i in range(1, 21)]
        state = classify_regime(self._benchmark(values), self.cfg)
        self.assertEqual(state.regime, "defensive_cash")

    def test_market_neutral_is_disabled_without_permission(self):
        self.assertFalse(self.cfg["market_neutral"]["enabled"])

    def test_slow_decline_routes_to_cash_before_range(self):
        from copy import deepcopy
        values = [100.] * 60 + [100. - .1 * i for i in range(1, 21)]
        legacy = deepcopy(self.cfg)
        legacy['classifier']['weak_market_cash_first'] = False
        frame = self._benchmark(values)
        self.assertEqual(classify_regime(frame, legacy).regime, 'range_mean_reversion')
        self.assertEqual(classify_regime(frame, self.cfg).regime, 'defensive_cash')


if __name__ == "__main__":
    unittest.main()
