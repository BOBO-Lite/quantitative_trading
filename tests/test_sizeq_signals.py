import unittest
from copy import deepcopy
from sizeq_signals import SignalGap,ttm_income,records_index,select,prev

class SQ1SignalsTests(unittest.TestCase):
    def setUp(self):
        self.pool=[];self.fin=[]
        for i in range(7):
            s='60000'+str(i)+'.SH'
            self.pool.append(dict(symbol=s,asof='2017-12-29',listed='2010-01-01',close=10,float_shares=100+i,st=0,paused=0,provider_pe=-100))
            for period,value in [('2016-09-30',10),('2016-12-31',20),('2017-06-30',30),('2017-09-30',40)]:
                self.fin.append(dict(symbol=s,table='income',period=period,published=period,income=value))
            for period,value in [('2017-06-30',30),('2017-09-30',40)]:
                self.fin.extend([dict(symbol=s,table='cashflow',period=period,published=period,cash=value),dict(symbol=s,table='balance',period=period,published=period,equity=100,assets=200,liabilities=80)])

    def test_ttm_rebuild_uses_three_legs(self):
        x=records_index(self.fin,'2017-12-29');self.assertEqual(ttm_income(x,'600000.SH','2017-09-30'),50)

    def test_pe_provider_negative_does_not_override_public_profit(self):
        r=select(self.pool,self.fin,'2017-12-29');self.assertEqual(r['targets'],[p['symbol'] for p in self.pool[:5]])

    def test_unknown_smaller_stock_blocks(self):
        f=[r for r in self.fin if r['symbol']!='600000.SH']
        r=select(self.pool,f,'2017-12-29');self.assertEqual(r['status'],'BLOCKED');self.assertIsNone(r['targets'])

    def test_larger_stock_not_needed_after_five(self):
        f=[r for r in self.fin if r['symbol'] in [p['symbol'] for p in self.pool[:5]]]
        r=select(self.pool,f,'2017-12-29');self.assertEqual(r['status'],'PASS');self.assertEqual(len(r['higher_cap_not_needed']),2)

    def test_missing_rank_eligible_blocks(self):
        self.pool[-1]['float_shares']=None
        r=select(self.pool,self.fin,'2017-12-29');self.assertEqual(r['status'],'BLOCKED')

    def test_missing_rank_debt_exclusion_is_decisive(self):
        s=self.pool[-1]['symbol'];self.pool[-1]['float_shares']=None
        for r in self.fin:
            if r['symbol']==s and r['table']=='balance':r['liabilities']=150
        r=select(self.pool,self.fin,'2017-12-29');self.assertEqual(r['status'],'PASS');self.assertEqual(r['excluded'][s],'DEBT_GE_70')

    def test_future_report_blocks_even_if_high_cap(self):
        self.fin[-1]['published']='2018-01-01'
        with self.assertRaises(SignalGap):select(self.pool,self.fin,'2017-12-29')

    def test_fewer_than_five_skip(self):
        p=self.pool[:4];f=[r for r in self.fin if r['symbol'] in [s['symbol'] for s in p]]
        self.assertEqual(select(p,f,'2017-12-29')['targets'],[])

    def test_duplicate_version_blocks(self):
        with self.assertRaises(SignalGap):select(self.pool,self.fin+[self.fin[0]],'2017-12-29')

    def test_missing_ttm_leg_not_zero(self):
        f=[r for r in self.fin if not(r['symbol']=='600000.SH' and r['period']=='2016-09-30')]
        self.assertEqual(select(self.pool,f,'2017-12-29')['status'],'BLOCKED')

    def test_annual_and_q1_boundaries(self):
        self.assertEqual(prev('2018-03-31'),'2017-12-31')
        self.assertEqual(ttm_income(records_index(self.fin,'2017-12-29'),'600000.SH','2016-12-31'),20)

    def test_nonpositive_ttm_rejects(self):
        for r in self.fin:
            if r['symbol']=='600000.SH' and r['table']=='income' and r['period']=='2016-12-31':r['income']=-100
        r=select(self.pool,self.fin,'2017-12-29');self.assertEqual(r['excluded']['600000.SH'],'TTM_NONPOSITIVE')

if __name__=='__main__':unittest.main()
