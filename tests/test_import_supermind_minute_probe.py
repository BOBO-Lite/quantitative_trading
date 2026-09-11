import base64
import copy
import hashlib
import json
import sys
from pathlib import Path
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from import_supermind_minute_probe import decode_packets, build_dataset
from replay_historical_minute_probe import replay


def packet(value):
    raw = json.dumps(value).encode()
    encoded = base64.b64encode(zlib.compress(raw)).decode()
    chunks = [encoded[:10], encoded[10:]]
    return ['MINBUNDLE sample {} 2 {} {} {}'.format(i, len(raw), hashlib.sha256(raw).hexdigest(), chunk)
            for i, chunk in enumerate(chunks)]


class PacketTests(unittest.TestCase):
    def test_reverse_log_order_is_reconstructed(self):
        lines = packet({'rows': [1, 2, 3]})
        self.assertEqual(decode_packets('\n'.join(reversed(lines)))['sample'], {'rows': [1, 2, 3]})

    def test_missing_part_rejected(self):
        with self.assertRaisesRegex(ValueError, '缺少分片'):
            decode_packets(packet({'x': 2})[0])

    def test_duplicate_part_rejected(self):
        lines = packet({'x': 2})
        with self.assertRaisesRegex(ValueError, '重复分片'):
            decode_packets('\n'.join(lines + lines[:1]))

    def test_wrong_hash_rejected(self):
        lines = packet({'x': 2})
        lines = [' '.join(line.split(' ')[:5] + ['0' * 64, line.split(' ')[6]]) for line in lines]
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            decode_packets('\n'.join(lines))

    def test_untrusted_log_is_never_executed(self):
        with self.assertRaisesRegex(ValueError, '没有有效'):
            decode_packets("__import__('os').system('whoami')")


class HistoricalSampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / 'reports/s2_research/minute_export_6a9fd871acb66d00b64c4fda.txt'
        cls.packets = decode_packets(path.read_text(encoding='utf8'))

    def test_real_sample_prices_participation_and_cash(self):
        data = build_dataset(self.packets)
        self.assertEqual(data['row_count'], 1440)
        for rate, cmb_quantity in ((.25, 600), (.001, 300)):
            result = replay(data, rate)
            expected = [14.36435, 35.88585, 14.43555, 36.04392]
            self.assertEqual([f['quantity'] for f in result['fills']], [500, cmb_quantity, 500, cmb_quantity])
            for fill, price in zip(result['fills'], expected):
                self.assertAlmostEqual(fill['price'], price, places=7)
            self.assertAlmostEqual(result['snapshot']['equity'] - 30000, result['snapshot']['realized_pnl'])

    def test_real_sample_duplicate_minute_rejected(self):
        packets = copy.deepcopy(self.packets)
        rows = packets['2019-04-17_minutes']
        rows[2] = copy.deepcopy(rows[0])
        with self.assertRaisesRegex(ValueError, '唯一性'):
            build_dataset(packets)

    def test_real_sample_bad_volume_rejected(self):
        packets = copy.deepcopy(self.packets)
        packets['2019-04-17_minutes'][0]['volume'] += 100
        with self.assertRaisesRegex(ValueError, '日线核账'):
            build_dataset(packets)

    def test_missing_daily_factor_is_not_fabricated(self):
        packets = copy.deepcopy(self.packets)
        frame = packets['2019-04-18_600036.SH_previous_daily']
        frame['factor'] = {key: None for key in frame['factor']}
        with self.assertRaisesRegex(ValueError, '历史字段缺失'):
            build_dataset(packets)


if __name__ == '__main__':
    unittest.main()
