import unittest
from datetime import date,timedelta
from e1_rank_research import RankRules,trend_features
from exit_research import ExitRules
import simple_strategy_rules as base

class RankTests(unittest.TestCase):
    def test_future_history_cannot_change_rank_features(self):
        history={}
        for i in range(61):
            day=str(date(2018,1,1)+timedelta(days=i));history[day]=dict(datetime=day,close=10*1.01**i,factor=1.)
        asof=sorted(history)[59];a=trend_features(history,asof,.03)
        history[sorted(history)[60]]['close']=100000
        self.assertEqual(a,trend_features(history,asof,.03))
        self.assertAlmostEqual(a['r2'],1)
        self.assertAlmostEqual(a['rs20'],1.01**20-1-.03)

    def test_baseline_and_cap_keep_original_order(self):
        rows=[dict(symbol='B',date='2018-01-01',amount20=20),dict(symbol='A',date='2018-01-01',amount20=10)]
        for mode in ('baseline','cap2'):
            self.assertEqual(sorted(rows,key=RankRules(mode,{}).sort_key),sorted(rows,key=base.sort_key))

    def test_only_rank_changes_not_candidate_set(self):
        rows=[dict(symbol=s,date='2018-01-01',amount20=i+10) for i,s in enumerate('ABC')]
        f={('A','2018-01-01'):dict(rs20=.1,stable60=.2),('B','2018-01-01'):dict(rs20=.3,stable60=.1)}
        self.assertEqual([r['symbol'] for r in sorted(rows,key=RankRules('rs20',f).sort_key)],['B','A','C'])
        self.assertEqual([r['symbol'] for r in sorted(rows,key=RankRules('stable60',f).sort_key)],['A','B','C'])
        self.assertEqual(RankRules('rs20',f).select_signal,base.select_signal)

    def test_exit_protection_is_e1(self):
        p=dict(entry_price=10.,stop=9.,highest_close=11.)
        for mode in ('baseline','rs20','stable60','cap2'):
            self.assertEqual(RankRules(mode,{}).close_protection(p,12.,11.,.4),ExitRules('E1').close_protection(p,12.,11.,.4))

if __name__=='__main__':unittest.main()
