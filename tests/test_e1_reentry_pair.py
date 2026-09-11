import unittest
from e1_reentry_pair import ReentryRules
from s2_strategy_rules import Policy,planned_loss

class ReentryPairTests(unittest.TestCase):
    def size(self,r,dd=.12,count=0):return r.size_entry(10.,9.7,30000.,30000.,0.,'trend_breakout',dd,count)
    def test_r_requires_trend_streak_but_not_equity_recovery(self):
        r=ReentryRules('E1R');self.assertEqual(self.size(r),0)
        r.trend_days=5;q=self.size(r);self.assertGreater(q,0);self.assertLessEqual(q*10,6000)
    def test_f_and_e1_have_identical_recovery_sizing(self):
        for suffix in ('R','U'):
            a,b=ReentryRules('E1'+suffix),ReentryRules('F'+suffix);a.trend_days=b.trend_days=5
            for dd in (0.,.119,.12,.14,.15):self.assertEqual(self.size(a,dd),self.size(b,dd))
    def test_u_removes_soft_veto_but_not_hard_limit(self):
        r=ReentryRules('E1U');self.assertGreater(self.size(r,.12),0);self.assertEqual(self.size(r,.15),0)
    def test_r_remaining_risk_and_one_position(self):
        r=ReentryRules('FR');r.trend_days=5
        for dd in (.12,.14,.149):
            q=self.size(r,dd)
            if q:self.assertLessEqual(planned_loss(10,9.7,q,Policy()),30000*(.15-dd)/(1-dd)*.5)
        self.assertEqual(self.size(r,.12,1),0)
    def test_both_keep_hard_and_market_exits(self):
        p=dict(entry_date='2020-01-01',entry_price=10.,initial_r=.3,stop=9.7,highest_close=10.)
        bar=dict(datetime='2020-01-03T10:00:00',close=10.,low=10.,high=10.,symbol='600000.SH',is_paused=False,confirmation=dict(asof='2020-01-02',down=False,volume_ratio=1.,relative5=.1,two_below_ma10=False))
        for m in ('E1R','FR','E1U','FU'):
            r=ReentryRules(m);self.assertEqual(r.exit_reason(dict(p),bar,'trend_breakout',.15,2),'drawdown_hard_stop')
            self.assertEqual(r.exit_reason(dict(p),bar,'defensive_cash',0,2),'cash_defense')
    def test_latched_recovery_does_not_restore_at_1198(self):
        r=ReentryRules('FH');r.trend_days=5;self.assertGreater(self.size(r,.12),0)
        self.assertEqual(self.size(r,.1198,1),0);self.assertTrue(r.reentry_latched)
        self.assertLessEqual(self.size(r,.1198)*10,6000)
    def test_latched_recovery_restores_at_10_with_confirmed_trend(self):
        r=ReentryRules('E1H');r.trend_days=5;self.size(r,.12)
        self.assertGreater(self.size(r,.10,1),0);self.assertFalse(r.reentry_latched)
    def test_latch_does_not_clear_on_short_market_rebound(self):
        r=ReentryRules('FH');r.trend_days=5;self.size(r,.12);r.trend_days=4
        self.assertEqual(self.size(r,.099),0);self.assertTrue(r.reentry_latched)
    def test_same_latched_sizing_for_both_exit_signals(self):
        a,b=ReentryRules('E1H'),ReentryRules('FH');a.trend_days=b.trend_days=5
        for dd in (.12,.1198,.105,.099,.15):self.assertEqual(self.size(a,dd),self.size(b,dd))
if __name__=='__main__':unittest.main()
