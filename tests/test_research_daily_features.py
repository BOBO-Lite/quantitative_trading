import copy
import json
import sys
from pathlib import Path
import unittest
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from research_daily_features import stock_features, benchmark_features
from research_daily_features import build_feature_report, packet_rows
from import_supermind_minute_probe import decode_packets
from build_history_sample_bundle import build_bundle
from research_portfolio import run_bundle


def history():
    rows = []
    for i, stamp in enumerate(pd.bdate_range('2025-01-01', periods=160)):
        close = 10 + i * .01
        rows.append(dict(date=stamp.strftime('%Y-%m-%d'), open=close-.01, high=close+.1,
            low=close-.1, close=close, volume=1000., turnover=8e7, factor=1.,
            high_limit=close*1.1, low_limit=close*.9, is_st=False, is_paused=False))
    return rows


class DailyFeatureTests(unittest.TestCase):
    def setUp(self):
        self.rows = history()
        self.asof = self.rows[130]['date']

    def features(self, rows=None, bm=None):
        return stock_features(self.rows if rows is None else rows, self.rows if bm is None else bm,
                              self.asof, '600036.SH')

    def test_future_rows_do_not_change_past_features(self):
        expected = self.features(self.rows[:131], self.rows[:131])
        changed = copy.deepcopy(self.rows)
        for row in changed[131:]:
            row.update(close=9999., volume=1e10, factor=9.)
        self.assertEqual(self.features(changed, changed), expected)

    def test_breakout_and_volume_baselines_exclude_signal_day(self):
        changed = copy.deepcopy(self.rows)
        changed[130].update(close=20., high=21., low=11., volume=3000.)
        result = self.features(changed)
        self.assertAlmostEqual(result['prior_breakout_close'], self.rows[129]['close'])
        self.assertAlmostEqual(result['volume_ratio'], 3.)
        self.assertAlmostEqual(result['ma20'], sum(r['close'] for r in changed[111:131])/20)

    def test_corporate_action_window_fails_closed(self):
        changed = copy.deepcopy(self.rows)
        changed[100]['factor'] = 2.
        with self.assertRaisesRegex(ValueError, 'CORPORATE_ACTION'):
            self.features(changed)

    def test_missing_signal_day_cannot_use_stale_close(self):
        changed = [r for r in self.rows if r['date'] != self.asof]
        with self.assertRaisesRegex(ValueError, '信号日'):
            self.features(changed)

    def test_missing_middle_day_is_not_assumed_paused(self):
        changed = self.rows[:100] + self.rows[101:]
        with self.assertRaisesRegex(ValueError, '交易日不一致'):
            self.features(changed)

    def test_missing_events_and_ranking_stay_blocked(self):
        result = self.features()
        self.assertFalse(result['event_clear'])
        self.assertFalse(result['pit_verified'])
        self.assertIsNone(result['rs_percentile'])
        self.assertEqual(len(result['blockers']), 3)

    def test_prelisting_nulls_do_not_count_as_observed_days(self):
        changed = copy.deepcopy(self.rows)
        for row in changed[:20]:
            row['close'] = None
        with self.assertRaisesRegex(ValueError, '有效上市行情'):
            self.features(changed)

    def test_missing_historical_status_not_defaulted(self):
        changed = copy.deepcopy(self.rows)
        changed[130]['is_st'] = None
        with self.assertRaisesRegex(ValueError, '历史状态'):
            self.features(changed)

    def test_benchmark_future_prices_do_not_change_regime_inputs(self):
        self.assertEqual(benchmark_features(self.rows, self.asof),
                         benchmark_features(self.rows[:131], self.asof))


class RealFeatureBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = Path(__file__).resolve().parents[1] / 'reports/s2_research'
        cls.packets = decode_packets((folder/'feature_export_6a9fdb7054104300b63c389a.txt').read_text(encoding='utf8'))
        cls.features = build_feature_report(cls.packets, ['2019-04-16', '2019-04-17', '2019-04-18', '2019-04-19'])
        cls.minutes = json.loads((folder/'portfolio_replay/historical_minute_sample.json').read_text(encoding='utf8'))

    def test_real_daily_and_minutes_run_without_fabricated_entry_evidence(self):
        bundle = build_bundle(self.features, self.minutes)
        result = run_bundle(bundle)
        self.assertEqual(len(bundle['missing_evidence']), 6)
        self.assertEqual(len(result['daily']), 3)
        self.assertEqual(result['orders'], [])
        self.assertFalse(result['formal_strategy_validated'])

    def test_real_future_daily_mutation_does_not_change_signal_features(self):
        stock = packet_rows(self.packets['600036.SH_raw_history'])
        bm = packet_rows(self.packets['000905.SH_benchmark'])
        expected = stock_features(stock, bm, '2019-04-16', '600036.SH')
        changed = copy.deepcopy(stock)
        for row in changed:
            if row['date'] > '2019-04-16':
                row.update(close=999., factor=99.)
        self.assertEqual(stock_features(changed, bm, '2019-04-16', '600036.SH'), expected)

    def test_sample_bridge_cannot_be_unlocked_by_setting_verified_flags(self):
        changed = copy.deepcopy(self.features)
        changed['days'][0]['stocks'][0]['event_clear'] = True
        with self.assertRaisesRegex(ValueError, '只接受未通过'):
            build_bundle(changed, self.minutes)

    def test_disagreeing_daily_close_is_rejected(self):
        changed = copy.deepcopy(self.features)
        changed['days'][1]['stocks'][0]['raw_close'] += 1.
        with self.assertRaisesRegex(ValueError, '口径不一致'):
            build_bundle(changed, self.minutes)


if __name__ == '__main__':
    unittest.main()
