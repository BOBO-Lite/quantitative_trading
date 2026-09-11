import unittest
from capital_utilization import AuditRules
from s2_strategy_rules import Policy

class CapitalSizingTests(unittest.TestCase):
    def test_observer_sizing_matches_original_over_grid(self):
        from e1_reentry_pair import ReentryRules
        for mode in ('FH','E1H'):
            for cost in (1.,1.5):
                for trend in (0,4,5):
                    a,b=AuditRules(mode),ReentryRules(mode);a.trend_days=b.trend_days=trend
                    for dd in (.0,.12,.1198,.105,.099,.149,.15):
                        for count in (0,1,2):
                            for price in (3.,10.,80.):
                                args=(price,price*.95,30000.,30000.,0.,'trend_breakout',dd,count,Policy(cost_multiplier=cost))
                                self.assertEqual(a.size_entry(*args),b.size_entry(*args))
    def test_diagnostic_does_not_override_risk_to_create_lot(self):
        r=AuditRules('FH');r.trend_days=5
        self.assertEqual(r.size_entry(1000,950,30000,30000,0,'trend_breakout',.12,0),0)
        self.assertEqual(r.sizing[-1]['reason'],'lot_or_risk_budget_zero')
    def test_minimum_is_distinguished_from_zero_risk_capacity(self):
        r=AuditRules('FH');r.trend_days=5
        q=r.size_entry(10,9.4,30000,30000,0,'trend_breakout',.12,0)
        self.assertEqual(q,0)
        self.assertGreater(r.sizing[-1]['raw_quantity'],0)
        self.assertEqual(r.sizing[-1]['reason'],'minimum_4000_only')
    def test_lower_minimum_does_not_relax_normal_state(self):
        a,b=AuditRules('FH',3000),AuditRules('FH')
        args=(10,9.5,15000,15000,0,'trend_breakout',0,0)
        self.assertEqual(a.size_entry(*args),b.size_entry(*args))
    def test_lower_minimum_accepts_risk_sized_recovery_position(self):
        from s2_strategy_rules import planned_loss
        a,b=AuditRules('FH',3000),AuditRules('FH');a.trend_days=b.trend_days=5
        args=(10,9.5,30000,30000,0,'trend_breakout',.12,0)
        q=a.size_entry(*args)
        self.assertGreater(q,0);self.assertEqual(b.size_entry(*args),0)
        self.assertGreaterEqual(q*10,3000);self.assertLess(q*10,4000)
        self.assertLessEqual(planned_loss(10,9.5,q),30000*Policy().risk_fraction/2)
    def test_lower_minimum_keeps_recovery_position_count(self):
        a=AuditRules('FH',3000);a.trend_days=5
        self.assertEqual(a.size_entry(10,9.6,30000,30000,4000,'trend_breakout',.12,1),0)

if __name__=='__main__':unittest.main()
