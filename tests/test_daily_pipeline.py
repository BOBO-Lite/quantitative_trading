import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from run_daily_pipeline import run_pipeline  # noqa: E402


class DailyPipelineTests(unittest.TestCase):
    def test_incomplete_base_stops_before_network_or_candidate_scan(self):
        coverage = {
            "status": "INCOMPLETE",
            "seen_batch_count": 750,
            "expected_total_batches": 1161,
            "symbol_count": 3750,
            "expected_symbol_count": 5801,
        }
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / "runtime"
            reports = Path(directory) / "reports"
            with patch("run_daily_pipeline.inspect_daily_bundle_coverage", return_value=coverage), \
                 patch("run_daily_pipeline.run_update") as update, \
                 patch("run_daily_pipeline.generate_research_outputs") as scan:
                result = run_pipeline(runtime, reports, ROOT / "config" / "s1_config.json")
            self.assertEqual(result["status"], "WAITING_FOR_COMPLETE_BASE")
            update.assert_not_called()
            scan.assert_not_called()
            self.assertTrue((runtime / "latest_pipeline_status.json").exists())


if __name__ == "__main__":
    unittest.main()
