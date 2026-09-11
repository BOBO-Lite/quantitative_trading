import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from update_daily_incremental import (  # noqa: E402
    CHINA_TZ,
    IncrementalUpdateError,
    account_tradable_symbols,
    append_benchmark,
    append_daily,
    build_incremental_rows,
    benchmark_rows_for_update,
    completed_target_date,
    next_unwritten_target_date,
    fetch_snapshot_for_symbols,
    fetch_historical_target_rows,
)


class UpdateDailyIncrementalTests(unittest.TestCase):
    @staticmethod
    def _snapshot(target="2026-09-03", volume=100):
        observed = datetime.fromisoformat(f"{target}T15:00:00+08:00")
        return [{
            "symbol": "000001.SZ",
            "name": "平安银行",
            "last": 12.03,
            "open": 11.88,
            "high": 12.08,
            "low": 11.83,
            "pre_close": 11.91,
            "volume": volume,
            "amount": 745516002.91,
            "market_timestamp": int(observed.timestamp()),
        }]

    @staticmethod
    def _metadata():
        return {
            "000001.SZ": {
                "symbol": "000001.SZ",
                "name": "平安银行",
                "listed_date": "1991-04-03",
            }
        }

    def test_volume_is_converted_from_lots_to_shares(self):
        frame, quality = build_incremental_rows(
            self._snapshot(), pd.Timestamp("2026-09-03"), self._metadata()
        )
        self.assertEqual(frame.iloc[0]["volume"], 10000)
        self.assertEqual(quality["accepted_symbols"], 1)
        self.assertFalse(bool(frame.iloc[0]["paused"]))

    def test_benchmark_update_prefers_live_rows_over_stale_cache(self):
        live = [{"trade_date": "2026-09-07", "provider": "live"}]
        with patch(
            "update_daily_incremental.fetch_benchmark_with_retry", return_value=live
        ), patch(
            "update_daily_incremental.cached_research_benchmark",
            return_value=[{"trade_date": "2026-09-04", "provider": "cache"}],
        ) as cached:
            rows = benchmark_rows_for_update(
                Path("unused"), datetime(2026, 9, 7, 16, 0, tzinfo=CHINA_TZ)
            )
        self.assertEqual(rows, live)
        cached.assert_not_called()

    def test_stale_cache_fails_closed_after_weekday_close(self):
        with patch(
            "update_daily_incremental.fetch_benchmark_with_retry",
            side_effect=RuntimeError("live unavailable"),
        ), patch(
            "update_daily_incremental.cached_research_benchmark",
            return_value=[{"trade_date": "2026-09-04", "provider": "cache"}],
        ):
            with self.assertRaisesRegex(IncrementalUpdateError, "研究缓存停在"):
                benchmark_rows_for_update(
                    Path("unused"), datetime(2026, 9, 7, 16, 0, tzinfo=CHINA_TZ)
                )

    def test_account_permission_filter_excludes_three_boards(self):
        metadata = {
            symbol: {"symbol": symbol}
            for symbol in ["600001.SH", "000001.SZ", "300001.SZ", "688001.SH", "430001.BJ"]
        }
        cfg = {"universe": {
            "excluded_symbol_prefixes": ["300", "301", "688", "689"],
            "excluded_exchanges": ["BJ"],
        }}
        self.assertEqual(
            account_tradable_symbols(metadata, cfg),
            ["000001.SZ", "600001.SH"],
        )

    def test_historical_catch_up_uses_completed_bar(self):
        history = [{
            "trade_date": "2026-09-03", "open": 11.8, "high": 12.1,
            "low": 11.7, "close": 12.0, "volume": 123, "turnover": 456789,
        }]
        with patch(
            "update_daily_incremental._sohu_history_batch",
            return_value={"000001.SZ": history},
        ):
            frame, quality = fetch_historical_target_rows(
                ["000001.SZ"], pd.Timestamp("2026-09-03"), self._metadata(), workers=1
            )
        self.assertEqual(frame.iloc[0]["volume"], 12300)
        self.assertEqual(
            quality["mode"],
            "historical_catch_up_sohu_with_eastmoney_fallback",
        )

    def test_missing_target_day_does_not_invent_suspension(self):
        history = [{'trade_date':'2026-09-02','open':12.,'high':12.,'low':12.,'close':12.,'volume':100,'turnover':120000}]
        with patch('update_daily_incremental._sohu_history_batch',return_value={'000001.SZ':history}), patch('update_daily_incremental._sohu_history',return_value=history), patch('update_daily_incremental.time.sleep'):
            frame, quality = fetch_historical_target_rows(['000001.SZ'],pd.Timestamp('2026-09-03'),self._metadata(),workers=1)
        self.assertTrue(frame.empty)
        self.assertEqual(quality['missing_history_symbols'],['000001.SZ'])
        self.assertEqual(quality['paused_symbols'],[])

    def test_batched_quote_mapping(self):
        payload = {"data": {"diff": [{
            "f2": 12.03, "f3": 1.01, "f5": 620040,
            "f6": 745516002.91, "f12": "000001", "f14": "平安银行",
            "f15": 12.08, "f16": 11.83, "f17": 11.88,
            "f18": 11.91, "f124": 1788400000,
        }]}}
        with patch("update_daily_incremental._request_json", return_value=payload):
            rows, missing, failures = fetch_snapshot_for_symbols(
                ["000001.SZ"], delay_seconds=0
            )
        self.assertEqual(rows[0]["high"], 12.08)
        self.assertEqual(rows[0]["volume"], 620040)
        self.assertEqual(missing, [])
        self.assertEqual(failures, [])

    def test_stale_traded_quote_is_rejected(self):
        snapshot = self._snapshot(target="2026-09-02")
        frame, quality = build_incremental_rows(
            snapshot, pd.Timestamp("2026-09-03"), self._metadata()
        )
        self.assertTrue(frame.empty)
        self.assertEqual(quality["stale_traded_symbols"], ["000001.SZ"])

    def test_paused_quote_uses_previous_close(self):
        snapshot = self._snapshot(target="2026-08-01", volume=0)
        snapshot[0].update({"last": None, "open": None, "high": None, "low": None, "amount": 0})
        frame, _ = build_incremental_rows(
            snapshot, pd.Timestamp("2026-09-03"), self._metadata()
        )
        self.assertEqual(frame.iloc[0]["close"], 11.91)
        self.assertTrue(bool(frame.iloc[0]["paused"]))

    def test_completed_target_date_ignores_today_before_close(self):
        rows = [
            {"trade_date": "2026-09-02"},
            {"trade_date": "2026-09-03"},
        ]
        before_close = datetime(2026, 9, 3, 14, 0, tzinfo=CHINA_TZ)
        after_close = datetime(2026, 9, 3, 15, 20, tzinfo=CHINA_TZ)
        self.assertEqual(
            completed_target_date(before_close, rows), pd.Timestamp("2026-09-02")
        )
        self.assertEqual(
            completed_target_date(after_close, rows), pd.Timestamp("2026-09-03")
        )

    def test_next_target_fills_oldest_gap_first(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "benchmark.csv"
            pd.DataFrame([{"date": "2026-09-02"}]).to_csv(path, index=False)
            rows = [
                {"trade_date": "2026-09-03"},
                {"trade_date": "2026-09-04"},
            ]
            now = datetime(2026, 9, 4, 15, 20, tzinfo=CHINA_TZ)
            self.assertEqual(
                next_unwritten_target_date(now, rows, path),
                pd.Timestamp("2026-09-03"),
            )

    def test_append_daily_is_idempotent_and_conflict_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "daily.csv"
            incoming, _ = build_incremental_rows(
                self._snapshot(), pd.Timestamp("2026-09-03"), self._metadata()
            )
            previous = incoming.copy()
            previous["date"] = pd.Timestamp("2026-09-02")
            previous.to_csv(path, index=False)

            action, combined = append_daily(path, incoming, pd.Timestamp("2026-09-03"))
            self.assertEqual(action, "append")
            self.assertEqual(len(combined), 2)

            incoming.to_csv(path, index=False)
            action, _ = append_daily(path, incoming, pd.Timestamp("2026-09-03"))
            self.assertEqual(action, "already_current")

            conflict = incoming.copy()
            conflict.loc[0, "close"] = 99
            with self.assertRaises(IncrementalUpdateError):
                append_daily(path, conflict, pd.Timestamp("2026-09-03"))

    def test_append_daily_ignores_csv_float_rendering_noise(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "daily.csv"
            incoming, _ = build_incremental_rows(
                self._snapshot(), pd.Timestamp("2026-09-03"), self._metadata()
            )
            stored = incoming.copy()
            stored.loc[0, "amount"] = float(stored.loc[0, "amount"]) + 1e-9
            stored.to_csv(path, index=False)
            action, _ = append_daily(path, incoming, pd.Timestamp("2026-09-03"))
            self.assertEqual(action, "already_current")

    def test_append_benchmark_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "benchmark.csv"
            pd.DataFrame([{"date": "2026-09-02", "close": 6000.0}]).to_csv(
                path, index=False
            )
            rows = [{"trade_date": "2026-09-03", "close": 6010.0}]
            action, combined = append_benchmark(path, rows, pd.Timestamp("2026-09-03"))
            self.assertEqual(action, "append")
            self.assertEqual(len(combined), 2)


if __name__ == "__main__":
    unittest.main()
