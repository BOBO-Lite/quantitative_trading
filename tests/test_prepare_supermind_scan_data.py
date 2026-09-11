import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from prepare_supermind_scan_data import (  # noqa: E402
    inspect_daily_bundle_coverage,
    load_benchmark,
    load_daily_parts,
    require_complete_daily_bundle,
)


class PrepareSuperMindScanDataTests(unittest.TestCase):
    @staticmethod
    def _write_universe(root: Path):
        (root / "supermind_universe.json").write_text(json.dumps({
            "symbol_count": 1,
            "securities": [{
                "symbol": "000001.SZ", "name": "平安银行",
                "exchange": "深交所", "listed_date": "1991-04-03",
                "de_listed_date": "2200-01-01",
            }],
        }, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _part_payload(batch_number=0):
        return {
            "batch_number": batch_number,
            "symbols": ["000001.SZ"],
            "missing_symbols": [],
            "row_counts": {"000001.SZ": 1},
            "daily_bars": {"000001.SZ": [{
                "date": "2026-09-02", "open": 10, "high": 11,
                "low": 9, "close": 10.5, "volume": 100,
                "turnover": 123456,
            }]},
        }

    def test_maps_turnover_and_universe_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_universe(root)
            (root / "supermind_daily_part_0000.json").write_text(
                json.dumps(self._part_payload()), encoding="utf-8"
            )
            daily = load_daily_parts(root)
            self.assertEqual(daily.iloc[0]["amount"], 123456)
            self.assertFalse(bool(daily.iloc[0]["paused"]))
            self.assertFalse(bool(daily.iloc[0]["st"]))
            self.assertGreater(daily.iloc[0]["listing_days"], 120)

    def test_prefers_bundle_over_validation_parts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_universe(root)
            (root / "supermind_daily_part_0000.json").write_text(
                json.dumps(self._part_payload()), encoding="utf-8"
            )
            (root / "supermind_daily_bundle_00.json").write_text(json.dumps({
                "format": "supermind_daily_bundle",
                "bundle_number": 0,
                "start_batch": 0,
                "end_batch_exclusive": 1,
                "parts": [self._part_payload()],
            }), encoding="utf-8")
            daily = load_daily_parts(root)
            self.assertEqual(len(daily), 1)
            self.assertEqual(daily.iloc[0]["symbol"], "000001.SZ")

    def test_loads_plain_and_gzip_bundles_together(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_universe(root)
            plain_payload = {
                "format": "supermind_daily_bundle",
                "bundle_number": 0,
                "start_batch": 0,
                "end_batch_exclusive": 1,
                "parts": [self._part_payload(0)],
            }
            second_part = self._part_payload(1)
            second_part["daily_bars"]["000001.SZ"][0]["date"] = "2026-09-01"
            gzip_payload = {
                "format": "supermind_daily_bundle",
                "compression": "gzip",
                "bundle_number": 6,
                "start_batch": 1,
                "end_batch_exclusive": 2,
                "parts": [second_part],
            }
            (root / "supermind_daily_bundle_00.json").write_text(
                json.dumps(plain_payload), encoding="utf-8"
            )
            with gzip.open(
                root / "supermind_daily_bundle_gz_06.json.gz",
                "wt",
                encoding="utf-8",
            ) as handle:
                json.dump(gzip_payload, handle)

            daily = load_daily_parts(root)
            self.assertEqual(len(daily), 2)

    def test_prefers_current_compressed_universe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_universe(root)
            current = {
                "symbol_count": 1,
                "securities": [{
                    "symbol": "000001.SZ", "name": "ST平安",
                    "exchange": "深交所", "listed_date": "1991-04-03",
                    "de_listed_date": "2200-01-01",
                }],
            }
            with gzip.open(
                root / "supermind_universe_current.json.gz",
                "wt",
                encoding="utf-8",
            ) as handle:
                json.dump(current, handle, ensure_ascii=False)
            (root / "supermind_daily_part_0000.json").write_text(
                json.dumps(self._part_payload()), encoding="utf-8"
            )

            daily = load_daily_parts(root)
            self.assertTrue(bool(daily.iloc[0]["st"]))

    def test_filters_unfinished_dates_after_cutoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_universe(root)
            part = self._part_payload()
            part["row_counts"]["000001.SZ"] = 2
            part["daily_bars"]["000001.SZ"].append({
                "date": "2026-09-03", "open": 11, "high": 12,
                "low": 10, "close": 11.5, "volume": 120,
                "turnover": 234567,
            })
            (root / "supermind_daily_part_0000.json").write_text(
                json.dumps(part), encoding="utf-8"
            )

            daily = load_daily_parts(root, as_of="2026-09-02")
            self.assertEqual(len(daily), 1)
            self.assertEqual(str(daily.iloc[0]["date"].date()), "2026-09-02")

    def test_loads_only_frozen_benchmark(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "supermind_benchmark.json").write_text(json.dumps({
                "symbol": "000905.SH", "row_count": 1,
                "daily_bars": [{"date": "2026-09-02", "close": 6000}],
            }), encoding="utf-8")
            benchmark = load_benchmark(root)
            self.assertEqual(len(benchmark), 1)

    @staticmethod
    def _write_coverage_bundle(
        root: Path,
        batches: list[int],
        *,
        total_symbols: int,
    ) -> None:
        symbols = [f"{number:06d}.SZ" for number in range(total_symbols)]
        parts = []
        cursor = 0
        for index, batch in enumerate(batches):
            remaining_batches = len(batches) - index
            take = (len(symbols) - cursor + remaining_batches - 1) // remaining_batches
            batch_symbols = symbols[cursor:cursor + take]
            cursor += take
            parts.append({
                "batch_number": batch,
                "symbols": batch_symbols,
                "missing_symbols": [],
                "row_counts": {symbol: 0 for symbol in batch_symbols},
                "daily_bars": {symbol: [] for symbol in batch_symbols},
            })
        (root / "supermind_daily_bundle_00.json").write_text(json.dumps({
            "format": "supermind_daily_bundle",
            "start_batch": min(batches),
            "end_batch_exclusive": max(batches) + 1,
            "parts": parts,
        }), encoding="utf-8")

    def test_strict_coverage_passes_only_when_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_coverage_bundle(root, [0, 1, 2], total_symbols=5)
            status = inspect_daily_bundle_coverage(
                root, expected_total_batches=3, expected_symbol_count=5
            )
            self.assertEqual(status["status"], "COMPLETE")

    def test_default_expected_count_follows_current_universe_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            total = 5802
            symbols = [f"{number:06d}.SZ" for number in range(total)]
            with gzip.open(root / "supermind_universe_current.json.gz", "wt", encoding="utf-8") as handle:
                json.dump({
                    "symbol_count": total,
                    "securities": [{"symbol": symbol} for symbol in symbols],
                }, handle)
            self._write_coverage_bundle(
                root, list(range(1161)), total_symbols=total
            )
            status = inspect_daily_bundle_coverage(root)
            self.assertEqual(status["status"], "COMPLETE")
            self.assertEqual(status["expected_symbol_count"], 5802)

    def test_strict_coverage_reports_missing_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_coverage_bundle(root, [0, 1], total_symbols=4)
            status = inspect_daily_bundle_coverage(
                root, expected_total_batches=3, expected_symbol_count=4
            )
            self.assertEqual(status["status"], "INCOMPLETE")
            self.assertEqual(status["missing_batches"], [2])

    def test_strict_coverage_rejects_duplicate_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_coverage_bundle(root, [0], total_symbols=1)
            with gzip.open(root / "supermind_daily_bundle_gz_06.json.gz", "wt") as handle:
                json.dump({
                    "format": "supermind_daily_bundle",
                    "start_batch": 0,
                    "end_batch_exclusive": 1,
                    "parts": [self._part_payload(0)],
                }, handle)
            status = inspect_daily_bundle_coverage(
                root, expected_total_batches=1, expected_symbol_count=1
            )
            self.assertEqual(status["status"], "INCOMPLETE")
            self.assertEqual(status["duplicate_batches"], [0])

    def test_strict_coverage_rejects_wrong_symbol_count(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_coverage_bundle(root, [0], total_symbols=1)
            status = inspect_daily_bundle_coverage(
                root, expected_total_batches=1, expected_symbol_count=2
            )
            self.assertEqual(status["status"], "INCOMPLETE")
            self.assertEqual(status["symbol_count"], 1)

    def test_formal_gate_fails_before_outputs_are_created(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_coverage_bundle(root, [0], total_symbols=1)
            daily_output = root / "s1_daily.csv"
            benchmark_output = root / "s1_benchmark.csv"
            with self.assertRaises(ValueError):
                require_complete_daily_bundle(root)
            self.assertFalse(daily_output.exists())
            self.assertFalse(benchmark_output.exists())


if __name__ == "__main__":
    unittest.main()
