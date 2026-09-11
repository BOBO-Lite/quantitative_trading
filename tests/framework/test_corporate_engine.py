import copy,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from validate_corporate_execution import run_window,require_native_tax_parity
class CorporateEngineTests(unittest.TestCase):
    def test_native_month_end_disagreement_is_blocked(self):
        with self.assertRaisesRegex(ValueError,'自然月边界'):
            require_native_tax_parity('2025-02-28','2025-03-31')
    @classmethod
    def setUpClass(cls):cls.cases=json.loads((ROOT/'reports/s2_research/corporate_actions/verified_windows.json').read_text(encoding='utf-8'))['cases']
    def test_eight_real_dividend_cost_cases(self):
        for case in self.cases:
            for multiplier in (1.,1.5):
                with self.subTest(symbol=case['symbol'],day=case['dates'][0],multiplier=multiplier):
                    self.assertEqual(run_window(case,multiplier)['status'],'PASS')
    def test_synthetic_deferred_payment_after_position_closed(self):
        case=copy.deepcopy(self.cases[0]);case['events'][0]['pay_date']=case['dates'][-1]
        result=run_window(case,sell_day=case['dates'][1])
        self.assertEqual(result['status'],'PASS')
        self.assertEqual(result['snapshot']['dividend_receivable'],0)
        self.assertEqual(len(result['rqalpha']['taxes']),1)
if __name__=='__main__':unittest.main()
