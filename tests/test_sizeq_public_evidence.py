import unittest
from assemble_sizeq_signals import public_cash_exclusion,OUT
from sizeq_signals import SignalGap

class PublicEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=(OUT/'601313_2017annual_source.txt').read_text(encoding='utf8')

    def test_future_annual_cannot_repair_january(self):
        for day in ['2018-01-08','2018-01-15','2018-01-22','2018-01-29']:
            with self.assertRaises(SignalGap):public_cash_exclusion(day,self.source)

    def test_missing_cash_or_publication_blocks(self):
        for token in ['-14,784,241.27','2018-02-02','（10-12 月份）']:
            with self.assertRaises(SignalGap):public_cash_exclusion('2018-02-05',self.source.replace(token,''))

    def test_exact_allowed_dates_have_negative_quarter_cash(self):
        for day in ['2018-02-05','2018-02-12']:
            proof=public_cash_exclusion(day,self.source)
            self.assertLess(float(proof['quarter_cash']),0)
            self.assertLess(proof['published'],day)

if __name__=='__main__':unittest.main()
