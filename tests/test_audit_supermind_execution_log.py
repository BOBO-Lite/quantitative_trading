"""用独立现金算式验证日志审计器，防止倒序页面产生伪结论。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from audit_supermind_execution_log import audit_log


def fixture(reverse=False):
    events = [
        "BAR 2019-04-17 09:46:00 000001.SZ open=14.35 close=14.33 vol=676400.0 amount=9697110.6",
        "FILL 2019-04-17 09:45:00 Trade({'order_book_id': '000001.SZ', 'side': SIDE.BUY, 'last_price': 14.36435, 'last_quantity': 500, 'commission': 5.0, 'tax': 0, 'transaction_cost': 5.0})",
        "PROBE_END 2019-04-17 15:30:00 StockAccount({'available_cash': 22812.825})",
        "BAR 2019-04-19 09:46:00 000001.SZ open=14.45 close=14.47 vol=515700.0 amount=7464367.2",
        "FILL 2019-04-19 09:45:00 Trade({'order_book_id': '000001.SZ', 'side': SIDE.SELL, 'last_price': 14.43555, 'last_quantity': 500, 'commission': 5.0, 'tax': 7.217775, 'transaction_cost': 12.217775})",
        "PROBE_END 2019-04-19 15:30:00 StockAccount({'available_cash': 30018.382225})",
        '回测结束',
    ]
    return '\n'.join(reversed(events) if reverse else events)


class ExecutionLogAuditTests(unittest.TestCase):
    def test_forward_and_reverse_logs_reconcile_same_cash(self):
        for reverse in (False, True):
            report = audit_log(fixture(reverse))
            self.assertTrue(report['cash_reconciles'])
            self.assertTrue(report['all_next_open_prices_match'])
            self.assertAlmostEqual(report['reconstructed_cash'], 30018.382225)
            self.assertFalse(report['formal_strategy_validated'])

    def test_mismatch_does_not_pass(self):
        report = audit_log(fixture().replace('30018.382225', '31018.382225'))
        self.assertFalse(report['cash_reconciles'])
        self.assertEqual(report['status'], 'INCOMPLETE_OR_MISMATCH')

    def test_missing_economic_bar_is_rejected(self):
        with self.assertRaises(ValueError):
            audit_log(fixture().replace('BAR 2019-04-19 09:46:00', 'BAR 2019-04-19 09:47:00'))

    def test_unfinished_log_is_not_complete(self):
        self.assertFalse(audit_log(fixture().replace('回测结束', ''))['completed'])


if __name__ == '__main__':
    unittest.main()
