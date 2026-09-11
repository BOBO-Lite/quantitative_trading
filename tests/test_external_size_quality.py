import unittest
from copy import deepcopy
from external_size_quality import DataGap, available_version, quarterly_metrics, rank_candidates


class SizeQualityTests(unittest.TestCase):
    def setUp(self):
        self.old = dict(symbol='000063.SZ', period='2018-03-31', published='2018-04-28',
                        parent_income_ytd=1687020000, operating_cash_ytd=-171149000,
                        parent_equity=39580282000, assets=139138702000, liabilities=95016015000)
        self.new = dict(self.old, published='2018-07-28', parent_income_ytd=-5407237000,
                        parent_equity=32363195000, assets=137876425000, liabilities=100970825000)
        self.prev = dict(self.old, period='2017-12-31', published='2018-03-16',
                         parent_equity=40968202000)

    def test_future_revision_not_selected(self):
        self.assertEqual(available_version([self.old,self.new],'000063.SZ','2018-03-31','2018-05-02'),self.old)

    def test_revision_used_after_publication(self):
        self.assertEqual(available_version([self.old,self.new],'000063.SZ','2018-03-31','2018-07-30'),self.new)

    def test_no_report_before_announcement(self):
        with self.assertRaises(DataGap): available_version([self.old],'000063.SZ','2018-03-31','2018-04-27')

    def test_ambiguous_same_date_versions_block(self):
        with self.assertRaises(DataGap):
            available_version([self.old,dict(self.old,assets=1)],'000063.SZ','2018-03-31','2018-05-02')

    def test_original_zte_arithmetic(self):
        r=quarterly_metrics(self.old,self.prev,'2018-05-02')
        self.assertAlmostEqual(r['roe_quarter_pct'],4.18883116409739)
        self.assertEqual(r['operating_cash_quarter'],-171149000)

    def test_restatement_reproduces_provider_leak(self):
        r=quarterly_metrics(self.new,self.prev,'2018-07-30')
        self.assertAlmostEqual(r['roe_quarter_pct'],-14.74739939837775)
        with self.assertRaises(DataGap): quarterly_metrics(self.new,self.prev,'2018-05-02')

    def test_q3_uses_difference_not_cumulative(self):
        prev=dict(self.old,period='2018-06-30',published='2018-08-01',parent_equity=100,
                  parent_income_ytd=9,operating_cash_ytd=12)
        cur=dict(self.old,period='2018-09-30',published='2018-10-30',parent_equity=100,
                 parent_income_ytd=12,operating_cash_ytd=10)
        r=quarterly_metrics(cur,prev,'2018-12-28')
        self.assertEqual(r['roe_quarter_pct'],3)
        self.assertEqual(r['operating_cash_quarter'],-2)

    def test_missing_quarter_blocks(self):
        with self.assertRaises(DataGap): quarterly_metrics(dict(self.old,period='2018-06-30'),self.prev,'2018-12-28')

    def test_symbol_mismatch_blocks(self):
        with self.assertRaises(DataGap): quarterly_metrics(self.old,dict(self.prev,symbol='600519.SH'),'2018-05-02')

    def candidate(self, **kw):
        r=dict(symbol='600001.SH',asof='2018-12-28',valuation_date='2018-12-28',listed='2010-01-01',
               float_market_cap=1000000000,pe_ttm=10,roe_quarter_pct=6,operating_cash_quarter=100,
               debt_ratio=.5,is_st=0,is_paused=0)
        return dict(r,**kw)

    def test_filters_strict_boundaries(self):
        controls=[self.candidate(symbol='60000'+str(i)+'.SH') for i in range(2,6)]
        self.assertEqual(len(rank_candidates(controls+[self.candidate()],'2018-12-28')),5)
        for field,value in [('roe_quarter_pct',5),('operating_cash_quarter',0),('pe_ttm',0),
                            ('debt_ratio',.7),('is_st',1),('is_paused',1),('listed','2017-12-28')]:
            with self.subTest(field=field):
                self.assertEqual(rank_candidates(controls+[self.candidate(**{field:value})],'2018-12-28'),[])

    def test_fewer_than_five_skips_rebalance(self):
        self.assertEqual(rank_candidates([self.candidate()],'2018-12-28'),[])

    def test_missing_not_zero(self):
        with self.assertRaises(DataGap): rank_candidates([self.candidate(roe_quarter_pct=None)],'2018-12-28')

    def test_nan_not_exclusion(self):
        with self.assertRaises(DataGap): rank_candidates([self.candidate(pe_ttm=float('nan'))],'2018-12-28')

    def test_future_valuation_blocks(self):
        with self.assertRaises(DataGap): rank_candidates([self.candidate(valuation_date='2018-12-31')],'2018-12-28')

    def test_smallest_five_deterministic(self):
        rows=[self.candidate(symbol='60000'+str(i)+'.SH',float_market_cap=1000+i//2) for i in range(7)]
        self.assertEqual(rank_candidates(list(reversed(rows)),'2018-12-28'),[r['symbol'] for r in rows[:5]])


if __name__ == '__main__': unittest.main()
