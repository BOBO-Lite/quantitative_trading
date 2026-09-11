import unittest
from unittest.mock import patch
from exit_horizon_audit import TraceRules
from e1_reentry_pair import ReentryRules

class ExitTraceTests(unittest.TestCase):
    def setUp(self):
        self.rules=TraceRules()
        self.p=dict(entry_date='2020-01-02',stop=9,entry_price=10,initial_r=1)
        self.bar=dict(symbol='000001.SZ',datetime='2020-01-03T15:00:00',close=8.9,
            confirmation=dict(asof='2020-01-02'))
    def call(self):
        return self.rules.exit_reason(self.p,self.bar,'trend_breakout',.03,2,True)
    def test_pending_exit_keeps_first_cause(self):
        with patch.object(ReentryRules,'exit_reason',side_effect=['close_confirmed_stop','cash_defense']):
            self.assertEqual(self.call(),'close_confirmed_stop')
            self.bar['datetime']='2020-01-06T15:00:00'
            self.assertEqual(self.call(),'cash_defense')
        record=next(iter(self.rules.first_triggers.values()))
        self.assertEqual(record['reason'],'close_confirmed_stop')
        self.assertEqual(record['trigger_time'],'2020-01-03T15:00:00')
    def test_no_signal_does_not_create_exit(self):
        with patch.object(ReentryRules,'exit_reason',return_value=None):
            self.assertIsNone(self.call())
        self.assertEqual(self.rules.first_triggers,{})
    def test_repurchase_keeps_separate_cause(self):
        with patch.object(ReentryRules,'exit_reason',side_effect=['time_exit','cash_defense']):
            self.call()
            self.p['entry_date']='2020-02-03'
            self.bar['datetime']='2020-02-04T15:00:00'
            self.call()
        self.assertEqual(len(self.rules.first_triggers),2)

if __name__=='__main__': unittest.main()
