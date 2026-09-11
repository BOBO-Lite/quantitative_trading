import unittest
from copy import deepcopy
from datetime import date,timedelta
from exit_recovery_research import features,first_signal,simulate
from research_portfolio import session_minutes

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.days=[(date(2020,1,1)+timedelta(days=i)).isoformat() for i in range(15)]
        self.h={d:dict(close=9.,factor=1.,is_paused=False) for d in self.days}
        self.trigger=dict(stop=10.,trigger_time=self.days[8]+'T15:00:00')
    def test_future_prices_cannot_change_first_signal(self):
        self.h[self.days[10]]['close']=11
        before=first_signal(self.h,self.days,self.days[9],self.trigger,[],'L')
        altered=deepcopy(self.h)
        for d in self.days[11:]:altered[d]['close']=1000000
        self.assertEqual(before,self.days[10])
        self.assertEqual(first_signal(altered,self.days,self.days[9],self.trigger,[],'L'),before)
    def test_above_level_without_a_cross_is_not_reclaim(self):
        for d in self.days:self.h[d]['close']=11
        self.assertIsNone(first_signal(self.h,self.days,self.days[9],self.trigger,[],'L'))
    def test_dividend_adjusts_level_and_ma_consistently(self):
        for d in self.days:self.h[d]['close']=10
        d=self.days[10];self.h[d].update(close=9,factor=10/9)
        c,level,ma=features(self.h,d,self.trigger,[dict(ex_date=d,cash_per_share=1)])
        self.assertAlmostEqual(c,9);self.assertAlmostEqual(level,9);self.assertAlmostEqual(ma,9)
    def test_entry_is_next_minute_and_failure_sale_obeys_t_plus_one(self):
        s='000001.SZ';start=self.days[11];end=self.days[12];signal=self.days[10]
        self.h[signal]['close']=11
        minutes={}
        for d in (start,end):
            self.h[d].update(close=9,volume=240000,high_limit=12,low_limit=8,is_st=False)
            minutes[s,d]=[dict(datetime=t,open=9,high=9,low=9,close=9,volume=1000,turnover=9000) for t in session_minutes(d)]
        data=dict(daily={s:self.h},events={s:[]},unsupported={s:[]},errors=[],conflicts=[])
        bench={d:dict(close=12,ma20=11,ma60=10,slope5=1,ret20=.1) for d in self.days}
        case=dict(symbol=s,starting_cash=2000,signal=signal,end=end,cost=1.,original_quantity=100,trigger=self.trigger)
        result=simulate(case,minutes,data,self.days,bench)
        self.assertEqual(len(result['fills']),2)
        self.assertEqual(result['fills'][0]['fill_time'],start+'T09:32:00')
        self.assertEqual(result['fills'][1]['fill_time'],end+'T09:32:00')
        self.assertLess(result['increment'],0)

if __name__=='__main__':unittest.main()
