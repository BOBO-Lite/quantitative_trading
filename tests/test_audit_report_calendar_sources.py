import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from audit_report_calendar_sources import audit, compare_sources, normalize_snapshot


class CalendarSourceAuditTests(unittest.TestCase):
    def setUp(self):
        self.directory = ROOT / 'reports/s2_research/data_feasibility'
        self.payload = json.loads((self.directory / 'eastmoney_appointments_2019-03-31.json').read_text(encoding='utf-8'))

    def test_real_sources_agree_but_cannot_release_pit_gate(self):
        result = audit(self.directory)
        self.assertEqual(result['row_count'], 7)
        self.assertEqual(len(result['cross_source_checks']), 1)
        self.assertTrue(result['cross_source_checks'][0]['dates_agree'])
        self.assertEqual(result['cross_source_checks'][0]['code'], '000001')
        self.assertFalse(result['formal_backtest_ready'])
        self.assertTrue(all(r['published_at'] is None for r in result['rows']))

    def test_actual_date_and_vendor_update_time_are_not_known_at(self):
        self.payload['result']['data'][0]['EITIME'] = '2019-04-01 09:00:00'
        self.payload['result']['data'][0]['APPOINT_PUBLISH_DATE'] = '2019-04-02 00:00:00'
        row = normalize_snapshot(self.payload, 'eastmoney')[0]
        self.assertIsNone(row['available_at'])
        self.assertIsNone(row['published_at'])
        self.assertFalse(row['event_clear'])

    def test_missing_change_field_rejected(self):
        del self.payload['result']['data'][0]['FIRST_CHANGE_DATE']
        with self.assertRaisesRegex(ValueError, '缺少字段'):
            normalize_snapshot(self.payload, 'eastmoney')

    def test_empty_result_is_not_no_event(self):
        self.payload['result']['data'] = []
        with self.assertRaisesRegex(ValueError, '空响应'):
            normalize_snapshot(self.payload, 'eastmoney')

    def test_duplicate_report_cannot_overwrite_version(self):
        self.payload['result']['data'].append(copy.deepcopy(self.payload['result']['data'][0]))
        with self.assertRaisesRegex(ValueError, '重复'):
            normalize_snapshot(self.payload, 'eastmoney')

    def test_invalid_chronology_rejected(self):
        self.payload['result']['data'][0]['FIRST_APPOINT_DATE'] = '2019-03-01 00:00:00'
        with self.assertRaisesRegex(ValueError, '不晚于报告期'):
            normalize_snapshot(self.payload, 'eastmoney')

    def test_disagreement_is_exposed(self):
        rows = normalize_snapshot(self.payload, 'eastmoney')
        other = copy.deepcopy(rows[0])
        other.update(provider='cninfo', first_scheduled_date='2019-04-25')
        checks = compare_sources(rows + [other])
        self.assertFalse(checks[0]['dates_agree'])

    def test_tampered_raw_response_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            raw = json.dumps(self.payload).encode()
            manifest = [dict(name='eastmoney_sample', sha256=hashlib.sha256(raw).hexdigest(), row_count=2)]
            (path / 'public_calendar_probe.json').write_text(json.dumps(manifest))
            (path / 'eastmoney_sample.json').write_bytes(raw + b' ')
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                audit(path)


if __name__ == '__main__':
    unittest.main()
