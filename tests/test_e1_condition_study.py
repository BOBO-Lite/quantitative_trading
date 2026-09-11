import unittest
from e1_condition_study import forward,aggregate,groups
from e1_condition_replay import ConditionRules
from exit_research import ExitRules

class ConditionTests(unittest.TestCase):
    def test_next_open_to_fifth_close(self):
        dates=[f'2020-01-{i:02d}' for i in range(1,8)]
        history={d:dict(open=10,close=11,factor=1) for d in dates}
        history[dates[0]]['open']=1
        ret,err=forward(history,dates,0,5)
        self.assertIsNone(err);self.assertAlmostEqual(ret,10)
        self.assertEqual(forward(history,dates,3,5),(None,'sample_end'))
        del history[dates[2]]
        self.assertEqual(forward(history,dates,0,5),(None,'missing_interval'))

    def test_group_features_only_use_current_inputs(self):
        row=dict(close=105,ma20=100,volume_ratio=2,atr20_raw=2,raw_close=100,prior_breakout_close=104)
        g=groups(row,dict(ret20=.05))
        # Floating price ratios near an exact boundary use deterministic arithmetic.
        self.assertEqual(g['volume'],'moderate');self.assertEqual(g['volatility'],'low2')
        self.assertEqual(g['market'],'moderate5');self.assertEqual(g['breakout'],'near2')
        self.assertEqual(g['ma20'],'near5')

    def test_dates_equal_weight_and_cross_year_outcomes_purged(self):
        def r(day,ret,exitday):return dict(asof=day,outcomes={'5':ret},exit_days={'5':exitday},groups={'a':'x'})
        data=[r('2019-01-01',10,'2019-01-08')]*10+[r('2019-02-01',-10,'2019-02-08'),r('2019-12-30',100,'2020-01-07')]
        a=aggregate(data,'2019-01-01','2019-12-31',5)
        self.assertEqual(a['days'],2);self.assertEqual(a['signals'],11);self.assertEqual(a['mean_date_balanced_pct'],0)

    def test_account_filter_boundary_and_original_guards(self):
        row=dict(symbol='600000.SH',market_state_verified=True,is_st=False,is_paused=False,
                 listing_bars=200,amount20=100000000.,close=110.,ma20=100.,ma60=90.,
                 prior_breakout_close=109.,volume_ratio=1.5,atr20_raw=2.,raw_close=110.)
        rules=ConditionRules()
        self.assertFalse(rules.select_signal(row,'trend_breakout'))
        row['close']=110.01
        self.assertTrue(rules.select_signal(row,'trend_breakout'))
        self.assertFalse(rules.select_signal(row,'defensive_cash'))
        row['is_st']=True
        self.assertFalse(rules.select_signal(row,'trend_breakout'))
        p=dict(entry_price=10.,stop=9.,highest_close=11.)
        self.assertEqual(rules.close_protection(p,12,11,.4),ExitRules('E1').close_protection(p,12,11,.4))

if __name__=='__main__':unittest.main()
