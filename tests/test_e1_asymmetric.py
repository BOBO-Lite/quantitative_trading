import unittest
from s2_strategy_rules import Policy,planned_loss
from e1_asymmetric import AsymmetricRules

class AsymmetricTests(unittest.TestCase):
    def setUp(self):
        self.p=dict(entry_date='2020-01-02',entry_price=10.,initial_r=.5,stop=9.5,highest_close=12.,known_ma10=10.8)
        self.b=dict(datetime='2020-02-03T15:00:00',close=11.5,low=11.3,is_paused=False)
    def test_winners_extend_only_after_profit_and_known_trend(self):
        r=AsymmetricRules('W')
        self.assertIsNone(r.exit_reason(self.p,self.b,'trend_breakout',0,20,True))
        self.assertEqual(r.exit_reason(self.p,self.b,'trend_breakout',0,40,True),'time_exit')
        self.b['close']=10.9
        self.assertEqual(r.exit_reason(self.p,self.b,'trend_breakout',0,20,True),'time_exit')
    def test_profit_extension_keeps_protective_and_market_exits(self):
        r=AsymmetricRules('W');self.p['stop']=11.6
        self.assertEqual(r.exit_reason(self.p,self.b,'trend_breakout',0,20,True),'close_confirmed_stop')
        self.assertEqual(r.exit_reason(self.p,self.b,'defensive_cash',0,20,True),'cash_defense')
    def test_loss_signal_is_close_only_and_first_five_sessions(self):
        r=AsymmetricRules('L');self.p['stop']=9.;self.b.update(close=9.75,low=9.7)
        self.assertEqual(r.exit_reason(self.p,self.b,'trend_breakout',0,5,True),'early_half_r_loss')
        self.assertIsNone(r.exit_reason(self.p,self.b,'trend_breakout',0,6,True))
        self.assertIsNone(r.exit_reason(self.p,self.b,'trend_breakout',0,5,False))
    def test_recovery_removes_wait_but_keeps_risk_and_exposure_limits(self):
        r=AsymmetricRules('R')
        args=(10.,9.7,30000.,30000.,0.,'trend_breakout',.12,0)
        self.assertEqual(r.size_entry(*args),0)
        for _ in range(5):r.research_regime(12.,11.,10.)
        q=r.size_entry(*args)
        self.assertGreater(q,0);self.assertLessEqual(q*10,6000)
        self.assertLessEqual(planned_loss(10.,9.7,q,Policy()),30000*.0125/2)
        self.assertEqual(r.size_entry(10.,9.7,30000,30000,0,'trend_breakout',.15,0),0)
        self.assertEqual(r.size_entry(10.,9.7,30000,25000,5000,'trend_breakout',.12,1),0)
    def test_recovery_budget_shuts_down_near_hard_stop(self):
        r=AsymmetricRules('R');r.trend_days=5
        self.assertEqual(r.size_entry(10.,9.7,30000,30000,0,'trend_breakout',.1499,0),0)
    def test_extension_bridges_previous_ma_on_cash_dividend(self):
        self.p.update(known_ma10=11.2,known_ma10_stop_reference=9.5,stop=9.1,entry_price=9.68)
        self.b.update(close=10.85,low=10.8)
        self.assertIsNone(AsymmetricRules('W').exit_reason(self.p,self.b,'trend_breakout',0,20,True))

if __name__=='__main__':unittest.main()
