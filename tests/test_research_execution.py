import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from research_execution import ReplayBroker
from s2_strategy_rules import Policy, fee


def bar(stamp, price=10., volume=10000, **changes):
    return dict(datetime=stamp, open=price, close=price, low=price,
                high_limit=11., low_limit=9., factor=1., volume=volume,
                is_paused=False) | changes


class ReplayBrokerTests(unittest.TestCase):
    def setUp(self):
        self.b = ReplayBroker()
        self.s = '600001.SH'
        self.t = '2026-01-05T09:45:00'
        self.b.on_minute(self.t, {self.s: bar(self.t)})

    def buy(self, qty=500, volume=10000):
        self.b.submit(self.s, qty, self.t, True, 1., 10.4)
        stamp = '2026-01-05T09:46:00'
        self.b.on_minute(stamp, {self.s: bar(stamp, volume=volume)})

    def test_next_minute_and_cash_costs(self):
        self.b.submit(self.s, 500, self.t, True, 1., 10.4)
        self.assertEqual(self.b.cash, 30000.)
        self.assertEqual(len(self.b.fills), 0)
        stamp = '2026-01-05T09:46:00'
        self.b.on_minute(stamp, {self.s: bar(stamp)})
        self.assertAlmostEqual(self.b.cash, 30000 - 5005 - 5.05005)
        self.assertEqual(self.b.fills[0]['fill_time'], stamp)

    def test_partial_fill_and_remainder_release(self):
        self.buy(volume=1200)  # 25%只能300股。
        self.assertEqual(self.b.positions[self.s].quantity, 300)
        self.assertEqual(self.b.orders[0]['status'], 'PARTIAL_REMAINDER_CANCELLED')
        self.assertEqual(self.b.reserved_cash, 0.)
        stamp = '2026-01-05T09:47:00'
        self.b.on_minute(stamp, {self.s: bar(stamp)})
        self.assertEqual(len(self.b.fills), 1)

    def test_missing_minute_expires_intent(self):
        self.b.submit(self.s, 500, self.t, True, 1., 10.4)
        stamp = '2026-01-05T09:47:00'
        self.b.on_minute(stamp, {self.s: bar(stamp)})
        self.assertEqual(len(self.b.fills), 0)
        self.assertEqual(self.b.orders[0]['status'], 'EXPIRED_MISSING_MINUTE')

    def test_t1_rejects_sell_and_next_day_realized_pnl_reconciles(self):
        self.buy()
        with self.assertRaises(ValueError):
            self.b.submit(self.s, 500, '2026-01-05T09:46:00', False, 1.)
        stamp = '2026-01-06T09:45:00'
        self.b.on_minute(stamp, {self.s: bar(stamp, 10.5)})
        self.b.submit(self.s, 500, stamp, False, 1.)
        stamp = '2026-01-06T09:46:00'
        self.b.on_minute(stamp, {self.s: bar(stamp, 10.5)})
        expected = 10.5 * .999 * 500 - fee(10.5 * .999 * 500, True) - 5005 - fee(5005)
        self.assertAlmostEqual(self.b.cash - 30000, expected)
        self.assertAlmostEqual(self.b.realized_pnl, expected)
        self.assertEqual(self.b.positions, {})

    def test_limit_up_cannot_fill(self):
        self.b.submit(self.s, 500, self.t, True, 1., 11.)
        stamp = '2026-01-05T09:46:00'
        self.b.on_minute(stamp, {self.s: bar(stamp, 11.)})
        self.assertEqual(len(self.b.fills), 0)

    def test_second_order_cannot_spend_reserved_cash(self):
        self.b.submit(self.s, 2000, self.t, True, 1., 10.4)
        with self.assertRaises(ValueError):
            self.b.submit('600002.SH', 1000, self.t, True, 1., 10.4)

    def test_duplicate_minute_cannot_repeat_fill(self):
        self.buy()
        with self.assertRaises(ValueError):
            self.b.on_minute('2026-01-05T09:46:00', {})
        self.assertEqual(len(self.b.fills), 1)

    def test_corporate_action_stops_unadjusted_ledger(self):
        self.buy()
        stamp = '2026-01-06T09:31:00'
        with self.assertRaises(ValueError):
            self.b.on_minute(stamp, {self.s: bar(stamp, 5., factor=2.)})

    def test_cost_stress_is_charged(self):
        self.b = ReplayBroker(policy=Policy(cost_multiplier=1.5))
        self.b.on_minute(self.t, {self.s: bar(self.t)})
        self.buy()
        self.assertAlmostEqual(self.b.cash, 30000 - 5007.5 - fee(5007.5, multiplier=1.5))

    def test_missing_held_quote_cannot_silently_mark_equity(self):
        self.buy()
        with self.assertRaises(ValueError):
            self.b.on_minute('2026-01-05T09:47:00', {})


if __name__ == '__main__':
    unittest.main()
