import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from generate_candidates import generate_research_outputs  # noqa: E402


class GenerateCandidatesTests(unittest.TestCase):
    @staticmethod
    def _features() -> pd.DataFrame:
        common = {
            "date": pd.Timestamp("2026-09-03"),
            "close": 10.5,
            "high": 10.6,
            "ma20": 10.0,
            "ma60": 9.5,
            "ma20_prev": 9.9,
            "atr20": 0.3,
            "volume_ratio": 1.5,
            "excess20_pct": 0.9,
            "compression10": 0.1,
            "score": 88.0,
            "structure_low10": 9.6,
            "prior_high_close20": 10.2,
            "close_location": 0.8,
            "avg_amount20": 100_000_000,
            "listing_days": 1000,
            "paused": False,
            "st": False,
            "eligible": True,
            "market_gate": True,
            "signal": True,
        }
        allowed = {**common, "symbol": "600001.SH"}
        excluded = {
            **common,
            "symbol": "300001.SZ",
            "eligible": False,
            "signal": False,
            "score": float("nan"),
            "excess20_pct": float("nan"),
        }
        return pd.DataFrame([allowed, excluded])

    def test_outputs_are_research_only_and_explain_excluded_board(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            daily = root / "daily.csv"
            benchmark = root / "benchmark.csv"
            output = root / "report"
            pd.DataFrame([{"date": "2026-09-03"}]).to_csv(daily, index=False)
            pd.DataFrame([{"date": "2026-09-03", "close": 6000}]).to_csv(benchmark, index=False)
            with patch("generate_candidates.prepare_daily_features", return_value=self._features()):
                manifest = generate_research_outputs(
                    daily,
                    benchmark,
                    ROOT / "config" / "s1_config.json",
                    pd.Timestamp("2026-09-03"),
                    output,
                )
            self.assertEqual(manifest["classification"], "RESEARCH_CANDIDATES_ONLY")
            self.assertFalse(manifest["automatic_trading"])
            self.assertEqual(manifest["candidate_count"], 1)
            candidates = pd.read_csv(output / "candidates.csv")
            audit = pd.read_csv(output / "all_symbols_reasons.csv")
            self.assertEqual(candidates.iloc[0]["symbol"], "600001.SH")
            reason = audit.loc[audit["symbol"] == "300001.SZ", "failure_reasons"].iloc[0]
            self.assertIn("账户权限范围外", reason)

    def test_observation_pool_survives_closed_market_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            daily = root / "daily.csv"
            benchmark = root / "benchmark.csv"
            output = root / "report"
            pd.DataFrame([{"date": "2026-09-03"}]).to_csv(daily, index=False)
            pd.DataFrame([{"date": "2026-09-03", "close": 6000}]).to_csv(benchmark, index=False)
            features = self._features().iloc[[0]].copy()
            features["market_gate"] = False
            features["signal"] = False
            with patch("generate_candidates.prepare_daily_features", return_value=features):
                manifest = generate_research_outputs(
                    daily, benchmark, ROOT / "config" / "s1_config.json",
                    pd.Timestamp("2026-09-03"), output,
                )
            self.assertEqual(manifest["candidate_count"], 0)
            self.assertEqual(manifest["observation_count"], 1)
            observations = pd.read_csv(output / "observation_pool.csv")
            self.assertEqual(observations.iloc[0]["symbol"], "600001.SH")


if __name__ == "__main__":
    unittest.main()
