"""受控回调验证持仓生命周期；不是平台撮合验收。"""
import unittest
from contextlib import ExitStack
from types import SimpleNamespace as NS
from unittest.mock import patch
import pandas as pd
from test_supermind_audited_research import m


class ExitLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.symbol = '600036.SH'
        self.meta = dict(entry_date='20190417', entry_price=10., initial_r=.4,
                         effective_stop=9.6, highest_close=10., atr20=.2, holding_days=0)
        self.position = NS(amount=500, available_amount=500)
        self.state = NS(positions_meta={self.symbol: self.meta}, pending_open_exit=set(),
                        entry_rejections={}, exit_pending_symbols=set(), exit_intents={},
                        exit_orders={}, entry_orders={}, candidates={})
        self.bar = NS(is_paused=False, close=10.5, low=10.4, low_limit=9.)
        self.now = pd.Timestamp('2019-04-17 15:30')
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in [('g', self.state), ('log', NS(info=lambda *a: None))]:
            self.stack.enter_context(patch.object(m, name, value, create=True))
        self.stack.enter_context(patch.object(m, 'get_datetime', side_effect=lambda: self.now, create=True))
        self.stack.enter_context(patch.object(m, '_portfolio_values',
            side_effect=lambda _: (30000., 20000., {self.symbol: self.position})))
        self.stack.enter_context(patch.object(m, 'get_current',
            side_effect=lambda _: {self.symbol: self.bar}, create=True))

    def test_entry_close_updates_next_day_protection_once(self):
        m.after_trading(None)
        m.after_trading(None)
        self.assertEqual(self.meta['holding_days'], 1)
        self.assertGreater(self.meta['effective_stop'], 10.)
        with patch.object(m, 'order', create=True) as order:
            self.now = pd.Timestamp('2019-04-17 14:00')
            self.bar.low = 9.
            m.handle_bar(None, {})
            order.assert_not_called()  # 同日仍受 T+1 约束。

    def test_eighth_day_schedules_time_exit(self):
        self.meta['holding_days'] = 7
        self.now = pd.Timestamp('2019-04-26 15:30')
        self.bar.close = 10.1
        m.after_trading(None)
        self.assertIn(self.symbol, self.state.pending_open_exit)

    def test_paused_twentieth_day_still_schedules_exit(self):
        self.meta['holding_days'] = 19
        self.bar.is_paused = True
        m.after_trading(None)
        self.assertEqual(self.meta['holding_days'], 20)
        self.assertIn(self.symbol, self.state.pending_open_exit)

    def test_rejected_open_exit_retries_without_losing_intent(self):
        self.state.pending_open_exit.add(self.symbol)
        self.now = pd.Timestamp('2019-04-18 09:31')
        with patch.object(m, 'order', side_effect=[None, 'retry-id'], create=True) as order:
            m.open_auction(None, {})
            self.assertIn(self.symbol, self.state.pending_open_exit)
            m.handle_bar(None, {})
            m.handle_bar(None, {})
            self.assertEqual(order.call_count, 2)  # 未终结委托不能重复提交。

    def test_unavailable_shares_keep_scheduled_exit(self):
        self.state.pending_open_exit.add(self.symbol)
        self.position.available_amount = 0
        with patch.object(m, 'order', create=True) as order:
            m.open_auction(None, {})
            order.assert_not_called()
        self.assertIn(self.symbol, self.state.pending_open_exit)

    def test_partial_cancel_retries_only_remaining_shares_then_cleans_up(self):
        self.state.pending_open_exit.add(self.symbol)
        self.state.exit_pending_symbols.add(self.symbol)
        self.state.exit_intents[self.symbol] = {}
        self.position.amount = self.position.available_amount = 200
        self.now = pd.Timestamp('2019-04-18 09:32')
        status = NS(FILLED='filled', REJECTED='rejected', CANCELLED='cancelled')
        with patch.object(m, 'ORDER_STATUS', status, create=True), \
             patch.object(m, 'SIDE', NS(BUY='buy', SELL='sell'), create=True), \
             patch.object(m, 'order', return_value='remaining', create=True) as order:
            m.on_order(None, NS(order_id='first', symbol=self.symbol,
                               order_type='SHORT', status='cancelled'))
            m.handle_bar(None, {})
            order.assert_called_once_with(self.symbol, -200)
            self.position.amount = self.position.available_amount = 0
            m.on_trade(None, NS(order_id='remaining', order_book_id=self.symbol, side='sell'))
        self.assertNotIn(self.symbol, self.state.positions_meta)
        self.assertNotIn(self.symbol, self.state.pending_open_exit)


if __name__ == '__main__':
    unittest.main()
