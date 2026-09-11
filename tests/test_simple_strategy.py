import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import simple_strategy_rules as rules
from research_portfolio import run_bundle
from test_research_portfolio import synthetic_bundle
from test_s2_strategy_rules import snapshot,minute

class SimpleTests(unittest.TestCase):
    def row(self): return snapshot() | dict(market_state_verified=True,atr20_raw=.2)
    def test_only_registered_technical_conditions(self):
        row=self.row()
        for k in ('event_clear','pit_verified','industry','rs_percentile','rsi14','compression10','ma20_previous','close_location'):
            row.pop(k,None)
        self.assertTrue(rules.select_signal(row,'trend_breakout'))
        for change in ({'market_state_verified':False},{'is_st':True},{'is_paused':True},{'volume_ratio':3.01},{'close':10.1},{'symbol':'300001.SZ'},{'symbol':'600001.SZ'},{'amount20':None}):
            self.assertFalse(rules.select_signal(row | change,'trend_breakout'),change)
    def test_one_market_switch(self):
        self.assertEqual(rules.research_regime(110,105,100),'trend_breakout')
        self.assertEqual(rules.research_regime(110,100,105),'defensive_cash')
    def test_entry_day_st_state_is_required(self):
        row=self.row();bar=minute() | dict(close=10.2,is_st=False)
        self.assertTrue(rules.entry_confirmed(row,bar,'trend_breakout',10.,10.1))
        self.assertFalse(rules.entry_confirmed(row,bar | dict(is_st=True),'trend_breakout',10.,10.1))
        bar.pop('is_st')
        self.assertFalse(rules.entry_confirmed(row,bar,'trend_breakout',10.,10.1))
    def test_pending_exposure_cannot_breach_seventy_percent(self):
        q=rules.size_entry(10,9.6,30000,10000,16000,'trend_breakout',0,2)
        self.assertGreater(q,0);self.assertLessEqual(16000+10*q,21000)
        self.assertEqual(rules.size_entry(10,9.6,30000,10000,18000,'trend_breakout',0,2),0)
    def test_trailing_only_and_twenty_day_exit(self):
        p=dict(entry_date='2026-01-01',entry_price=10,highest_close=10,stop=9.6,initial_r=.4,quantity=500)
        a=rules.close_protection(p,10.1,0,.2)
        self.assertAlmostEqual(a['stop'],9.7)
        self.assertAlmostEqual(rules.close_protection(a,9.9,0,.2)['stop'],9.7)
        m=dict(datetime='2026-01-10T15:00:00',is_paused=False,low=10,close=10)
        self.assertIsNone(rules.exit_reason(p,m,'trend_breakout',0,8,True))
        self.assertEqual(rules.exit_reason(p,m,'trend_breakout',0,20,True),'time_exit')
    def test_independent_version_runs_without_legacy_gate_and_preserves_original(self):
        b=synthetic_bundle();b['research_version']=rules.VERSION
        for d in b['days']:
            for batch in d['minutes']:
                for bar in batch['bars'].values():bar['is_st']=False
            for r in d['previous_close']['stocks']:
                r.update(market_state_verified=True,event_clear=False,pit_verified=False)
                r.pop('industry');r.pop('rs_percentile')
        result=run_bundle(b,rules=rules)
        self.assertTrue(result['fills'])
        self.assertEqual(result['research_version'],'TECH1.0')
        self.assertLessEqual(sum(f['quantity']*f['price'] for f in result['fills'] if f['buy']),21000)
        self.assertFalse(run_bundle(b)['fills'])
        b['unresolved_corporate_symbols']=['600001.SH','600002.SH','600003.SH']
        with self.assertRaisesRegex(ValueError,'停止而非剔除'):
            run_bundle(b,rules=rules)
        with self.assertRaises(ValueError):run_bundle(synthetic_bundle(),rules=rules)
    def test_missing_minutes_still_fails(self):
        b=synthetic_bundle();b['research_version']=rules.VERSION;b['days'][0]['minutes'].pop()
        with self.assertRaises(ValueError):run_bundle(b,rules=rules)

if __name__=='__main__':unittest.main()
