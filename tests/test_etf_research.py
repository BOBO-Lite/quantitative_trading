"""ETF账户经济行为与数据时间边界回归。"""
import copy,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from etf_replay import tick,commission,execution,size,loss,replay,long_features
from etf_dataset import features,SYMBOLS

class ETFTests(unittest.TestCase):
    def fixture(self):
        calendar=['2017-12-29','2018-01-02','2018-01-03','2018-01-04','2018-01-05','2018-01-08']
        daily={s:{d:dict(date=d,close=4.,open=4.,high=4.1,low=3.9,volume=1e7,turnover=1e8,adjustment=1.,is_paused=False,high_limit=4.4,low_limit=3.6,symbol=s) for d in calendar} for s in SYMBOLS}
        minutes={(s,d):dict(datetime=d+'T09:35:00',open=4.,high=4.1,low=3.9,close=4.,volume=1e7,turnover=4e7) for s in SYMBOLS for d in calendar}
        return calendar,daily,[],minutes
    def f(self,h):
        r=h[-1];return dict(date=r['date'],close=r['close'],ma20=3.99,ma60=3.98,atr=.02,amount20=1e8 if r['symbol']==SYMBOLS[0] else 0,adjustment=r['adjustment'])
    def run_case(self,data):
        with patch('etf_replay.features',side_effect=self.f):return replay(*data)
    def test_quote_rounding_is_adverse(self):
        self.assertEqual(tick(4.00001),4.001);self.assertEqual(tick(4.00099,False),4.)
    def test_etf_commission_does_not_add_stock_taxes(self):
        self.assertEqual(commission(10000),5.);self.assertEqual(commission(10000,1.5),7.5)
    def test_cap_rejects_slippage(self):
        _,d,_,m=self.fixture();q,_,why=execution(m[SYMBOLS[0],'2018-01-02'],d[SYMBOLS[0]]['2018-01-02'],True,1000,1.,4.003)
        self.assertEqual((q,why),(0,'price_limit'))
    def test_participation_partial(self):
        _,d,_,m=self.fixture();bar=m[SYMBOLS[0],'2018-01-02'];bar['volume']=45678
        self.assertEqual(execution(bar,d[SYMBOLS[0]]['2018-01-02'],True,1000,1.,4.1)[0],400)
    def test_locked_limit_does_not_fill(self):
        _,d,_,m=self.fixture();bar=m[SYMBOLS[0],'2018-01-02'];bar['open']=4.4
        self.assertEqual(execution(bar,d[SYMBOLS[0]]['2018-01-02'],True,1000,1.,5.)[0],0)
    def test_risk_budget_includes_fees(self):
        q=size(4,3.8,30000,30000,0,0,1.5)
        self.assertLessEqual(loss(q,4,3.8,1.5),375);self.assertLessEqual(q*4*.08,600)
    def test_weekly_no_pyramiding(self):
        r=self.run_case(self.fixture());self.assertEqual(sum(f['buy'] for f in r['fills']),1)
    def test_buy_day_stop_exits_next_day(self):
        data=self.fixture();data[1][SYMBOLS[0]]['2018-01-02']['close']=3.8
        r=self.run_case(data);self.assertEqual([f['datetime'][:10] for f in r['fills'][:2]],['2018-01-02','2018-01-03'])
    def test_dividend_receivable_paydate_no_double_count(self):
        data=self.fixture();data[2].append(dict(symbol=SYMBOLS[0],record_date='2018-01-02',ex_date='2018-01-03',pay_date='2018-01-04',cash=.1,kind='cash'))
        for day in data[0][2:]:
            data[1][SYMBOLS[0]][day]['close']=3.9;data[1][SYMBOLS[0]][day]['adjustment']=4/3.9
        r=self.run_case(data);q=r['fills'][0]['quantity'];a,b=r['daily'][:2]
        self.assertAlmostEqual(a['equity'],b['equity']);self.assertAlmostEqual(b['receivable'],q*.1);self.assertAlmostEqual(r['metrics']['dividends_paid'],q*.1)
    def test_no_entitlement_before_first_buy(self):
        data=self.fixture();data[2].append(dict(symbol=SYMBOLS[0],record_date='2017-12-29',ex_date='2018-01-02',pay_date='2018-01-03',cash=.1,kind='cash'))
        self.assertEqual(self.run_case(data)['metrics']['dividends_paid'],0)
    def test_split_blocks_actual_rights(self):
        data=self.fixture();data[2].append(dict(symbol=SYMBOLS[0],record_date='2018-01-03',ex_date='2018-01-04',kind='unsupported_split',ratio=1.1))
        self.assertEqual(self.run_case(data)['status'],'BLOCKED_CORPORATE_ACTION')
    def test_future_bar_cannot_change_past_orders(self):
        data=self.fixture();original=self.run_case(data)
        altered=copy.deepcopy(data);altered[1][SYMBOLS[0]]['2018-01-08']['close']=2.
        other=self.run_case(altered)
        self.assertEqual(original['daily'][:-1],other['daily'][:-1]);self.assertEqual(original['fills'],other['fills'])
    def test_features_use_signal_date_adjustment(self):
        h=[dict(date='2017-01-01',close=10.,high=11.,low=9.,adjustment=1.,turnover=1e8) for _ in range(120)]
        h[-1].update(close=5.,high=5.5,low=4.5,adjustment=2.)
        f=features(h);self.assertEqual(f['ma20'],5.);self.assertEqual(f['ma60'],5.);self.assertEqual(f['atr'],1.)
    def test_long_trend_does_not_rebuy_next_week(self):
        data=self.fixture();data[1][SYMBOLS[0]]['2018-01-03']['close']=3.7
        with patch('etf_replay.long_features',side_effect=self.f):r=replay(*data,variant='ETF2.0')
        self.assertEqual(sum(f['buy'] for f in r['fills']),1)
        self.assertEqual(r['fills'][1]['datetime'],'2018-01-04T09:35:00')
    def test_long_trend_requires_200_bars(self):
        h=[dict(date='2017-01-01',close=4.,adjustment=1.,turnover=1e8) for _ in range(200)]
        self.assertIsNone(long_features(h[:-1]));self.assertEqual(long_features(h)['ma60'],4.)
    def test_unregistered_variant_rejected(self):
        with self.assertRaises(ValueError):replay(*self.fixture(),variant='optimized')
    def test_unheld_split_does_not_block_other_fund(self):
        data=self.fixture();data[2].append(dict(symbol=SYMBOLS[1],record_date='2018-01-03',ex_date='2018-01-04',kind='unsupported_split',ratio=1.1))
        self.assertEqual(self.run_case(data)['status'],'COMPLETED')

if __name__=='__main__':unittest.main()
