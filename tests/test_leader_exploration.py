import unittest
import pandas as pd
import numpy as np
from leader_exploration import features,exit_signal,run

class LeaderExplorationTests(unittest.TestCase):
    def test_future_prices_do_not_change_past_signals(self):
        close=np.arange(1,101,dtype=float)+100
        frame=pd.DataFrame(dict(open=close,close=close,high=close+1,low=close-1,factor=1.,volume=1000.),index=pd.date_range('2018-01-01',periods=100))
        before=features(frame)
        frame.loc[frame.index[81]:,['open','high','low','close']]*=3
        after=features(frame)
        pd.testing.assert_frame_equal(before.iloc[:81],after.iloc[:81])

    def test_low_exit_uses_prior_window(self):
        c=np.full(12,100.);c[-1]=90
        frame=pd.DataFrame(dict(open=c,high=c+1,low=c-1,close=c,factor=1.,volume=1000.))
        last=features(frame).iloc[-1].to_dict()
        self.assertEqual(last['low10'],99.)
        self.assertTrue(exit_signal(last,{'peak':100},'low10'))

    def test_entry_and_exit_fill_after_signal(self):
        days=['2018-01-02','2018-01-03','2018-01-04','2018-01-05']
        def row(c):
            return dict(open=c,high=c+1,low=c-1,close=c,factor=1.,a_open=c,a_close=c,
                 is_st=0,is_paused=0,volume=10000.,strength=.4,ma10=10.,ma20=9.,ma60=8.,
                 prior_high20=10.,vol20=1000.,prev_close=11.,prev_ma10=10.,low10=9.)
        rows={d:{'A':row(c)} for d,c in zip(days,[11,11,9.8,10])}
        r=run(days,{d:['A'] for d in days},rows,{d:100 for d in days},'breakout','ma10',1.)
        self.assertEqual(r['fills'][0]['date'],days[1]);self.assertEqual(r['fills'][0]['signal'],days[0])
        self.assertEqual(r['fills'][1]['date'],days[3]);self.assertEqual(r['fills'][1]['signal'],days[2])

if __name__=='__main__':unittest.main()
