import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from generate_s2_regime_report import generate_s2_regime_report  # noqa: E402


class GenerateS2RegimeReportTests(unittest.TestCase):
    def test_reports_mapping_and_return_readiness_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            benchmark = root / "benchmark.csv"
            pd.DataFrame({
                "date": pd.date_range("2026-01-01", periods=80, freq="B"),
                "close": [100 + i * 0.05 for i in range(80)],
            }).to_csv(benchmark, index=False)
            manifest = root / "industry_manifest.json"
            manifest.write_text(json.dumps({
                "point_in_time_industry_ready": True,
            }), encoding="utf-8")
            returns = root / "industry_daily_returns.csv.gz"
            returns.write_bytes(b"ready")
            report_dir = root / "report"
            payload = generate_s2_regime_report(
                benchmark,
                report_dir,
                ROOT / "config" / "s2_regime_config.json",
                manifest,
                returns,
            )
            self.assertTrue(payload["industry_data"]["mapping_ready"])
            self.assertTrue(payload["industry_data"]["returns_ready"])


if __name__ == "__main__":
    unittest.main()
