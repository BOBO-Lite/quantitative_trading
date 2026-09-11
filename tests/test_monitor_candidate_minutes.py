import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import monitor_candidate_minutes as monitor  # noqa: E402
from monitor_candidate_minutes import evaluate_candidate, run  # noqa: E402
from s1_engine import load_config  # noqa: E402


class MonitorCandidateMinutesTests(unittest.TestCase):
    def test_event_gate_fails_closed_and_rejects_near_report(self):
        entry = pd.Timestamp("2026-09-08")
        self.assertEqual(
            monitor.event_gate("600001.SH", entry, None)["status"],
            "WAITING_FOR_EVENT_CALENDAR",
        )
        calendar = pd.DataFrame([{
            "symbol": "600001.SH",
            "next_periodic_report_date": "2026-09-20",
            "coverage_through": "2026-10-31",
            "verified_at": "2026-09-08T09:30:00+08:00",
            "source_url": "https://example.invalid/official",
        }]).set_index("symbol", drop=False)
        self.assertEqual(
            monitor.event_gate("600001.SH", entry, calendar)["status"],
            "PERIODIC_REPORT_WITHIN_MAX_HOLDING_HORIZON",
        )

    def test_account_snapshot_requires_recent_timezone_aware_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "account.json"
            path.write_text(json.dumps({
                "generated_at": "2026-09-08T09:40:00+08:00",
                "portfolio": {"total_value": 30000, "available_cash": 25000},
                "positions": [],
            }), encoding="utf-8")
            equity, cash = monitor.load_account_snapshot(
                path, datetime.fromisoformat("2026-09-08T09:50:00+08:00")
            )
            self.assertEqual((equity, cash), (30000.0, 25000.0))
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config(ROOT / "config" / "s1_config.json")
        cls.candidate = pd.Series({
            "date": "2026-09-07", "symbol": "600001.SH", "close": 10.0,
            "high": 10.2, "atr20": 0.2, "structure_low10": 9.6, "score": 90,
        })

    def test_signal_fills_only_on_next_minute(self):
        quote = {"actionable_for_new_orders": True}
        minutes = [
            {"ts_code": "600001.SH", "datetime": "2026-09-08 09:45:00", "open": 10.0, "close": 10.25, "average": 10.1},
            {"ts_code": "600001.SH", "datetime": "2026-09-08 09:46:00", "open": 10.3, "close": 10.31, "average": 10.2},
        ]
        result = evaluate_candidate(self.candidate, quote, minutes, self.cfg)
        self.assertEqual(result["status"], "TRIGGERED_WAITING_FOR_ACCOUNT_SNAPSHOT")
        self.assertEqual(result["next_bar_at"], "2026-09-08T09:46:00")
        self.assertAlmostEqual(result["estimated_fill"], 10.3103)

    def test_empty_candidate_file_avoids_market_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidates = root / "candidates.csv"
            pd.DataFrame(columns=["symbol"]).to_csv(candidates, index=False)
            output = root / "monitor.json"
            payload = run(candidates, output, ROOT / "config" / "s1_config.json")
            saved = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "NO_RESEARCH_CANDIDATES")
        self.assertEqual(saved["candidate_count"], 0)


if __name__ == "__main__":
    unittest.main()
