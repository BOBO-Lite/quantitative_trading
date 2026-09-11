"""现金分红的权利、应收、税及组合净值边界。"""
import copy,sys,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from corporate_actions import CashDividendBook,dividend_tax_rate
from test_research_portfolio import synthetic_bundle
from research_portfolio import run_bundle

def event():
    return dict(symbol='600001.SH',announcement_date='2026-01-02',record_date='2026-01-06',ex_date='2026-01-07',pay_date='2026-01-08',cash_per_share=.2,shares_per_share=0)

class DividendTests(unittest.TestCase):
    def test_record_ex_pay_are_separate_and_not_double_counted(self):
        b=CashDividendBook([event()]);b.close_day('2026-01-06',{'600001.SH':SimpleNamespace(quantity=500,entry_day='2026-01-06')})
        self.assertEqual(b.receivable,0)
        self.assertEqual(b.open_day('2026-01-07'),0);self.assertEqual(b.receivable,100)
        self.assertEqual(b.open_day('2026-01-08'),100);self.assertEqual(b.receivable,0)
        self.assertEqual(b.open_day('2026-01-09'),0);self.assertEqual(b.gross_income,100)
    def test_ex_day_new_buyer_has_no_entitlement(self):
        b=CashDividendBook([event()]);b.close_day('2026-01-06',{})
        b.open_day('2026-01-07');self.assertEqual(b.open_day('2026-01-08'),0)
        self.assertEqual(b.sell('600001.SH','2026-01-07',500,'2026-01-08'),0)
    def test_sale_before_payment_keeps_receivable_and_taxes_only_sold_quantity(self):
        b=CashDividendBook([event()]);b.close_day('2026-01-06',{'600001.SH':SimpleNamespace(quantity=500,entry_day='2026-01-06')});b.open_day('2026-01-07')
        self.assertEqual(b.sell('600001.SH','2026-01-06',200,'2026-01-07'),8)
        self.assertEqual(b.receivable,100);self.assertEqual(b.open_day('2026-01-08'),100)
        self.assertEqual(b.sell('600001.SH','2026-01-06',300,'2026-01-08'),12)
        self.assertEqual(b.tax_paid,20)
    def test_calendar_month_and_year_boundaries(self):
        for buy,sell,expected in [('2026-01-06','2026-02-06',.2),('2026-01-06','2026-02-07',.1),('2025-01-06','2026-01-06',.1),('2025-01-06','2026-01-07',0),('2024-02-29','2025-02-28',.1)]:
            self.assertEqual(dividend_tax_rate(buy,sell),expected)
    def test_unknown_record_position_fails(self):
        with self.assertRaisesRegex(ValueError,'登记日'):CashDividendBook([event()]).open_day('2026-01-07')
    def test_february_purchase_does_not_extend_month_to_march_31(self):
        self.assertEqual(dividend_tax_rate('2026-02-28','2026-03-28'),.2)
        self.assertEqual(dividend_tax_rate('2026-02-28','2026-03-29'),.1)
        self.assertEqual(dividend_tax_rate('2026-02-28','2026-03-31'),.1)
    def test_duplicate_event_and_duplicate_processing_fail(self):
        with self.assertRaises(ValueError):CashDividendBook([event(),event()])
        b=CashDividendBook([event()]);b.close_day('2026-01-06',{})
        with self.assertRaises(ValueError):b.close_day('2026-01-06',{})
        b.open_day('2026-01-07')
        with self.assertRaises(ValueError):b.open_day('2026-01-07')
    def test_unsupported_share_action_and_date_order_fail(self):
        e=event();e['shares_per_share']=.1
        with self.assertRaises(ValueError):CashDividendBook([e])
        e=event();e['pay_date']='2026-01-06'
        with self.assertRaises(ValueError):CashDividendBook([e])
    def dividend_bundle(self):
        b=synthetic_bundle();e=event();e['pay_date']=e['ex_date'];b['corporate_events']=[e]
        for batch in b['days'][1]['minutes']:
            r=batch['bars']['600001.SH']
            for key in ('open','close','low','high_limit','low_limit'):r[key]-=.2
            r['turnover']=r['open']*r['volume'];r['factor']=10.2/10.
        b['days'][1]['close_features']['stocks']['600001.SH']['factor']=10.2/10.
        return b
    def test_portfolio_dividend_attribution_reconciles(self):
        r=run_bundle(self.dividend_bundle())
        self.assertGreater(r['final']['dividend_income'],0)
        self.assertAlmostEqual(r['final']['dividend_tax'],r['final']['dividend_income']*.2)
        self.assertAlmostEqual(sum(x['total'] for x in r['pnl_by_route'].values()),r['final']['equity']-30000)
        self.assertEqual(r['positions'],{})
    def test_unknown_factor_change_remains_blocked(self):
        b=self.dividend_bundle();b['corporate_events']=[]
        with self.assertRaisesRegex(ValueError,'公司行动'):run_bundle(b)
if __name__=='__main__':unittest.main()
