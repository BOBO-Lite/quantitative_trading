import unittest
import numpy as np
import pandas as pd
from fh_volatility import schedule_from_prices,VolatilityRules
from e1_reentry_pair import ReentryRules
from s2_strategy_rules import Policy,planned_loss

class VolatilityAdaptationTests(unittest.TestCase):
    def test_future_prices_cannot_change_past_weights_or_calibration(self):
        dates=pd.bdate_range('2017-12-29','2020-12-31').strftime('%Y-%m-%d')
        prices=dict(zip(dates,100*np.cumprod(1+.0002+.008*np.sin(np.arange(len(dates))))))
        original=schedule_from_prices(prices)
        altered={d:p*(1.5 if d>='2020-07-01' else 1) for d,p in prices.items()}
        changed=schedule_from_prices(altered)
        self.assertEqual(original['c'],changed['c']);self.assertEqual(original['constant'],changed['constant'])
        for m in original['monthly']:
            if m<='2020-07':self.assertEqual(original['monthly'][m],changed['monthly'][m])
        self.assertTrue(all(0<w<=1 for w in original['monthly'].values()))

    def test_reduced_risk_preserves_lots_and_budget(self):
        r=VolatilityRules('DYNAMIC',['2020-01-02'],{'monthly':{'2020-01':.5},'constant':.5})
        r.research_regime(12,11,10,1,1)
        p=Policy();q=r.size_entry(10,9.5,30000,30000,0,'trend_breakout',0,0,p)
        self.assertEqual(q%100,0)
        if q:self.assertLessEqual(planned_loss(10,9.5,q,p),30000*p.risk_fraction*.5)

    def test_baseline_sizing_matches(self):
        a=ReentryRules('FH');b=VolatilityRules('BASE',['2020-01-02'],{})
        for r in (a,b):r.research_regime(12,11,10,1,1)
        for dd in (0,.12,.099):
            args=(10,9.5,30000,30000,0,'trend_breakout',dd,0,Policy())
            self.assertEqual(a.size_entry(*args),b.size_entry(*args))

    def test_pre2020_budget_is_unchanged(self):
        r=VolatilityRules('DYNAMIC',['2019-12-31'],{'monthly':{},'constant':.3})
        r.research_regime(12,11,10,1,1);self.assertEqual(r.weight,1)

if __name__=='__main__':unittest.main()
