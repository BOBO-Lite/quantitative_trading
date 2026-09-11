import copy
import json
import sys
from pathlib import Path
import unittest
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from audit_historical_cross_section import audit_section, enrich_features
from import_supermind_minute_probe import decode_packets
from build_history_sample_bundle import build_bundle
from research_portfolio import run_bundle


def sample():
    rows = [dict(symbol=s, date='2019-04-16', eligible=True, reason='ELIGIBLE',
                 observed_bars=121, is_st=False, is_paused=False, amount20=8e7,
                 ret20=.1, ret60=.2) for s in ('600001.SH', '600002.SH')]
    return dict(date='2019-04-16', universe_asof='2019-04-16',
                source='get_all_securities(stock, historical_date)', benchmark_ret20=.05,
                expected_symbols=[r['symbol'] for r in rows], rows=rows)


class CrossSectionTests(unittest.TestCase):
    def test_average_ties_and_valid_population(self):
        result = audit_section(sample())
        self.assertEqual(result['eligible_count'], 2)
        self.assertEqual([r['rs_percentile'] for r in result['rows']], [.75, .75])

    def test_missing_symbol_cannot_shrink_denominator(self):
        section = sample()
        section['rows'].pop()
        with self.assertRaisesRegex(ValueError, '覆盖不完整'):
            audit_section(section)

    def test_invalid_history_is_not_a_legitimate_strategy_exclusion(self):
        section = sample()
        section['rows'][0].update(eligible=False, reason='MISSING_HISTORY')
        with self.assertRaisesRegex(ValueError, '数据质量排除'):
            audit_section(section)

    def test_current_universe_cannot_replace_historical_date(self):
        section = sample()
        section['universe_asof'] = '2026-09-08'
        with self.assertRaisesRegex(ValueError, '日期'):
            audit_section(section)

    def test_st_with_extreme_return_does_not_affect_ranking(self):
        section = sample()
        extra = dict(section['rows'][0], symbol='600003.SH', is_st=True, eligible=False,
                     reason='ST', ret20=100.)
        section['expected_symbols'].append(extra['symbol'])
        section['rows'].append(extra)
        self.assertEqual(audit_section(section)['eligible_count'], 2)

    def test_fake_eligible_flag_rejected(self):
        section = sample()
        section['rows'][0]['is_paused'] = True
        with self.assertRaisesRegex(ValueError, '排除理由'):
            audit_section(section)

    def test_mapping_uses_previous_month_and_keeps_events_blocked(self):
        row = dict(symbol='600001.SH', ret20=.1, event_clear=False, pit_verified=False,
                   blockers=['FULL_PIT_UNIVERSE_RANKING_MISSING', 'HISTORICAL_EVENT_CALENDAR_MISSING',
                             'PIT_INDUSTRY_FEATURES_MISSING'])
        features = dict(days=[dict(date='2019-04-16', stocks=[row])])
        mapping = pd.DataFrame([dict(date='2019-03-31', symbol='600001.SH', industry_code='OLD'),
                                dict(date='2019-04-30', symbol='600001.SH', industry_code='FUTURE')])
        result = enrich_features(features, [audit_section(sample())], mapping)
        enriched = result['days'][0]['stocks'][0]
        self.assertEqual(enriched['industry'], 'OLD')
        self.assertNotIn('FULL_PIT_UNIVERSE_RANKING_MISSING', enriched['blockers'])
        self.assertFalse(enriched['event_clear'])
        self.assertFalse(enriched['pit_verified'])
        self.assertIn('PIT_INDUSTRY_FEATURES_MISSING', enriched['blockers'])


class RealCrossSectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.folder = cls.root / 'reports/s2_research'
        cls.packets = decode_packets((cls.folder/'cross_export_6a9fdf61d8cd0b00b6bd6729.txt').read_text(encoding='utf8'))

    def test_real_coverage_and_eligible_counts(self):
        for date, count in [('2019-04-16', 2361), ('2019-04-17', 2358), ('2019-04-18', 2354)]:
            result = audit_section(self.packets[date+'_cross_section'])
            self.assertEqual(result['universe_count'], 2855)
            self.assertEqual(result['eligible_count'], count)
            self.assertEqual(sum(result['exclusion_counts'].values()), 2855)

    def test_real_ranks_connect_without_unlocking_event_gate(self):
        audit = [audit_section(p) for p in self.packets.values()]
        f = json.loads((self.folder/'portfolio_replay/historical_daily_features.json').read_text(encoding='utf8'))
        mapping = pd.read_csv(self.root/'runtime/industry_history/monthly_industry.csv.gz', dtype=str)
        features = enrich_features(f, audit, mapping)
        self.assertEqual(len(features['rank_matches']), 6)
        self.assertTrue(all(r['return_delta'] == 0 for r in features['rank_matches']))
        minutes = json.loads((self.folder/'portfolio_replay/historical_minute_sample.json').read_text(encoding='utf8'))
        bundle = build_bundle(features, minutes)
        self.assertTrue(all('FULL_PIT_UNIVERSE_RANKING_MISSING' not in row['reasons'] for row in bundle['missing_evidence']))
        self.assertEqual(run_bundle(bundle)['orders'], [])


if __name__ == '__main__':
    unittest.main()
