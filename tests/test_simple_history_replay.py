import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from simple_history_replay import merge_cache,clean_boundary
from simple_minute_cache import Cache

class HistoryJoinTests(unittest.TestCase):
    def test_year_overlap_is_verified_and_history_preserved(self):
        a=Cache({});b=Cache({})
        a.daily={'600001.SH':{'2018-12-27':{'close':10},'2018-12-28':{'close':11}}}
        b.daily={'600001.SH':{'2018-12-28':{'close':11},'2019-01-02':{'close':12}}}
        c=merge_cache([a,b]);self.assertEqual(len(c.daily['600001.SH']),3)
        self.assertEqual(len(a.daily['600001.SH']),2)
        b.daily['600001.SH']['2018-12-28']['close']=11.01
        with self.assertRaisesRegex(ValueError,'跨年原始日线冲突'):merge_cache([a,b])
    def test_signal_overlap_ignores_only_warmup_count(self):
        a=dict(date='2018-12-28',benchmark={'close':100},route='trend_breakout',universe_count=1,candidates=[dict(symbol='600001.SH',listing_bars=300,close=10,raw_close=10,atr20_raw=.2)])
        b=dict(a,candidates=[dict(symbol='600001.SH',listing_bars=200,close=10,raw_close=10,atr20_raw=.2)])
        self.assertEqual(clean_boundary(a),clean_boundary(b))
        b['candidates'][0]['close']=10.01
        self.assertNotEqual(clean_boundary(a),clean_boundary(b))
    def test_non_executable_boundary_candidates_are_transport_only(self):
        base=dict(date='2019-12-31',benchmark={'close':100},route='trend_breakout',universe_count=1,candidates=[])
        full=dict(base,candidates=[dict(symbol='600001.SH',listing_bars=300,raw_close=10,atr20_raw=1)])
        self.assertEqual(clean_boundary(base),clean_boundary(full))

if __name__=='__main__':unittest.main()
