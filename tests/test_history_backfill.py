import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from download_sohu_history_backfill import (  # noqa: E402
    COLUMNS,
    _atomic_json,
    fetch_batch_resilient,
)


class HistoryBackfillTests(unittest.TestCase):
    def test_failed_group_is_split_until_single_symbols(self):
        def fake(symbols, start_date, end_date):
            if len(symbols) > 1:
                raise RuntimeError("batch too large")
            return pd.DataFrame([{
                "date": "2026-09-04", "symbol": symbols[0],
                "open": 1, "high": 1, "low": 1, "close": 1,
                "volume": 100, "amount": 100,
            }], columns=COLUMNS)

        with patch("download_sohu_history_backfill.fetch_batch", side_effect=fake):
            frame = fetch_batch_resilient(
                ["000001.SZ", "600000.SH"], "2018-01-01", "2026-09-04"
            )
        self.assertEqual(set(frame["symbol"]), {"000001.SZ", "600000.SH"})

    def test_single_symbol_failure_is_not_hidden(self):
        with patch(
            "download_sohu_history_backfill.fetch_batch",
            side_effect=RuntimeError("single failed"),
        ):
            with self.assertRaises(RuntimeError):
                fetch_batch_resilient(["000001.SZ"], "2018-01-01", "2026-09-04")

    def test_manifest_replace_retries_transient_windows_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "manifest.json"
            real_replace = __import__("os").replace
            calls = 0

            def flaky_replace(source, destination):
                nonlocal calls
                calls += 1
                if calls < 3:
                    raise PermissionError("temporarily locked")
                return real_replace(source, destination)

            with patch("download_sohu_history_backfill.os.replace", side_effect=flaky_replace):
                _atomic_json({"status": "RUNNING"}, target)
            self.assertEqual(calls, 3)
            self.assertIn("RUNNING", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
