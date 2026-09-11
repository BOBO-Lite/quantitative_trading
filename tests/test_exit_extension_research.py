"""防止分页遗漏被误当完整历史，及跨年账户被重置。"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from exit_extension_research import read_export, check_prefix

class ExtensionTests(unittest.TestCase):
    def fixture(self, directory):
        p=Path(directory)/'minute_export_01.txt'
        p.write_text('TECH1_ENTRY_MINUTE_EXPORT_DONE',encoding='utf8')
        p.with_name('minute_probe_01.py').write_text("REQUESTS = [('000001.SZ','2020-01-02')]",encoding='utf8')
        return p

    def test_whole_missing_packet_rejected_despite_end_marker(self):
        with tempfile.TemporaryDirectory() as d, patch('exit_extension_research.decode_packets',return_value={'daily_a':{'symbol':'000001.SZ'}}):
            with self.assertRaisesRegex(ValueError,'集合'):
                read_export(self.fixture(d))

    def test_missing_daily_rejected_even_when_all_minutes_present(self):
        packets={'minute_a':dict(symbol='000001.SZ',date='2020-01-02')}
        with tempfile.TemporaryDirectory() as d, patch('exit_extension_research.decode_packets',return_value=packets):
            with self.assertRaisesRegex(ValueError,'集合'):
                read_export(self.fixture(d))

    def test_daily_prefix_cannot_be_reset(self):
        old={k:[dict(cash=30000)] for k in ('fills','daily','minute_curve','orders','decisions')}
        new={k:list(v) for k,v in old.items()}
        new['daily']=[dict(cash=31000)]
        with self.assertRaisesRegex(ValueError,'daily'):
            check_prefix(new,old)

if __name__=='__main__': unittest.main()
