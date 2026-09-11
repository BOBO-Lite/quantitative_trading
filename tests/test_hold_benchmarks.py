import unittest
from hold_benchmarks import hold_path,original_pnl

class HoldingControlsTests(unittest.TestCase):
    def setUp(self):
        self.symbol='000001.SZ';self.dates=['2020-01-02','2020-01-03','2020-01-06']
        daily={d:dict(open=p,high=p,low=p,close=p,factor=f) for d,p,f in zip(self.dates,[10,9,10],[1,10/9,10/9])}
        self.event=dict(symbol=self.symbol,announcement_date='2019-12-20',record_date='2020-01-02',ex_date='2020-01-03',pay_date='2020-01-03',cash_per_share=1,shares_per_share=0)
        self.data=dict(daily={self.symbol:daily},events={self.symbol:[self.event]},unsupported={self.symbol:[]},conflicts=[],errors=[])
        self.buy=dict(price=10,quantity=100,fees=5,fill_time='2020-01-02T09:46:00')
    def test_dividend_bridge_does_not_create_extra_profit(self):
        r=hold_path(self.symbol,self.buy,1005,self.dates,self.data)
        self.assertEqual(r['curve'][1]['equity'],1000)
        self.assertEqual(r['profit'],95)
        self.assertEqual(r['dividend_gross'],100)
    def test_missing_holding_day_is_blocked(self):
        del self.data['daily'][self.symbol]['2020-01-06']
        with self.assertRaisesRegex(ValueError,'missing_daily'):hold_path(self.symbol,self.buy,1005,self.dates,self.data)
    def test_unexplained_adjustment_is_blocked(self):
        self.data['events'][self.symbol]=[]
        with self.assertRaisesRegex(ValueError,'unexplained_factor'):hold_path(self.symbol,self.buy,1005,self.dates,self.data)
    def test_sold_trade_dividend_tax_is_separate_from_fill_pnl(self):
        trade=dict(buy=self.buy,sells=[dict(quantity=100,net_pnl=-100,fill_time='2020-01-03T09:32:00')])
        self.assertAlmostEqual(original_pnl(trade,[self.event]),-20)
    def test_sold_before_record_close_does_not_receive_dividend(self):
        trade=dict(buy=self.buy,sells=[dict(quantity=100,net_pnl=0,fill_time='2020-01-02T14:32:00')])
        self.assertEqual(original_pnl(trade,[self.event]),0)

if __name__=='__main__':unittest.main()
