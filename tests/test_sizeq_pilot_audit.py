import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from audit_sizeq_pilot import audit, alias_debt_exclusion, rows, OUT
from external_size_quality import DataGap
from import_supermind_minute_probe import decode_packets

class PilotAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path=OUT/'pilot_export.txt'
        cls.packets=decode_packets(cls.path.read_text(encoding='utf8'))

    def test_complete_decision_and_no_imputed_valuation(self):
        r=audit(self.path)
        self.assertEqual(r['status'],'PASS_SINGLE_SIGNAL_DECISION_AUDIT')
        self.assertEqual(r['targets'],['603060.SH','002346.SZ','603025.SH','603318.SH','603203.SH'])
        self.assertEqual(sum(r['excluded_counts'].values())+len(r['eligible_rows']),2181)
        self.assertEqual(r['resolved_gaps'][0]['missing_field'],'valuation')

    def test_missing_packet_blocks(self):
        p=deepcopy(self.packets); del p['balance_2017q3_0']
        with patch('audit_sizeq_pilot.decode_packets',return_value=p),self.assertRaises(KeyError): audit(self.path)

    def test_future_financial_row_blocks(self):
        p=deepcopy(self.packets); f=p['balance_2017q3_0']
        f['data'][0][f['columns'].index('balance_stat_report_date')]='2018-01-01'
        with patch('audit_sizeq_pilot.decode_packets',return_value=p),self.assertRaises(DataGap): audit(self.path)

    def test_incomplete_export_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'input.txt';p.write_text('MINBUNDLE',encoding='utf8')
            with self.assertRaises(DataGap):audit(p)

    def test_alias_future_statement_blocks(self):
        p=decode_packets((OUT/'alias_export.txt').read_text(encoding='utf8'))
        f=p['balance_2017q3'];f['data'][0][f['columns'].index('balance_stat_report_date')]='2018-01-01'
        with patch('audit_sizeq_pilot.decode_packets',return_value=p),self.assertRaises(DataGap):alias_debt_exclusion(self.path,'2017-12-29')

    def test_alias_cannot_hide_potential_candidate(self):
        p=decode_packets((OUT/'alias_export.txt').read_text(encoding='utf8'))
        f=p['balance_2017q3'];f['data'][0][f['columns'].index('balance_stat_total_liabilities')]=1
        with patch('audit_sizeq_pilot.decode_packets',return_value=p),self.assertRaises(DataGap):alias_debt_exclusion(self.path,'2017-12-29')

    def test_frame_duplicates_block(self):
        with self.assertRaises(DataGap):rows(dict(columns=['a','a'],index=[0],data=[[1,2]]))

if __name__=='__main__':unittest.main()
