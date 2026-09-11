"""需.venv-framework运行：真实RQAlpha引擎的成交边界，不模拟其账户。"""
import copy, json, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT))
from validate_rqalpha_sample import run_case
from adapters.rqalpha_sample_mod import submit_intent, SampleSource
from replay_historical_minute_probe import replay

class RqalphaEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = json.loads((ROOT/'reports/s2_research/portfolio_replay/historical_minute_sample.json').read_text(encoding='utf-8'))
    def setUp(self): self.data = copy.deepcopy(self.original)
    def row(self, stamp, symbol='000001.SZ'):
        return next(r for r in self.data['rows'] if r['symbol']==symbol and r['datetime']==stamp)
    def buy_once(self, stamp='2019-04-17T09:45:00', cap=14.5, qty=500):
        def callback(ctx,bars,orders):
            if ctx.now.isoformat()==stamp:
                orders.append(submit_intent(ctx,'000001.XSHE',qty,True,cap))
        return callback
    def test_four_real_sample_cost_and_liquidity_cases(self):
        for rate,mult in ((.25,1.),(.001,1.),(.25,1.5),(.001,1.5)):
            with self.subTest(rate=rate,multiplier=mult):
                rq = run_case(self.data,rate,mult)
                local = replay(self.data,rate,mult)
                self.assertEqual(len(rq['fills']),4)
                for a,b in zip(rq['fills'],local['fills']):
                    for field in ('price','quantity','fees','cash_after'):
                        self.assertAlmostEqual(a[field],b[field],places=7)
                    self.assertEqual(a['fill_time'],b['fill_time'])
                self.assertAlmostEqual(rq['equity'],local['snapshot']['equity'],places=7)
    def test_not_same_bar_and_partial_remainder_cancelled(self):
        r = run_case(self.data,.001)
        self.assertEqual(r['fills'][0]['fill_time'],'2019-04-17T09:46:00')
        self.assertEqual(r['orders'][1]['filled_quantity'],300)
        self.assertIn('CANCELLED',r['orders'][1]['status'])
        self.assertEqual(len(r['fills']),4)
    def test_missing_next_minute_expires(self):
        self.data['rows'] = [r for r in self.data['rows'] if r['datetime']!='2019-04-17T09:46:00']
        r = run_case(self.data,callback=self.buy_once())
        self.assertEqual(r['fills'],[])
        self.assertIn('CANCELLED',r['orders'][0]['status'])
    def test_lunch_gap_expires(self):
        r = run_case(self.data,callback=self.buy_once('2019-04-17T11:30:00'))
        self.assertEqual(r['fills'],[])
    def test_slippage_inclusive_cap(self):
        r = run_case(self.data,callback=self.buy_once(cap=14.36))
        self.assertEqual(r['fills'],[])
    def test_paused_cannot_fill(self):
        self.row('2019-04-17T09:46:00')['is_paused']=True
        r = run_case(self.data,callback=self.buy_once())
        self.assertEqual(r['fills'],[])
    def test_limit_up_cannot_fill(self):
        self.row('2019-04-17T09:46:00')['high_limit']=14.36
        r = run_case(self.data,callback=self.buy_once())
        self.assertEqual(r['fills'],[])
    def test_limit_down_blocks_sell(self):
        self.row('2019-04-19T09:46:00')['low_limit']=14.44
        r = run_case(self.data)
        self.assertEqual(len(r['fills']),3)
        self.assertTrue(all(f['symbol']!='000001.XSHE' or f['buy'] for f in r['fills']))
    def test_liquidity_uses_floor_and_sell_allows_odd_shares(self):
        self.row('2019-04-19T09:46:00')['volume']=1202
        r = run_case(self.data)
        self.assertEqual(r['fills'][2]['quantity'],300)
        self.assertIn('CANCELLED',r['orders'][2]['status'])
        self.row('2019-04-19T09:46:00')['volume']=1206
        r = run_case(self.data)
        self.assertEqual(r['fills'][2]['quantity'],301)
    def test_t1_and_no_add_and_duplicate_gate(self):
        rejected=[]
        def callback(ctx,bars,orders):
            if ctx.now.isoformat()=='2019-04-17T09:45:00':
                orders.append(submit_intent(ctx,'000001.XSHE',500,True,14.5))
                with self.assertRaises(ValueError): submit_intent(ctx,'000001.XSHE',100,True,14.5)
                rejected.append('duplicate')
            if ctx.now.isoformat()=='2019-04-17T09:46:00':
                with self.assertRaises(ValueError): submit_intent(ctx,'000001.XSHE',500,False)
                with self.assertRaises(ValueError): submit_intent(ctx,'000001.XSHE',100,True,14.5)
                rejected.extend(['t1','add'])
        r=run_case(self.data,callback=callback)
        self.assertEqual(len(rejected),3); self.assertEqual(len(r['fills']),1)
    def test_both_orders_reserve_costs_before_fills(self):
        def callback(ctx,bars,orders):
            if ctx.now.isoformat()=='2019-04-17T09:45:00':
                orders.append(submit_intent(ctx,'000001.XSHE',1000,True,14.5))
                self.assertAlmostEqual(ctx.portfolio.frozen_cash,14505.145,places=6)
                orders.append(submit_intent(ctx,'600036.XSHG',500,True,36))
        r=run_case(self.data,callback=callback)
        self.assertIsNone(r['orders'][1]); self.assertEqual(len(r['fills']),1)
        self.assertGreater(r['cash'],0)
    def test_factor_change_fails_closed(self):
        self.row('2019-04-18T09:46:00')['factor']*=2
        with self.assertRaisesRegex(ValueError,'公司行动'): SampleSource(self.data)
    def test_invalid_volume_rejected(self):
        self.row('2019-04-18T09:46:00')['volume']=float('nan')
        with self.assertRaises(ValueError): SampleSource(self.data)
    def test_missing_held_quote_stops_engine(self):
        self.data['rows']=[r for r in self.data['rows'] if not (r['symbol']=='000001.SZ' and r['datetime']=='2019-04-18T09:46:00')]
        with self.assertRaisesRegex(Exception,'缺少估值分钟'): run_case(self.data)
if __name__=='__main__': unittest.main()
