import copy,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from akshare_daily_bridge import adapt_probe,fetch_missing
class AkshareBridgeTests(unittest.TestCase):
    def setUp(self):
        self.payload=json.loads((ROOT/'reports/s2_research/framework_adoption/akshare_tencent_verified/probe.json').read_text(encoding='utf-8'))
        self.symbols=[c['symbol'] for c in self.payload['cases']]
        self.metadata={s:dict(name='测试',listed_date='2000-01-01') for s in self.symbols}
    def test_actual_dated_probe_adapts_to_scan_schema(self):
        frame=adapt_probe(self.payload,self.symbols,'2026-09-08',self.metadata)
        self.assertEqual(len(frame),3);self.assertEqual(frame['volume'].iloc[0],74051600)
        self.assertTrue((frame['paused']==False).all())
    def test_wrong_date_and_zero_volume_are_rejected(self):
        with self.assertRaises(ValueError):adapt_probe(self.payload,self.symbols,'2026-09-07',self.metadata)
        self.payload['cases'][0]['row']['volume']=0
        with self.assertRaises(ValueError):adapt_probe(self.payload,self.symbols,'2026-09-08',self.metadata)
    def test_failed_symbol_is_not_filled_from_prior_price(self):
        self.payload['cases'][0]['status']='BLOCKED_SOURCE'
        frame=adapt_probe(self.payload,self.symbols,'2026-09-08',self.metadata)
        self.assertEqual(len(frame),2)
    def test_large_outage_does_not_trigger_unbounded_queries(self):
        frame,detail=fetch_missing(['600001.SH']*11,'2026-09-08',{},ROOT/'runtime/test-unused')
        self.assertTrue(frame.empty);self.assertEqual(detail['status'],'SKIPPED_SCOPE_OR_ENVIRONMENT')
if __name__=='__main__':unittest.main()
