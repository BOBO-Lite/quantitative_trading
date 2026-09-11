import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from build_industry_return_series import run  # noqa: E402


class BuildIndustryReturnSeriesTests(unittest.TestCase):
    def test_uses_previous_month_mapping_without_lookahead(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            daily = root / "daily.csv.gz"
            industry = root / "industry.csv.gz"
            output = root / "returns.csv.gz"
            pd.DataFrame([
                ["2026-01-30", "000001.SZ", 10.0],
                ["2026-02-02", "000001.SZ", 11.0],
                ["2026-03-02", "000001.SZ", 12.1],
            ], columns=["date", "symbol", "close"]).to_csv(daily, index=False, compression="gzip")
            pd.DataFrame([
                ["2026-01-31", "000001.SZ", "OLD", "旧行业"],
                ["2026-02-28", "000001.SZ", "NEW", "新行业"],
            ], columns=["date", "symbol", "industry_code", "industry_name"]).to_csv(
                industry, index=False, compression="gzip"
            )
            report = run(daily, industry, output, chunksize=2)
            frame = pd.read_csv(output)
        self.assertEqual(frame["industry_code"].tolist(), ["OLD", "NEW"])
        self.assertAlmostEqual(frame.iloc[0]["equal_weight_return"], 0.1)
        self.assertTrue(report["pre_research_ready"])
        self.assertFalse(report["formal_backtest_ready"])


if __name__ == "__main__":
    unittest.main()
