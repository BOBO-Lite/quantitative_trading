import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adapters.akshare_readonly import normalize_daily, compare_dated_rows, normalize_tencent_daily


class AkshareGateTests(unittest.TestCase):
    def test_tencent_pinned_sz000_unit_correction(self):
        rows = [dict(date='2026-09-08',open=11.66,close=11.78,high=11.81,low=11.65,volume=740516.,amount=870361100.)]
        row = normalize_tencent_daily(rows,'000001.SZ','2026-09-08','2026-09-08T19:00:00+08:00','1.18.94')
        self.assertEqual(row['volume'],74051600)
        self.assertEqual(row['source_volume_multiplier'],100)

    def test_tencent_version_upgrade_requires_reaudit(self):
        with self.assertRaisesRegex(ValueError,'版本变化'):
            normalize_tencent_daily([], '000001.SZ','2026-09-08','2026-09-08T19:00:00+08:00','1.18.95')

    def test_tencent_sh_volume_not_multiplied_twice(self):
        rows = [dict(date='2026-09-08',open=8.38,close=8.4,high=8.52,low=8.33,volume=28570000.,amount=241014200.)]
        row = normalize_tencent_daily(rows,'601555.SH','2026-09-08','2026-09-08T19:00:00+08:00','1.18.94')
        self.assertEqual(row['volume'],28570000)
    def setUp(self):
        self.rows = [{'日期': '2026-09-08', '股票代码': '000001', '开盘': 10., '收盘': 10.1,
                      '最高': 10.2, '最低': 9.9, '成交量': 1000, '成交额': 1005000}]

    def convert(self, **kw):
        return normalize_daily(self.rows, kw.get('symbol', '000001.SZ'), '2026-09-08',
                               kw.get('observed_at', '2026-09-08T16:00:00+08:00'))

    def test_lots_are_converted_to_shares(self):
        row = self.convert()
        self.assertEqual(row['volume'], 100000)
        self.assertFalse(row['historical_state_verified'])

    def test_stale_day_cannot_be_relabelled_or_paused(self):
        self.rows[0]['日期'] = '2026-09-07'
        with self.assertRaisesRegex(ValueError, '未返回目标日'):
            self.convert()

    def test_intraday_cannot_be_final_daily(self):
        with self.assertRaisesRegex(ValueError, '尚未完成'):
            self.convert(observed_at='2026-09-08T14:59:00+08:00')

    def test_naive_timestamp_rejected(self):
        with self.assertRaisesRegex(ValueError, '时区'):
            self.convert(observed_at='2026-09-08T16:00:00')

    def test_wrong_exchange_rejected(self):
        with self.assertRaisesRegex(ValueError, '交易所'):
            self.convert(symbol='000001.SH')

    def test_wrong_volume_units_are_detected(self):
        self.rows[0]['成交量'] *= 100
        with self.assertRaisesRegex(ValueError, '量额单位'):
            self.convert()

    def test_duplicate_target_rejected(self):
        self.rows.append(copy.deepcopy(self.rows[0]))
        with self.assertRaisesRegex(ValueError, '重复'):
            self.convert()

    def test_other_symbol_response_rejected(self):
        self.rows[0]['股票代码'] = '600036'
        with self.assertRaisesRegex(ValueError, '代码不一致'):
            self.convert()

    def test_ohlc_conflict_rejected(self):
        self.rows[0]['收盘'] = 11
        with self.assertRaisesRegex(ValueError, 'OHLC'):
            self.convert()

    def test_cross_source_mismatch_not_silently_accepted(self):
        row = self.convert()
        other = dict(row, volume=row['volume'] * 100)
        self.assertFalse(compare_dated_rows(row, other)['matches'])


if __name__ == '__main__':
    unittest.main()
