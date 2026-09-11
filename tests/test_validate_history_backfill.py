import sys
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from validate_history_backfill import REQUIRED_COLUMNS, validate_frame  # noqa: E402


class ValidateHistoryBackfillTests(unittest.TestCase):
    def valid_frame(self):
        return pd.DataFrame([{
            "date": "2026-09-04", "symbol": "000001.SZ",
            "open": 10.0, "high": 10.8, "low": 9.8, "close": 10.5,
            "volume": 1000, "amount": 10000,
        }], columns=REQUIRED_COLUMNS)

    def test_valid_frame_passes(self):
        result = validate_frame(
            self.valid_frame(), {"000001.SZ"}, "2018-01-01", "2026-09-04"
        )
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["missing_symbols"], [])

    def test_bad_price_relation_and_duplicate_are_reported(self):
        frame = pd.concat([self.valid_frame(), self.valid_frame()], ignore_index=True)
        frame.loc[0, "high"] = 9.0
        result = validate_frame(frame, {"000001.SZ"}, "2018-01-01", "2026-09-04")
        self.assertEqual(result["duplicate_date_symbol_rows"], 1)
        self.assertEqual(result["high_relation_failure_rows"], 1)
        self.assertTrue(result["errors"])

    def test_missing_expected_symbol_is_separate_from_field_errors(self):
        result = validate_frame(
            self.valid_frame(), {"000001.SZ", "600000.SH"},
            "2018-01-01", "2026-09-04",
        )
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["missing_symbols"], ["600000.SH"])


if __name__ == "__main__":
    unittest.main()
