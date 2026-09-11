import copy,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from simple_minute_cache import Cache,MissingMinutes
from import_supermind_minute_probe import decode_packets
from simple_corporate_events import build_events

class MinuteCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p=decode_packets((ROOT/'reports/simple_research/minute_export_entry.txt').read_text(encoding='utf8'))
        cls.packets={k:v for k,v in p.items() if v.get('symbol')=='600009.SH'}
        cls.corporate=decode_packets((ROOT/'reports/simple_research/corporate_export.txt').read_text(encoding='utf8'))
    def test_real_minutes_match_daily_and_missing_holding_is_explicit(self):
        c=Cache(self.packets)
        self.assertEqual(len(c.load('2019-04-01',{'600009.SH'})),240)
        self.assertIs(c.load('2019-04-01',{'600009.SH'})[0]['bars']['600009.SH']['is_st'],False)
        with self.assertRaises(MissingMinutes) as exc:c.load('2019-04-02',{'600009.SH'})
        self.assertEqual(exc.exception.requests,[dict(symbol='600009.SH',date='2019-04-02')])
    def test_corrupt_volume_and_missing_minute_fail(self):
        p=copy.deepcopy(self.packets);key='minute_2019-04-01_600009.SH';p[key]['data']['volume'][0]+=100
        with self.assertRaisesRegex(ValueError,'量额不一致'):Cache(p)
        p=copy.deepcopy(self.packets);p[key]['dates'].pop()
        with self.assertRaises(ValueError):Cache(p)
    def test_cash_and_uncertain_corporate_action_are_distinguished(self):
        events,unsupported=build_events(self.corporate,['600887.SH'])
        self.assertEqual(events[0]['cash_per_share'],.7)
        self.assertEqual(events[0]['record_date'],'2019-04-04')
        self.assertFalse(unsupported)
        with self.assertRaises(ValueError):build_events(self.corporate,['000418.SZ'])
    def test_closing_cache_detects_corruption(self):
        c=Cache(self.packets)
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'close.json';dates=['2019-04-01','2019-04-02']
            expected=c.closing_many(dates,path)
            self.assertEqual(c.closing_many(dates,path),expected)
            payload=json.loads(path.read_text(encoding='utf8'));payload['values'][0]['stocks']['600009.SH']['atr20_raw']+=1
            path.write_text(json.dumps(payload),encoding='utf8')
            with self.assertRaisesRegex(ValueError,'缓存损坏'):c.closing_many(dates,path)
    def test_pre_entry_history_does_not_create_account_entitlements(self):
        p=decode_packets((ROOT/'reports/simple_research/continuous_2018_2019/corporate_export.txt').read_text(encoding='utf8'))
        with self.assertRaisesRegex(ValueError,'事件集合不符'):build_events(p,['002350.SZ'],'2018-01-02')
        cash,other=build_events(p,['002350.SZ'],'2019-01-02')
        self.assertEqual(len(cash),1);self.assertEqual(cash[0]['cash_per_share'],.06);self.assertEqual(other,[])
    def test_duplicate_statistical_ratio_does_not_duplicate_cash(self):
        p=decode_packets((ROOT/'reports/simple_research/continuous_2018_2019/corporate_export.txt').read_text(encoding='utf8'))
        cash,other=build_events(p,['600863.SH'],'2019-01-02')
        self.assertEqual(len(cash),1);self.assertEqual(cash[0]['cash_per_share'],.096)
        self.assertEqual(cash[0]['source_rows_merged'],2)
        p['details_600863.SH']['data']['stock_bonus_date_of_record']['1']='2019-08-13T00:00:00.000Z'
        with self.assertRaisesRegex(ValueError,'冲突的重复'):build_events(p,['600863.SH'],'2019-01-02')

if __name__=='__main__':unittest.main()
