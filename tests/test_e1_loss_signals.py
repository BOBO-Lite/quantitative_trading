import unittest
from datetime import date,timedelta
from e1_loss_signal_study import features
from e1_loss_signal_replay import EarlyFailureRules

class LossSignalsTests(unittest.TestCase):
    def test_features_ignore_future_prices_and_volume(self):
        history={}
        for i in range(21):
            d=(date(2020,1,1)+timedelta(days=i)).isoformat();c=10+i/10
            history[d]=dict(datetime=d,close=c,high=c+.2,low=c-.2,factor=1,volume=1000+i*10)
        expected=features(history,'2020-01-21')
        history['2020-01-22']=dict(datetime='2020-01-22',close=10000,high=10001,low=9999,factor=10,volume=99999999)
        self.assertEqual(expected,features(history,'2020-01-21'))

    def setUp(self):
        self.rules=EarlyFailureRules()
        self.p=dict(entry_date='2020-01-02',entry_price=10.,stop=8.)
        self.bar=dict(datetime='2020-01-06T15:00:00',close=9.9,low=9.8,is_paused=False)

    def test_only_third_close_creates_new_exit(self):
        for days,atclose in ((1,True),(2,True),(3,False),(4,True)):
            self.assertIsNone(self.rules.exit_reason(self.p,self.bar,'trend_breakout',0,days,atclose))
        self.assertEqual(self.rules.exit_reason(self.p,self.bar,'trend_breakout',0,3,True),'third_close_failed_followthrough')
        self.bar['close']=10.
        self.assertIsNone(self.rules.exit_reason(self.p,self.bar,'trend_breakout',0,3,True))

    def test_original_defense_and_hard_stop_keep_priority(self):
        self.assertEqual(self.rules.exit_reason(self.p,self.bar,'defensive_cash',0,3,True),'cash_defense')
        self.assertEqual(self.rules.exit_reason(self.p,self.bar,'trend_breakout',.15,3,True),'drawdown_hard_stop')

    def test_paused_bar_does_not_create_new_exit(self):
        self.bar['is_paused']=True
        self.assertIsNone(self.rules.exit_reason(self.p,self.bar,'trend_breakout',0,3,True))

if __name__=='__main__':unittest.main()
