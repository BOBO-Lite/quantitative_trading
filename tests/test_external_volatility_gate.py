import unittest
import numpy as np
import pandas as pd
from external_volatility_gate import parse_factor_text,lagged_variance,fit_scale,metrics


class PublicFactorTests(unittest.TestCase):
    def test_percent_and_annual_rows(self):
        r=parse_factor_text('Header\n202401,2.0\n202402,-1.0\n2024,12.0',6,['Mom'])
        self.assertEqual(list(r.index),['202401','202402'])
        self.assertEqual(r.iloc[0,0],.02)

    def test_missing_sentinel_rejected(self):
        with self.assertRaises(AssertionError):parse_factor_text('202401,-99.99',6,['Mom'])

    def test_duplicate_rejected(self):
        with self.assertRaises(AssertionError):parse_factor_text('202401,1\n202401,2',6,['Mom'])

    def test_previous_month_only_across_year(self):
        dates=['201512%02d'%n for n in range(1,11)]+['201601%02d'%n for n in range(1,11)]
        daily=pd.Series(np.arange(20)/100,index=dates)
        v=lagged_variance(daily,['201601'])
        daily.loc[daily.index.str.startswith('201601')]=999
        self.assertEqual(v.iloc[0],lagged_variance(daily,['201601']).iloc[0])
        self.assertAlmostEqual(v.iloc[0],sum((x-.045)**2 for x in np.arange(10)/100))

    def test_holdout_does_not_change_scale(self):
        idx=['201510','201511','201512','201701']
        r=pd.Series([.01,-.02,.03,.04],index=idx)
        v=pd.Series([.001,.002,.003,.004],index=idx)
        c=fit_scale(r,v);r.loc['201701']=200;v.loc['201701']=100
        self.assertEqual(c,fit_scale(r,v))

    def test_total_compounding_and_initial_peak(self):
        r=metrics([-.1,.1],[1,1],[-.1,.1])
        self.assertAlmostEqual(r['monthly_close_max_drawdown_pct'],10)
        self.assertAlmostEqual(r['theoretical_total_cagr_pct'],(.99**6-1)*100)


if __name__=='__main__':unittest.main()
