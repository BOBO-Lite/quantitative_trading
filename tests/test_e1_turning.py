import unittest
from unittest.mock import patch
from e1_turning_rules import TurningRules

class TurningTests(unittest.TestCase):
    def position(self):return dict(entry_date='2020-01-02',entry_price=10.,initial_r=.5,stop=9.,highest_close=10.,known_ma10=10.,known_ma10_stop_reference=9.,turning_atr=.4)
    def bar(self,price,stamp='2020-01-03T10:00:00'):return dict(datetime=stamp,close=price,low=price-.01,high=price+.01,is_paused=False)
    def test_profit_peak_only_uses_completed_close(self):
        r=TurningRules('P');p=self.position();b=self.bar(12.);b['high']=20.
        self.assertIsNone(r.exit_reason(p,b,'trend_breakout',0,1))
        self.assertEqual(p['turning_peak'],12.)
        self.assertEqual(r.exit_reason(p,self.bar(11.59,'2020-01-03T10:01:00'),'trend_breakout',0,1),'earned_profit_reversal')
    def test_profit_protection_requires_earned_three_r(self):
        r=TurningRules('P');p=self.position()
        r.exit_reason(p,self.bar(11.),'trend_breakout',0,1)
        self.assertIsNone(r.exit_reason(p,self.bar(10.5),'trend_breakout',0,1))
    def test_loss_rebound_arms_before_atr_is_initialized(self):
        r=TurningRules('Q');p=self.position();p.pop('turning_atr')
        self.assertIsNone(r.exit_reason(p,self.bar(9.3,'2020-01-02T15:00:00'),'trend_breakout',0,1,True))
        self.assertIn('rebound_armed_at',p);p['turning_atr']=.4
        self.assertEqual(r.exit_reason(p,self.bar(9.71),'trend_breakout',0,1),'weak_rebound_exit')
    def test_reclaim_entry_disarms_failed_rebound(self):
        r=TurningRules('Q');p=self.position()
        r.exit_reason(p,self.bar(9.3),'trend_breakout',0,1)
        self.assertIsNone(r.exit_reason(p,self.bar(10.1,'2020-01-03T10:01:00'),'trend_breakout',0,1))
        self.assertNotIn('rebound_armed_at',p)
    def test_original_risk_exit_has_priority(self):
        r=TurningRules('PQ');p=self.position();b=self.bar(12.)
        self.assertEqual(r.exit_reason(p,b,'defensive_cash',0,2),'cash_defense')
        self.assertEqual(r.exit_reason(p,b,'trend_breakout',.15,2),'drawdown_hard_stop')
    def test_pullback_must_follow_first_confirmation(self):
        r=TurningRules('B');signal={'symbol':'600000.SH'};b=self.bar(10.6);b['low']=10.
        with patch('e1_turning_rules.base.entry_confirmed',return_value=True):
            self.assertFalse(r.entry_confirmed(signal,b,'trend_breakout',10.,10.3))
            b.update(datetime='2020-01-03T10:01:00',low=10.4)
            self.assertFalse(r.entry_confirmed(signal,b,'trend_breakout',10.,10.4))
            b.update(datetime='2020-01-03T10:02:00',low=10.2)
            self.assertTrue(r.entry_confirmed(signal,b,'trend_breakout',10.,10.4))

if __name__=='__main__':unittest.main()
