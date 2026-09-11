import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from recovery_research import RecoveryRules
from recovery_research import check_supplement
from s2_strategy_rules import planned_loss,Policy
from types import SimpleNamespace
from unittest.mock import patch

class RecoveryTests(unittest.TestCase):
    def test_cross_year_stock_requires_corporate_coverage(self):
        cache=SimpleNamespace(daily={'600001.SH':{}},minutes={('600001.SH','2020-01-02'):[]})
        with patch('recovery_research.Path.read_text',return_value='{"requests": []}'):
            with self.assertRaisesRegex(ValueError,'公司行动范围缺口'):check_supplement(cache,cache)
    def test_prior_year_does_not_require_future_corporate_coverage(self):
        cache=SimpleNamespace(daily={'600001.SH':{}},minutes={('600001.SH','2019-01-02'):[]})
        with patch('recovery_research.Path.read_text',return_value='{"requests": []}'):
            check_supplement(cache,cache)
    def trend(self,r,n):
        for _ in range(n):r.research_regime(12,11,10,0,0)
    def size(self,r,dd=.13,count=0):
        return r.size_entry(10.,9.7,30000.,30000.,0.,'trend_breakout',dd,count)
    def test_wait_twenty_days_before_recovery(self):
        r=RecoveryRules('R1');self.trend(r,1);self.assertEqual(self.size(r),0)
        self.trend(r,19);self.assertEqual(self.size(r),0)
        self.trend(r,1);qty=self.size(r)
        self.assertGreater(qty,0);self.assertLessEqual(qty*10,6000)
        self.assertLessEqual(planned_loss(10,9.7,qty),30000*.00625)
    def test_five_consecutive_trend_days_required(self):
        r=RecoveryRules('R1');self.trend(r,1);self.size(r)
        self.trend(r,20);r.research_regime(9,11,10,0,0)
        self.trend(r,4);self.assertEqual(self.size(r),0)
        self.trend(r,1);self.assertGreater(self.size(r),0)
    def test_small_remaining_drawdown_budget_blocks_minimum_order(self):
        r=RecoveryRules('R1');self.trend(r,1);self.size(r);self.trend(r,20)
        self.assertEqual(self.size(r,.149),0);self.assertEqual(self.size(r,.15),0)
        self.assertEqual(self.size(r,.13,1),0)
    def test_normal_recovery_rearms_cooldown(self):
        r=RecoveryRules('R1');self.trend(r,1);self.size(r);self.trend(r,20)
        self.assertGreater(self.size(r),0)
        self.size(r,.119);self.assertIsNone(r.pause_day)
        self.assertEqual(self.size(r,.13),0)
    def test_defensive_market_still_blocks_entry(self):
        r=RecoveryRules('R2')
        self.assertFalse(r.select_signal({},'defensive_cash'))
        self.assertEqual(r.size_entry(10,9.7,30000,30000,0,'defensive_cash',0,0),0)
    def test_market_exit_removed_but_price_time_and_hard_stop_retained(self):
        r=RecoveryRules('R2');p=dict(entry_date='2020-01-02',stop=9.5,entry_price=10)
        bar=dict(datetime='2020-01-03T15:00:00',is_paused=False,low=9.6,close=9.7)
        self.assertIsNone(r.exit_reason(p,bar,'defensive_cash',0,2,True))
        self.assertEqual(r.exit_reason(p,bar,'defensive_cash',.15,2,True),'drawdown_hard_stop')
        self.assertEqual(r.exit_reason(p,bar,'defensive_cash',0,20,True),'time_exit')
        bar['low']=bar['close']=9.5
        self.assertEqual(r.exit_reason(p,bar,'defensive_cash',0,2,True),'close_confirmed_stop')

if __name__=='__main__':unittest.main()
