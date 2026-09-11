"""历史行业分母、缺口及长基准拼接的失败关闭测试。"""
import copy
import json
import sys
import unittest
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from audit_long_history import industry_series, benchmark_frame, enrich
from import_supermind_minute_probe import decode_packets


class LongHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packets = decode_packets((ROOT/'reports/s2_research/long_history/platform_export.txt').read_text(encoding='utf8'))
        cls.mapping = pd.read_csv(ROOT/'runtime/industry_history/monthly_industry.csv.gz', dtype=str)

    def test_real_history_complete_and_event_gate_stays_closed(self):
        series = industry_series(self.packets, self.mapping)
        self.assertEqual(len(series), 792)
        features = json.loads((ROOT/'reports/s2_research/portfolio_replay/historical_ranked_features.json').read_text(encoding='utf8'))
        result = enrich(features, series)
        for day in result['days'][:3]:
            for stock in day['stocks']:
                self.assertFalse(stock['event_clear'])
                self.assertFalse(stock['pit_verified'])
                self.assertTrue(0 < stock['industry_percentile'] <= 1)
                self.assertNotIn('PIT_INDUSTRY_FEATURES_MISSING', stock['blockers'])

    def test_missing_required_price_cannot_shrink_denominator(self):
        packets = copy.deepcopy(self.packets)
        row = next(r for r in packets['industry_prices_0']['rows'] if r['symbol']=='000001.SZ')
        row['close'][-1] = None
        with self.assertRaisesRegex(ValueError, '价格缺失'):
            industry_series(packets, self.mapping)

    def test_missing_packet_and_calendar_day_rejected(self):
        packets = copy.deepcopy(self.packets)
        del packets['industry_prices_0']
        with self.assertRaisesRegex(ValueError, '覆盖不完整'):
            industry_series(packets, self.mapping)
        packets = copy.deepcopy(self.packets)
        for k,v in packets.items():
            if k.startswith('industry_prices_'):
                v['dates'].pop(5)
                for row in v['rows']: row['close'].pop(5)
        with self.assertRaisesRegex(ValueError, '交易日存在遗漏'):
            industry_series(packets, self.mapping)

    def test_changed_month_membership_rejected(self):
        packets = copy.deepcopy(self.packets)
        packets['industry_memberships']['mappings']['20190228']['T19']['members'].remove('000001.SZ')
        with self.assertRaisesRegex(ValueError, '独立月末快照'):
            industry_series(packets, self.mapping)

    def test_benchmark_overlap_mismatch_and_duplicate_fail(self):
        packet = dict(symbol='000905.SH',data={'close':{'2026-01-02':100.,'2026-01-05':101.}})
        current = pd.DataFrame([dict(date='2026-01-05',close=101.),dict(date='2026-01-06',close=102.)])
        frame, checks = benchmark_frame(packet,current)
        self.assertEqual(len(frame),3)
        current.loc[0,'close']=102
        with self.assertRaisesRegex(ValueError,'重叠'):
            benchmark_frame(packet,current)
        with self.assertRaisesRegex(ValueError,'重复'):
            benchmark_frame(packet,pd.concat([current,current]))


if __name__ == '__main__': unittest.main()
