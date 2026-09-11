import unittest
import numpy as np
from external_momentum import features,weights,buy_eligible
from external_momentum_replay import Ledger,execute

def sample():
    import datetime
    c=10*np.exp(np.arange(100)*.001)
    return dict(dates=[(datetime.date(2017,1,1)+datetime.timedelta(days=i)).isoformat() for i in range(100)],data=dict(open=c.tolist(),close=c.tolist(),high=(c*1.01).tolist(),low=(c*.99).tolist(),factor=[1.]*100,volume=[10000.]*100,turnover=[100000.]*100,is_st=[0]*100,is_paused=[0]*100))

class MomentumTests(unittest.TestCase):
    def test_known_exponential(self):
        f=features(sample());self.assertAlmostEqual(f['score'],np.expm1(.252),10);self.assertAlmostEqual(f['r2'],1);self.assertTrue(buy_eligible(f))
    def test_scale_invariant(self):
        w=sample();f=features(w)
        for k in ('open','high','low','close'):w['data'][k]=[v*2 for v in w['data'][k]]
        g=features(w);self.assertAlmostEqual(f['score'],g['score']);self.assertAlmostEqual(g['atr20'],2*f['atr20'])
    def test_split_adjustment(self):
        w=sample();f=features(w)
        for k in ('open','high','low','close'):w['data'][k]=[v*2 if i<50 else v for i,v in enumerate(w['data'][k])]
        w['data']['factor']=[.5]*50+[1.]*50;g=features(w)
        for k in f:self.assertAlmostEqual(f[k],g[k])
    def test_gap_is_return_not_return_difference(self):
        w=sample()
        for k in ('open','high','low','close'):w['data'][k]=[v*1.16 if i>=90 else v for i,v in enumerate(w['data'][k])]
        self.assertFalse(buy_eligible(features(w)))
    def test_short_and_invalid(self):
        w=sample();w['data']['close'][0]=float('nan')
        with self.assertRaises(ValueError):features(w)
    def test_weights_cap_and_cash(self):
        rows=[dict(symbol=str(i),close=10.,atr20=a) for i,a in enumerate([.01,1.,1.,1.,1.])]
        w=weights(rows);self.assertAlmostEqual(sum(w.values()),.95);self.assertLessEqual(max(w.values()),.25)
        self.assertAlmostEqual(sum(weights(rows[:2]).values()),.5)
    def test_equal_weight(self):
        w=weights([dict(symbol=str(i),close=10.,atr20=1.) for i in range(5)])
        self.assertTrue(all(abs(v-.19)<1e-12 for v in w.values()))

class AccountTests(unittest.TestCase):
    def test_t_plus_one(self):
        b=Ledger([]);b.buy('x',100,10,1,'2020-01-02')
        with self.assertRaises(ValueError):b.sell('x',100,10,1,'2020-01-02')
    def test_fifo_dividend_tax_and_receivable(self):
        e=dict(symbol='x',record_date='2020-03-02',ex_date='2020-03-03',pay_date='2020-03-04',cash_per_share=1)
        b=Ledger([e]);b.buy('x',100,10,1,'2019-01-02');b.buy('x',100,10,1,'2020-02-28');b.record('2020-03-02');b.open('2020-03-03')
        self.assertEqual(b.receivable,200);cash=b.cash;b.open('2020-03-04');self.assertAlmostEqual(b.cash,cash+200)
        self.assertEqual(b.sell('x',100,10,1,'2020-03-05')[1],0)
        self.assertEqual(b.sell('x',100,10,1,'2020-03-05')[1],20)
        self.assertEqual(b.qty('x'),0);self.assertEqual(b.receivable,0)
    def test_cash_cannot_be_invented(self):
        with self.assertRaises(ValueError):Ledger([]).buy('x',3000,10,1,'2020-01-02')
    def test_minute_volume_and_actual_price(self):
        d=dict(is_paused=False,is_st=False,high_limit=11,low_limit=9)
        bar=dict(open=10,high=10.1,low=9.9,volume=15000)
        self.assertEqual(execute(bar,d,True,1000,1)[0],100)
        bar['high']=10
        self.assertEqual(execute(bar,d,True,1000,1)[0],0)
    def test_limit_and_paused(self):
        d=dict(is_paused=False,is_st=False,high_limit=11,low_limit=9);bar=dict(open=11,high=11,low=11,volume=100000)
        self.assertEqual(execute(bar,d,True,1000,1)[0],0)
        d['is_paused']=True
        self.assertEqual(execute(bar,d,False,1000,1)[0],0)
    def test_capital_distribution_lock_and_tax(self):
        e=dict(symbol='x',record_date='2020-03-02',ex_date='2020-03-03',pay_date='2020-03-03',cash_per_share=.1,shares_per_share=.5,shares_trading_date='2020-03-04',taxable_cash_per_share=.1)
        b=Ledger([e]);b.buy('x',100,10,1,'2020-02-28');b.record('2020-03-02');b.open('2020-03-03')
        self.assertEqual(b.qty('x'),150);self.assertEqual(b.available('x','2020-03-03'),100)
        with self.assertRaises(ValueError):b.sell('x',150,6.6,1,'2020-03-03')
        self.assertAlmostEqual(b.sell('x',100,6.6,1,'2020-03-03')[1],4/3)
        self.assertEqual(b.available('x','2020-03-04'),50)
        self.assertAlmostEqual(b.sell('x',50,6.6,1,'2020-03-04')[1],2/3)
        self.assertAlmostEqual(b.tax,2)
    def test_bonus_stock_tax(self):
        e=dict(symbol='x',record_date='2020-03-02',ex_date='2020-03-03',pay_date='2020-03-03',cash_per_share=.1,shares_per_share=.2,shares_trading_date='2020-03-04',taxable_cash_per_share=.3)
        b=Ledger([e]);b.buy('x',100,10,1,'2020-02-28');b.record('2020-03-02');b.open('2020-03-03')
        self.assertAlmostEqual(b.sell('x',120,8,1,'2020-03-04')[1],6)
    def test_fractional_distribution_blocks(self):
        from external_momentum_replay import MissingData
        e=dict(symbol='x',record_date='2020-03-02',ex_date='2020-03-03',pay_date='2020-03-03',cash_per_share=0,shares_per_share=.001,shares_trading_date='2020-03-04')
        b=Ledger([e]);b.buy('x',100,10,1,'2020-02-28');b.record('2020-03-02')
        with self.assertRaises(MissingData):b.open('2020-03-03')

if __name__=='__main__':unittest.main()
