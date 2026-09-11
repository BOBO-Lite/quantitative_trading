import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import s2_strategy_rules as s


def snapshot():
    return dict(symbol='600001.SH', date='2026-01-05', is_st=False, is_paused=False,
                event_clear=True, pit_verified=True, listing_bars=150, amount20=8e7,
                close=10.2, ma20=10., ma60=9.9, ma20_previous=9.98,
                previous_close=10., prior_breakout_close=10.1, volume_ratio=1.4,
                close_location=.8, compression10=.1, rs_percentile=.9, rsi14=40.,
                industry_asof='2025-12-31', industry_percentile=.9, industry_return20=.1,
                raw_close=10., raw_high=10.1, factor=1.)


def minute():
    return dict(datetime='2026-01-06T09:46:00', open=10.2, close=10.2, low=10.15,
                high_limit=11., low_limit=9., volume=10000, is_paused=False, factor=1.)


class FourStrategyTests(unittest.TestCase):
    def test_dividend_adjusted_breakeven_uses_actual_cash_cost(self):
        pos = dict(entry_price=9.84, initial_r=.4, quantity=500, stop=9.4,
                   route='trend_breakout', breakeven_cost=4935.)
        result = s.close_protection(pos, 10.3, 9.7, .3)
        # 触发价扣预设卖出滑点与卖出费用后必须覆盖真实净现金成本。
        proceeds = result['stop'] * .999 * 500
        self.assertAlmostEqual(proceeds-s.fee(proceeds,sell=True),4935.,places=7)
        with self.assertRaises(ValueError):
            s.close_protection(pos | {'breakeven_cost':float('nan')},10.3,9.7,.3)

    def test_trend_signal(self):
        self.assertTrue(s.select_signal(snapshot(), 'trend_breakout'))

    def test_range_requires_rebound_not_falling_knife(self):
        row = snapshot() | dict(close=9.7, previous_close=9.6)
        self.assertTrue(s.select_signal(row, 'range_mean_reversion'))
        row['previous_close'] = 9.8
        self.assertFalse(s.select_signal(row, 'range_mean_reversion'))

    def test_rotation_requires_prior_industry_mapping(self):
        row = snapshot()
        self.assertTrue(s.select_signal(row, 'industry_rotation'))
        row['industry_asof'] = row['date']
        self.assertFalse(s.select_signal(row, 'industry_rotation'))

    def test_cash_never_selects_or_sizes(self):
        self.assertFalse(s.select_signal(snapshot(), 'defensive_cash'))
        self.assertEqual(s.size_entry(10, 9.6, 30000, 30000, 0, 'defensive_cash', 0, 0), 0)

    def test_missing_events_and_pit_fail_closed(self):
        for key in ('event_clear', 'pit_verified', 'is_st', 'is_paused'):
            row = snapshot()
            row.pop(key)
            self.assertFalse(s.select_signal(row, 'trend_breakout'))

    def test_forbidden_boards(self):
        for symbol in ('300001.SZ', '301001.SZ', '688001.SH', '689001.SH', '920001.BJ'):
            self.assertFalse(s.eligible(snapshot() | dict(symbol=symbol)))

    def test_declining_market_is_not_range(self):
        self.assertEqual(s.research_regime(7770.73, 7868.6179, 8077.3819, -.005999, -.024701), 'defensive_cash')

    def test_all_environment_routes(self):
        for args, expected in [((110, 105, 100, .01, .1), 'trend_breakout'),
                               ((100, 100, 100, 0, 0), 'range_mean_reversion'),
                               ((108, 110, 100, -.01, .05), 'industry_rotation'),
                               ((90, 95, 100, -.01, -.1), 'defensive_cash')]:
            self.assertEqual(s.research_regime(*args), expected)

    def test_nan_fails_closed(self):
        self.assertEqual(s.research_regime(float('nan'), 100, 100, 0, 0), 'defensive_cash')
        self.assertFalse(s.select_signal(snapshot() | dict(close=float('nan')), 'trend_breakout'))

    def test_fee_and_cash_boundaries(self):
        self.assertAlmostEqual(s.fee(5000), 5.05)
        self.assertAlmostEqual(s.fee(5000, True), 7.55)
        self.assertEqual(s.size_entry(10, 9.6, 30000, 5000, 0, 'trend_breakout', 0, 0), 400)

    def test_risk_and_position_limits(self):
        for dd, count in ((.12, 0), (.15, 0), (0, 3)):
            self.assertEqual(s.size_entry(10, 9.6, 30000, 30000, 0, 'trend_breakout', dd, count), 0)
        self.assertEqual(s.size_entry(10, 9.3, 30000, 30000, 0, 'trend_breakout', 0, 0), 0)

    def test_stop_budget_includes_round_trip_fees_and_exit_slippage(self):
        # 600股、6%止损价差恰好360元；计入成本后必须降至500股。
        for multiplier in (1., 1.5):
            policy = s.Policy(cost_multiplier=multiplier)
            qty = s.size_entry(10., 9.4, 28800., 28800., 0., 'trend_breakout', 0., 0, policy)
            self.assertEqual(qty, 500)
            exit_value = 9.4 * (1 - .001 * multiplier) * qty
            loss = 10 * qty - exit_value + s.fee(10 * qty, multiplier=multiplier)
            loss += s.fee(exit_value, True, multiplier)
            self.assertLessEqual(loss, 28800 * .0125)

    def test_negative_account_state_does_not_expand_position_room(self):
        self.assertEqual(s.size_entry(10, 9.6, 30000, 30000, -1000, 'trend_breakout', 0, 0), 0)

    def test_entry_uses_next_day_and_confirmed_minute(self):
        self.assertTrue(s.entry_confirmed(snapshot(), minute(), 'trend_breakout', 10., 10.1))
        self.assertFalse(s.entry_confirmed(snapshot(), minute() | dict(datetime='2026-01-05T09:46:00'), 'trend_breakout', 10., 10.1))

    def test_ex_rights_entry_rejected(self):
        self.assertFalse(s.entry_confirmed(snapshot(), minute() | dict(factor=2), 'trend_breakout', 10., 10.1))

    def test_fill_cannot_use_signal_bar_or_late_bar(self):
        self.assertIsNone(s.next_open_fill('2026-01-06T09:46:00', minute(), True))
        self.assertIsNone(s.next_open_fill('2026-01-06T09:44:00', minute(), True))
        self.assertAlmostEqual(s.next_open_fill('2026-01-06T09:45:00', minute(), True), 10.2102)

    def test_limits_and_price_cap(self):
        for buy, price in ((True, 11.), (False, 9.)):
            self.assertIsNone(s.next_open_fill('2026-01-06T09:45:00', minute() | dict(open=price), buy))
        self.assertIsNone(s.next_open_fill('2026-01-06T09:45:00', minute(), True, 10.2))

    def test_cost_stress_worsens_fill_and_fees(self):
        stress = s.Policy(cost_multiplier=1.5)
        self.assertGreater(s.fee(5000, multiplier=1.5), s.fee(5000))
        self.assertGreater(s.next_open_fill('2026-01-06T09:45:00', minute(), True, policy=stress),
                           s.next_open_fill('2026-01-06T09:45:00', minute(), True))

    def test_t1_and_cash_exit(self):
        pos = dict(entry_date='2026-01-06', stop=10.3, route='trend_breakout')
        self.assertIsNone(s.exit_reason(pos, minute(), 'defensive_cash', .2, 1))
        pos['entry_date'] = '2026-01-05'
        self.assertEqual(s.exit_reason(pos, minute(), 'defensive_cash', 0, 1), 'cash_defense')

    def test_mean_reversion_exit_at_close_only(self):
        pos = dict(entry_date='2026-01-05', stop=9.5, route='range_mean_reversion',
                   target_ma20=10., entry_price=9.8, initial_r=.3)
        self.assertIsNone(s.exit_reason(pos, minute(), 'range_mean_reversion', 0, 1))
        self.assertEqual(s.exit_reason(pos, minute(), 'range_mean_reversion', 0, 1, True), 'mean_reversion_target')

    def test_protection_preserves_stop_and_covers_costs(self):
        pos = dict(entry_price=10., initial_r=.4, quantity=500, stop=9.6, route='trend_breakout')
        updated = s.close_protection(pos, 10.5, 10., .2)
        fill = updated['stop'] * .999
        net = (fill - 10.) * 500 - s.fee(5000) - s.fee(fill * 500, True)
        self.assertAlmostEqual(net, 0., places=7)
        self.assertEqual(pos['stop'], 9.6)
        after = s.close_protection(updated, 10.3, 10., .2)
        self.assertGreaterEqual(after['stop'], updated['stop'])

    def test_trailing_and_rotation_exit(self):
        pos = dict(entry_date='2026-01-05', entry_price=10., initial_r=.4,
                   quantity=500, stop=9.6, route='industry_rotation')
        updated = s.close_protection(pos, 11., 10.5, .2)
        self.assertAlmostEqual(updated['stop'], 10.6)
        self.assertEqual(s.exit_reason(pos, minute(), 'industry_rotation', 0, 1, True, True), 'industry_strength_lost')

    def test_invalid_fill_and_policy_rejected(self):
        self.assertIsNone(s.next_open_fill('2026-01-06T09:45:00', minute() | dict(volume=float('nan')), True))
        with self.assertRaises(ValueError):
            s.Policy(risk_fraction=.03)
        with self.assertRaises(ValueError):
            s.Policy(cost_multiplier=.5)

    def test_three_active_routes_follow_confirm_fill_t1_exit_chain(self):
        for route in s.ROUTES[:3]:
            row = snapshot()
            if route == 'range_mean_reversion':
                row.update(close=9.7, previous_close=9.6)
            self.assertTrue(s.select_signal(row, route))
            confirm = minute() | dict(close=10.15)
            self.assertTrue(s.entry_confirmed(row, confirm, route, 10., 10.1))
            fill_bar = minute() | dict(datetime='2026-01-06T09:47:00', open=10.15)
            price = s.next_open_fill(confirm['datetime'], fill_bar, True, 10.2)
            qty = s.size_entry(price, price * .96, 30000, 30000, 0, route, 0, 0)
            self.assertGreater(qty, 0)
            pos = dict(entry_date='2026-01-06', entry_price=price, stop=price * .96,
                       initial_r=price * .04, quantity=qty, route=route, target_ma20=10.)
            self.assertIsNone(s.exit_reason(pos, fill_bar, 'defensive_cash', 0, 0))
            next_day = minute() | dict(datetime='2026-01-07T09:46:00')
            self.assertEqual(s.exit_reason(pos, next_day, 'defensive_cash', 0, 1), 'cash_defense')
            sell = s.next_open_fill(next_day['datetime'], next_day | dict(datetime='2026-01-07T09:47:00'), False)
            self.assertIsNotNone(sell)


if __name__ == '__main__':
    unittest.main()
