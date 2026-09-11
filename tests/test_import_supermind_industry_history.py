import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from import_supermind_industry_history import (  # noqa: E402
    discover_year_files,
    find_missing_snapshot_months,
    normalize_payloads,
    run,
)


class ImportIndustryHistoryTests(unittest.TestCase):
    def test_normalizes_industry_and_universe_snapshots(self):
        payload = {
            "industry_type": "industryid1",
            "failures": [],
            "snapshots": {"20260131": [{
                "symbol": "000001.SZ", "industry_code": "801780",
                "industry_name": "银行",
            }]},
            "universe_snapshots": {"20260131": [{
                "symbol": "000001.SZ", "name": "平安银行",
                "listed_date": "1991-04-03", "de_listed_date": "2200-01-01",
                "exchange": "深交所",
            }]},
        }
        industry, universe, failures = normalize_payloads([payload])
        self.assertEqual(industry.iloc[0]["date"], "2026-01-31")
        self.assertEqual(universe.iloc[0]["symbol"], "000001.SZ")
        self.assertEqual(failures, [])

    def test_rejects_wrong_industry_level(self):
        with self.assertRaises(ValueError):
            normalize_payloads([{"industry_type": "other"}])

    def test_finds_missing_snapshot_months(self):
        missing = find_missing_snapshot_months([
            "2024-12-31", "2026-01-31", "2026-02-28",
        ])
        self.assertEqual(missing, [f"2025-{month:02d}" for month in range(1, 13)])

    def test_expected_range_detects_missing_edge_months(self):
        missing = find_missing_snapshot_months(
            ["2018-02-28", "2018-03-31"], "2018-01", "2018-04"
        )
        self.assertEqual(missing, ["2018-01", "2018-04"])

    def test_discovers_one_file_per_year_and_prefers_full_gzip(self):
        with tempfile.TemporaryDirectory() as directory:
            raw_dir = Path(directory)
            for name in (
                "supermind_industry_history_2024.json",
                "supermind_industry_history_2024.json.gz",
                "supermind_industry_history_2024.compact.json.gz",
                "supermind_industry_history_2025.compact.json.gz",
            ):
                (raw_dir / name).touch()
            selected = discover_year_files(raw_dir, 2024, 2025)
            self.assertEqual(selected[0].name, "supermind_industry_history_2024.json.gz")
            self.assertEqual(
                selected[1].name,
                "supermind_industry_history_2025.compact.json.gz",
            )

    def test_discovery_reports_missing_year(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(FileNotFoundError, "2025"):
                discover_year_files(Path(directory), 2025, 2025)

    def test_compact_file_keeps_industry_ready_separate_from_metadata_ready(self):
        payload = {
            "industry_type": "industryid1",
            "failures": [],
            "snapshots": {"20250131": [{
                "symbol": "000001.SZ", "industry_code": "1",
                "industry_name": "银行",
            }]},
            "universe_snapshots": {"20250131": [{"symbol": "000001.SZ"}]},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "supermind_industry_history_2025.compact.json"
            source.write_text(__import__("json").dumps(payload), encoding="utf-8")
            report = run([source], root / "out", "2025-01", "2025-01")
        self.assertTrue(report["point_in_time_industry_ready"])
        self.assertFalse(report["point_in_time_universe_metadata_ready"])
        self.assertEqual(report["universe_metadata_coverage"], 0.0)


if __name__ == "__main__":
    unittest.main()
