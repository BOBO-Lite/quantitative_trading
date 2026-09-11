import unittest
from e1_confirmation import ConfirmationRules,prior_features

class ConfirmationTests(unittest.TestCase):
    def pos(self):return dict(entry_date='2020-01-01',entry_price=10.,initial_r=.5,stop=9.,highest_close=10.,known_ma10=11.8,known_ma10_stop_reference=9.,turning_atr=.4,turning_peak=12.)
    def bar(self,t='2020-01-03T10:00:00',price=11.5):return dict(datetime=t,close=price,low=price,high=price,is_paused=False,symbol='600000.SH',confirmation=dict(asof='2020-01-02',down=False,volume_ratio=.8,relative5=.1,two_below_ma10=False))
    def test_volume_veto_does_not_sell_early_peak(self):
        r=ConfirmationRules('V');p=self.pos();b=self.bar()
        self.assertIsNone(r.exit_reason(p,b,'trend_breakout',0,2));self.assertEqual(r.events[-1]['event'],'profit_exit_veto')
        b['confirmation'].update(down=True,volume_ratio=1.1)
        self.assertEqual(r.exit_reason(p,b,'trend_breakout',0,2),'confirmed_profit_exit')
    def test_relative_weakness_can_confirm(self):
        r=ConfirmationRules('S');b=self.bar();b['confirmation']['relative5']=-.01
        self.assertEqual(r.exit_reason(self.pos(),b,'trend_breakout',0,2),'confirmed_profit_exit')
    def test_recovery_resets_persistence_and_duplicate_does_not_count(self):
        r=ConfirmationRules('H');p=self.pos();b=self.bar()
        r.exit_reason(p,b,'trend_breakout',0,2);r.exit_reason(p,b,'trend_breakout',0,2,True)
        self.assertEqual(p['below_count'],1)
        r.exit_reason(p,self.bar('2020-01-03T10:01:00',11.9),'trend_breakout',0,2)
        self.assertEqual(p['below_count'],0)
    def test_thirty_completed_minutes_and_daily_reset(self):
        from datetime import datetime,timedelta
        r=ConfirmationRules('H');p=self.pos()
        for i in range(30):
            t=(datetime(2020,1,3,10)+timedelta(minutes=i)).isoformat();ans=r.exit_reason(p,self.bar(t),'trend_breakout',0,2)
            self.assertEqual(ans,'confirmed_profit_exit' if i==29 else None)
        self.assertIsNone(r.exit_reason(p,self.bar('2020-01-06T09:31:00'),'trend_breakout',0,3));self.assertEqual(p['below_count'],1)
    def test_combination_requires_two_distinct_confirmations(self):
        r=ConfirmationRules('C');p=self.pos();b=self.bar();b['confirmation']['relative5']=-.1
        self.assertIsNone(r.exit_reason(p,b,'trend_breakout',0,2))
        b['confirmation'].update(down=True,volume_ratio=1.)
        self.assertEqual(r.exit_reason(p,b,'trend_breakout',0,2),'confirmed_profit_exit')
    def test_loss_requires_persistence_and_original_risk_priority(self):
        r=ConfirmationRules('F');p=self.pos();b=self.bar(price=9.7)
        b['confirmation'].update(relative5=-.1,two_below_ma10=True)
        self.assertEqual(r.exit_reason(p,b,'trend_breakout',0,2),'persistent_weak_loss')
        self.assertEqual(r.exit_reason(p,b,'defensive_cash',0,2),'cash_defense')
    def test_future_context_rejected(self):
        b=self.bar();b['confirmation']['asof']='2020-01-03'
        with self.assertRaises(ValueError):ConfirmationRules('C').exit_reason(self.pos(),b,'trend_breakout',0,2)
    def test_future_daily_row_cannot_change_prior_features(self):
        from datetime import date,timedelta
        h={(date(2019,12,1)+timedelta(days=i)).isoformat():dict(close=10+i*.1,factor=1.,volume=100.) for i in range(22)}
        a=prior_features(h,'2019-12-21',.01);h['2019-12-22']=dict(close=9999.,factor=2.,volume=1e12)
        self.assertEqual(a,prior_features(h,'2019-12-21',.01))

if __name__=='__main__':unittest.main()
