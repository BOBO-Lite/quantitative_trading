"""收紧追价仍需真实突破确认，不能变成无确认抄底。"""
import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from entry_research import EntryRules

class EntryTests(unittest.TestCase):
    def setUp(self):
        self.signal=dict(date='2020-01-02',factor=1.,raw_close=10.,raw_high=10.1,atr20_raw=.2)
        self.bar=dict(datetime='2020-01-03T09:45:00',factor=1.,close=10.25,high_limit=11.,is_paused=False,is_st=False)
    def test_above_two_percent_rejected_only_by_tighter_entry(self):
        self.assertTrue(EntryRules('B0').entry_confirmed(self.signal,self.bar,'trend_breakout',10.,10.))
        self.assertFalse(EntryRules('B1').entry_confirmed(self.signal,self.bar,'trend_breakout',10.,10.))
    def test_exact_cap_allowed_but_unconfirmed_pullback_rejected(self):
        self.bar['close']=10.2
        self.assertTrue(EntryRules('B1').entry_confirmed(self.signal,self.bar,'trend_breakout',10.,10.))
        self.bar['close']=10.1
        self.assertFalse(EntryRules('B1').entry_confirmed(self.signal,self.bar,'trend_breakout',10.,10.))
    def test_time_and_vwap_guards_remain(self):
        self.bar['close']=10.2
        self.assertFalse(EntryRules('B1').entry_confirmed(self.signal,self.bar,'trend_breakout',10.,10.3))
        self.bar['datetime']='2020-01-03T09:44:00'
        self.assertFalse(EntryRules('B1').entry_confirmed(self.signal,self.bar,'trend_breakout',10.,10.))

if __name__=='__main__':unittest.main()
