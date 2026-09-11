import copy,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from simple_minute_aliases import apply_aliases
from import_supermind_minute_probe import decode_packets
from simple_minute_cache import Cache

class HistoricalCodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=ROOT/'reports/simple_research/2019'
        all_packets=decode_packets((cls.folder/'minute_export_entry01.txt').read_text(encoding='utf8'))
        cls.packets={k:v for k,v in all_packets.items() if v.get('symbol')=='001914.SZ'}
    def test_announcement_mapping_and_real_daily_reconciliation(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td);(folder/'alias_export.txt').write_bytes((self.folder/'alias_export.txt').read_bytes())
            repaired=apply_aliases(self.packets,folder)
            self.assertEqual(len(Cache(repaired).minutes['001914.SZ','2019-03-13']),240)
            self.assertEqual(self.packets['minute_2019-03-13_001914.SZ']['dates'],[])
    def test_raw_price_disagreement_prevents_alias_bridge(self):
        p=copy.deepcopy(self.packets);d=p['daily_001914.SZ'];i=[t[:10] for t in d['dates']].index('2019-03-13');d['data']['close'][i]+=.01
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td);(folder/'alias_export.txt').write_bytes((self.folder/'alias_export.txt').read_bytes())
            with self.assertRaisesRegex(ValueError,'原始日线不一致'):apply_aliases(p,folder)

if __name__=='__main__':unittest.main()
