import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters import supermind_market_snapshot as snapshot


class SuperMindMarketSnapshotTests(unittest.TestCase):
    def _write_snapshot(self, directory: str, age_seconds: int = 10) -> Path:
        now = datetime.now(timezone(timedelta(hours=8)))
        market_time = now - timedelta(seconds=age_seconds)
        path = Path(directory) / "snapshot.json"
        path.write_text(json.dumps({
            "schema_version": 1,
            "source": "supermind_get_price",
            "generated_at": now.isoformat(timespec="seconds"),
            "market_data_at": market_time.isoformat(timespec="seconds"),
            "quotes": {"601975.SH": {"datetime": market_time.isoformat(), "close": 4.24}},
            "minute_bars": {"601975.SH": [
                {"datetime": market_time.isoformat(), "open": 4.23, "close": 4.24}
            ]},
        }), encoding="utf-8")
        return path

    def test_fresh_quote_is_returned(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_snapshot(directory)
            with patch.dict(os.environ, {"ASHARE_MARKET_SNAPSHOT": str(path)}):
                rows = snapshot.realtime_quotes(["601975.SH"])
            self.assertEqual(rows[0]["ts_code"], "601975.SH")
            self.assertEqual(rows[0]["close"], 4.24)

    def test_stale_snapshot_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_snapshot(directory, age_seconds=120)
            with patch.dict(os.environ, {"ASHARE_MARKET_SNAPSHOT": str(path)}):
                with self.assertRaises(snapshot.SuperMindSnapshotError):
                    snapshot.realtime_quotes(["601975.SH"])

    def test_invalid_symbol_is_rejected(self):
        with self.assertRaises(ValueError):
            snapshot.realtime_quotes(["INVALID"])

    def test_historical_bars_allow_stale_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_snapshot(directory, age_seconds=3600)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["daily_bars"] = {
                "601975.SH": [{"datetime": "2026-09-01", "close": 4.24}]
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            with patch.dict(os.environ, {"ASHARE_MARKET_SNAPSHOT": str(path)}):
                rows = snapshot.historical_bars(["601975.SH"], "daily", 1)
            self.assertEqual(rows, [
                {"ts_code": "601975.SH", "datetime": "2026-09-01", "close": 4.24}
            ])


if __name__ == "__main__":
    unittest.main()
