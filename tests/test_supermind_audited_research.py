"""成交价格变化不应改写历史价格；旧报告适配器保持可复现。"""
import importlib.util
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / 'adapters/supermind_s1_audited_research.py'
spec = importlib.util.spec_from_file_location('audited', PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class AuditedResearchTests(unittest.TestCase):
    def setUp(self):
        self.c = dict(signal_close_raw=10., signal_close_adjusted=5.,
                      structure_low10_adjusted=4.8, atr20_adjusted=.1)

    def test_chasing_price_must_increase_structure_risk(self):
        plan = m._size_for_entry(self.c, 10., 30000., 30000., 0.)
        self.assertAlmostEqual(plan['structure_low_raw'], 9.6)
        self.assertAlmostEqual(plan['stop_distance'], .04)
        # 10.4买入距离真实结构低点9.6超过6%，必须拒绝。
        self.assertIsNone(m._size_for_entry(self.c, 10.4, 30000., 30000., 0.))

    def test_partial_fill_keeps_historical_structure_fixed(self):
        a = m._merge_entry_fill(self.c, 10., 100, None, '20260102')
        b = m._merge_entry_fill(self.c, 10.2, 100, a, '20260102')
        self.assertAlmostEqual(b['entry_price'], 10.1)
        self.assertAlmostEqual(b['initial_stop'], 9.6)
        self.assertAlmostEqual(b['atr20'], .2)

    def test_breakeven_covers_actual_cost_in_both_commission_branches(self):
        for qty in (100, 10000):
            entry = 10.
            exit_price = m._breakeven_price(entry, qty)
            purchase = entry * qty
            proceeds = exit_price * qty
            costs = max(5., purchase * .0002) + max(5., proceeds * .0002)
            costs += (purchase + proceeds) * .00001 + proceeds * .001
            self.assertAlmostEqual(proceeds - purchase - costs, 0., places=8)

    def test_cash_sizing_reserves_minimum_commission_and_transfer(self):
        plan = m._size_for_entry(self.c, 10., 30000., 5000., 0.)
        self.assertEqual(plan['quantity'], 400)
        self.assertLessEqual(m._buy_cash_required(10., plan['quantity']), 5000.)
        self.assertIsNone(m._size_for_entry(self.c, 10., 30000., 4000., 0.))

    def test_cash_sizing_accepts_exact_fee_inclusive_budget(self):
        budget = m._buy_cash_required(10., 500)
        self.assertAlmostEqual(budget, 5005.05)
        plan = m._size_for_entry(self.c, 10., 30000., budget, 0.)
        self.assertEqual(plan['quantity'], 500)

    def test_stop_risk_includes_costs_and_slippage(self):
        candidate = self.c | dict(structure_low10_adjusted=4.7, atr20_adjusted=.1)
        plan = m._size_for_entry(candidate, 10., 28800., 28800., 0.)
        self.assertEqual(plan['quantity'], 500)
        proceeds = 9.4 * .999 * 500
        loss = 5005.05 - proceeds + 5 + proceeds * .00101
        self.assertLessEqual(loss, 360.)

    def test_closing_ma10_includes_current_day_once(self):
        import pandas as pd
        previous = pd.DataFrame({'close': [10.] * 9})
        self.assertEqual(m._closing_ma10(previous, 11.), 10.1)
        with self.assertRaises(ValueError):
            m._closing_ma10(previous.iloc[:8], 11.)

    def test_two_r_trailing_cannot_skip_fee_inclusive_breakeven(self):
        import pandas as pd
        meta = dict(entry_date='20190416', entry_price=10., initial_r=.4,
                    effective_stop=9.6, highest_close=10., atr20=2., holding_days=0)
        state = SimpleNamespace(positions_meta={'600036.SH': meta}, pending_open_exit=set(), entry_rejections={})
        position = SimpleNamespace(amount=500)
        bar = SimpleNamespace(is_paused=False, close=10.8)
        with patch.object(m, 'g', state, create=True), \
             patch.object(m, 'get_datetime', return_value=pd.Timestamp('2019-04-17 15:30'), create=True), \
             patch.object(m, '_portfolio_values', return_value=(30000., 20000., {'600036.SH': position})), \
             patch.object(m, 'get_current', return_value={'600036.SH': bar}, create=True), \
             patch.object(m, 'history', return_value=pd.DataFrame({'close': [9.] * 9}), create=True), \
             patch.object(m, 'log', create=True):
            m.after_trading(None)
        self.assertGreaterEqual(meta['effective_stop'] * .999, m._breakeven_price(10., 500))

    def test_tighter_order_cap_preserves_eligible_low_price_entry(self):
        self.assertIsNone(m._size_for_entry(self.c, 10.4, 30000., 30000., 0.))
        cap = m._admissible_entry_cap(self.c)
        self.assertEqual(cap, 10.21)
        plan = m._size_for_entry(self.c, cap, 30000., 30000., 0.)
        self.assertIsNotNone(plan)
        self.assertLessEqual(plan['stop_distance'], .06)
        self.assertLessEqual(m._planned_loss(cap, plan['planned_stop'], plan['quantity']), 375.)

    def test_market_gate_retains_held_symbol_subscription(self):
        import pandas as pd
        state = SimpleNamespace(subscribed={'600001.SH', '600002.SH'},
                                positions_meta={'600001.SH': {}}, candidates={})
        with patch.object(m, 'g', state, create=True), \
             patch.object(m, 'get_datetime', return_value=pd.Timestamp('2026-01-06'), create=True), \
             patch.object(m, 'get_all_securities', return_value=pd.DataFrame(index=['600001.SH']), create=True), \
             patch.object(m, 'history', return_value=pd.DataFrame({'close': range(200, 135, -1)}), create=True), \
             patch.object(m, 'unsubscribe', create=True) as unsubscribe, \
             patch.object(m, 'subscribe', create=True), \
             patch.object(m, 'log', create=True):
            m.before_trading(None)
        self.assertEqual(state.subscribed, {'600001.SH'})
        unsubscribe.assert_called_once_with('600002.SH')

    def test_open_and_vwap_exclude_stale_open_bar(self):
        import pandas as pd
        self.assertIsNone(m._accumulate_session_bar(None, pd.Timestamp('2019-04-17 09:30'), 36., 802025., 28872900.))
        first = m._accumulate_session_bar(None, pd.Timestamp('2019-04-17 09:31'), 35.89, 100., 3590.)
        second = m._accumulate_session_bar(first, pd.Timestamp('2019-04-17 09:32'), 36., 300., 10800.)
        self.assertEqual(second['open'], 35.89)
        self.assertAlmostEqual(second['turnover'] / second['volume'], 35.975)
        self.assertNotEqual(second['turnover'] / second['volume'], 36.)

    def test_missing_first_or_intermediate_minute_blocks_entry(self):
        import pandas as pd
        self.assertIsNone(m._accumulate_session_bar(None, pd.Timestamp('2019-04-17 09:45'), 36., 100., 3600.))
        first = m._accumulate_session_bar(None, pd.Timestamp('2019-04-17 09:31'), 36., 100., 3600.)
        self.assertIsNone(m._accumulate_session_bar(first, pd.Timestamp('2019-04-17 09:33'), 36., 100., 3600.))
        duplicate = m._accumulate_session_bar(first, pd.Timestamp('2019-04-17 09:31'), 36., 100., 3600.)
        self.assertEqual(duplicate['volume'], 100.)

if __name__ == '__main__':
    unittest.main()
