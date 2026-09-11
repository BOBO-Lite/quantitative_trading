"""退出模式的经济行为边界，不运行真实交易。"""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from exit_research import ExitRules

class ExitRulesTests(unittest.TestCase):
    def setUp(self):
        self.position=dict(entry_date='2019-01-02',entry_price=10.,stop=9.5,highest_close=10.)
        self.bar=dict(datetime='2019-01-03T15:00:00',low=9.4,close=9.6,is_paused=False)
    def test_intraday_dip_recovers_only_original_exits(self):
        self.assertEqual(ExitRules('E0').exit_reason(self.position,self.bar,'trend_breakout',0,2),'protective_stop')
        for name in ('E1','E2'):
            self.assertIsNone(ExitRules(name).exit_reason(self.position,self.bar,'trend_breakout',0,2))
            self.assertIsNone(ExitRules(name).exit_reason(self.position,self.bar,'trend_breakout',0,2,True))
    def test_close_at_stop_requires_close_confirmation(self):
        self.bar['close']=9.5
        for name in ('E1','E2'):
            self.assertIsNone(ExitRules(name).exit_reason(self.position,self.bar,'trend_breakout',0,2))
            self.assertEqual(ExitRules(name).exit_reason(self.position,self.bar,'trend_breakout',0,2,True),'close_confirmed_stop')
    def test_cash_defense_and_hard_drawdown_are_not_delayed(self):
        for name in ('E1','E2'):
            self.assertEqual(ExitRules(name).exit_reason(self.position,self.bar,'defensive_cash',0,2),'cash_defense')
            self.assertEqual(ExitRules(name).exit_reason(self.position,self.bar,'trend_breakout',.15,2),'drawdown_hard_stop')
    def test_recovered_dip_does_not_mask_time_exit(self):
        self.assertEqual(ExitRules('E1').exit_reason(self.position,self.bar,'trend_breakout',0,20,True),'time_exit')
    def test_wider_trail_cannot_loosen_existing_stop(self):
        wide=ExitRules('E2').close_protection(self.position,10.2,10.,.3)
        tight=ExitRules('E1').close_protection(self.position,10.2,10.,.3)
        self.assertEqual(wide['stop'],9.5);self.assertAlmostEqual(tight['stop'],9.6)
    def test_buy_day_no_intraday_exit(self):
        self.bar['datetime']='2019-01-02T10:00:00'
        self.assertIsNone(ExitRules('E1').exit_reason(self.position,self.bar,'defensive_cash',.2,0))

if __name__=='__main__':unittest.main()
