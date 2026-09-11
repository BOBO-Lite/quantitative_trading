"""合成多标的案例；任何收益数字仅用于账本回归。"""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from research_portfolio import run_bundle, session_minutes
from s2_strategy_rules import Policy
from test_s2_strategy_rules import snapshot


def synthetic_bundle():
    calendar = ['2026-01-05', '2026-01-06', '2026-01-07']
    symbols = ['600001.SH', '600002.SH', '600003.SH']
    days = []
    for number, date in enumerate(calendar[1:]):
        prior = calendar[number]
        stocks = [snapshot() | dict(symbol=s, date=prior, industry='sector-' + s,
                     structure_low_raw=9.8, atr20_raw=.2, target_ma20_raw=10.) for s in symbols]
        benchmark = (dict(close=110, ma20=105, ma60=100, slope5=.01, ret20=.1) if not number
                     else dict(close=90, ma20=95, ma60=100, slope5=-.01, ret20=-.1))
        minutes = []
        for stamp in session_minutes(date):
            price = 10. if stamp[11:16] < '09:45' else 10.2
            minutes.append(dict(datetime=stamp, bars={s: dict(datetime=stamp,
                open=price, close=price, low=price, volume=10000, turnover=10000 * price,
                high_limit=11., low_limit=9., factor=1., is_paused=False) for s in symbols}))
        closing = dict(date=date, stocks={s: dict(factor=1., ma10_raw=10., atr20_raw=.2,
                                                 industry_weak=False) for s in symbols})
        days.append(dict(date=date, previous_close=dict(date=prior, benchmark=benchmark, stocks=stocks),
                         minutes=minutes, close_features=closing))
    return dict(source_kind='SYNTHETIC_TEST_ONLY', calendar=calendar, days=days, initial_cash=30000.)


class PortfolioTests(unittest.TestCase):
    def test_multiple_positions_cash_route_exit_and_account_identity(self):
        result = run_bundle(synthetic_bundle())
        buys = [f for f in result['fills'] if f['buy']]
        sells = [f for f in result['fills'] if not f['buy']]
        self.assertGreaterEqual(len(buys), 2)
        self.assertEqual(len(buys), len(sells))
        self.assertTrue(all(f['fill_time'].endswith('09:46:00') for f in buys))
        self.assertTrue(all(f['fill_time'].endswith('09:32:00') for f in sells))
        self.assertEqual(result['positions'], {})
        self.assertAlmostEqual(result['final']['equity'] - 30000, result['final']['realized_pnl'])
        self.assertLessEqual(result['daily'][0]['equity'] - result['daily'][0]['cash'],
                             .75 * result['daily'][0]['equity'])
        self.assertFalse(result['formal_strategy_validated'])

    def test_cost_pressure_increases_unit_execution_cost_without_oversizing(self):
        baseline = run_bundle(synthetic_bundle())
        stress = run_bundle(synthetic_bundle(), Policy(cost_multiplier=1.5))
        # 高成本可能压低仓位，亏损样例的总损失反而更小；比较每股费用和滑点。
        base_map = {(f['symbol'], f['buy']): f for f in baseline['fills']}
        self.assertTrue(stress['fills'])
        for stressed in stress['fills']:
            base = base_map[(stressed['symbol'], stressed['buy'])]
            self.assertGreater(stressed['fees'] / stressed['quantity'], base['fees'] / base['quantity'])
            if base['buy']:
                self.assertGreater(stressed['price'], base['price'])
            else:
                self.assertLess(stressed['price'], base['price'])
        self.assertLessEqual(sum(f['quantity'] for f in stress['fills'] if f['buy']),
                             sum(f['quantity'] for f in baseline['fills'] if f['buy']))

    def test_missing_minutes_fail_instead_of_selectively_skipping(self):
        bundle = synthetic_bundle()
        bundle['days'][0]['minutes'].pop(4)
        with self.assertRaisesRegex(ValueError, '交易分钟'):
            run_bundle(bundle)

    def test_future_daily_features_rejected(self):
        bundle = synthetic_bundle()
        bundle['days'][0]['previous_close']['date'] = '2026-01-06'
        with self.assertRaisesRegex(ValueError, '前一交易日'):
            run_bundle(bundle)

    def test_industry_cap_counts_same_minute_pending_orders(self):
        bundle = synthetic_bundle()
        for row in bundle['days'][0]['previous_close']['stocks']:
            row['industry'] = 'same-sector'
        result = run_bundle(bundle)
        bought = sum(f['price'] * f['quantity'] for f in result['fills'] if f['buy'])
        self.assertLessEqual(bought, 12000.)
        self.assertGreater(bought, 0.)

    def test_partial_exit_retries_remainder(self):
        bundle = synthetic_bundle()
        for b in bundle['days'][1]['minutes'][1]['bars'].values():
            b['volume'] = 400  # 仅允许100股成交，其余后续分钟重试。
        result = run_bundle(bundle)
        self.assertEqual(result['positions'], {})
        self.assertTrue(any(o['status'] == 'PARTIAL_REMAINDER_CANCELLED'
                            and not o['buy'] for o in result['orders']))
        self.assertTrue(any(f['fill_time'].endswith('09:33:00') for f in result['fills']))

    def test_corporate_action_on_held_stock_stops_replay(self):
        bundle = synthetic_bundle()
        bundle['days'][1]['minutes'][0]['bars']['600001.SH']['factor'] = 2.
        with self.assertRaisesRegex(ValueError, '公司行动'):
            run_bundle(bundle)

    def test_sample_end_marks_positions_without_fake_liquidation(self):
        bundle = synthetic_bundle()
        bundle['days'] = bundle['days'][:1]
        bundle['calendar'] = bundle['calendar'][:2]
        result = run_bundle(bundle)
        self.assertTrue(result['positions'])
        self.assertFalse(any(not f['buy'] for f in result['fills']))
        self.assertAlmostEqual(result['final']['equity'] - 30000,
                               result['final']['realized_pnl'] + result['final']['unrealized_pnl'])

    def test_range_branch_flows_through_portfolio(self):
        bundle = synthetic_bundle()
        pre = bundle['days'][0]['previous_close']
        pre['benchmark'] = dict(close=100, ma20=100, ma60=100, slope5=0, ret20=0)
        for row in pre['stocks']:
            row.update(close=9.7, previous_close=9.6)
        for batch in bundle['days'][0]['minutes']:
            if batch['datetime'][11:16] >= '09:45':
                for bar in batch['bars'].values():
                    bar.update(open=10.1, close=10.1, low=10.1, turnover=101000.)
        result = run_bundle(bundle)
        self.assertTrue(result['fills'])
        self.assertTrue(all(f['route'] == 'range_mean_reversion' for f in result['fills']))

    def test_rotation_branch_flows_through_portfolio(self):
        bundle = synthetic_bundle()
        bundle['days'][0]['previous_close']['benchmark'] = dict(
            close=108, ma20=110, ma60=100, slope5=-.01, ret20=.05)
        result = run_bundle(bundle)
        self.assertTrue(result['fills'])
        self.assertTrue(all(f['route'] == 'industry_rotation' for f in result['fills']))

    def test_entry_day_close_may_schedule_but_not_execute_exit(self):
        from s2_strategy_rules import exit_reason
        position = dict(entry_date='2026-01-06', route='range_mean_reversion',
                        stop=9.5, target_ma20=10.1)
        bar = dict(datetime='2026-01-06T15:00:00', is_paused=False, low=10.1, close=10.2)
        self.assertIsNone(exit_reason(position, bar, 'range_mean_reversion', 0., 1))
        self.assertEqual(exit_reason(position, bar, 'range_mean_reversion', 0., 1, True),
                         'mean_reversion_target')

    def test_intraday_drawdown_not_hidden_by_close_recovery(self):
        bundle = synthetic_bundle()
        bundle['calendar'] = bundle['calendar'][:2]
        bundle['days'] = bundle['days'][:1]
        for batch in bundle['days'][0]['minutes']:
            if batch['datetime'].endswith('09:50:00'):
                for bar in batch['bars'].values():
                    bar.update(open=9.7, close=9.7, low=9.7, turnover=97000.)
        result = run_bundle(bundle)
        self.assertGreater(result['metrics']['max_minute_close_drawdown'], result['daily'][0]['drawdown'])
        self.assertTrue(result['metrics']['drawdown_trough_time'].endswith('09:50:00'))

    def test_unrealized_attribution_reconciles_without_forced_sale(self):
        bundle = synthetic_bundle()
        bundle['calendar'] = bundle['calendar'][:2]
        bundle['days'] = bundle['days'][:1]
        result = run_bundle(bundle)
        self.assertAlmostEqual(sum(p['total'] for p in result['pnl_by_route'].values()),
                               result['final']['equity'] - 30000)
        self.assertEqual(result['pnl_by_route']['trend_breakout']['realized'], 0)
        self.assertNotEqual(result['pnl_by_route']['trend_breakout']['unrealized'], 0)

    def test_cash_start_does_not_inherit_prior_record_date_dividends(self):
        bundle=synthetic_bundle();start=bundle['calendar'][1]
        bundle['corporate_events']=[dict(symbol='600999.SH',announcement_date='2025-12-01',
            record_date=bundle['calendar'][0],ex_date=start,pay_date=start,cash_per_share=.5,shares_per_share=0)]
        result=run_bundle(bundle)
        self.assertEqual(result['final']['dividend_income'],0)
        records=[r for r in result['corporate_ledger'] if r['event']=='record' and r['symbol']=='600999.SH']
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['quantity'],0)
    def test_future_share_event_only_blocks_actual_record_date_holding(self):
        b=synthetic_bundle();b['unsupported_corporate_events']=[dict(symbol='600001.SH',record_date='2026-01-07',ex_date='2026-01-08',shares_per_share=.4)]
        r=run_bundle(b)
        self.assertTrue(r['fills']);self.assertFalse(r['positions'])
        b['unsupported_corporate_events'][0].update(record_date='2026-01-06',ex_date='2026-01-07')
        with self.assertRaisesRegex(ValueError,'实际持仓跨越'):run_bundle(b)


if __name__ == '__main__':
    unittest.main()
