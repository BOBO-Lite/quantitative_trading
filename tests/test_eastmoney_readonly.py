import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from adapters import eastmoney_readonly as em


class EastMoneyReadonlyTests(unittest.TestCase):
    def test_security_id_mapping(self):
        self.assertEqual(em._secid("601975.SH"), "1.601975")
        self.assertEqual(em._secid("000001.SZ"), "0.000001")
        self.assertEqual(em._secid("920001.BJ"), "0.920001")

    def test_quote_scaling(self):
        observed_at = int(datetime.now(em.CHINA_TZ).timestamp())
        payload = {"data": {"diff": [{"f2": 11.92, "f3": 1.71, "f4": 0.2,
                            "f5": 100, "f6": 200.5, "f12": "000001", "f14": "测试",
                            "f15": 11.96, "f16": 11.65, "f17": 11.68, "f18": 11.72,
                            "f124": observed_at}]}}
        with patch.object(em, "_request_json", return_value=payload):
            row = em.realtime_quotes(["000001.SZ"])[0]
        self.assertEqual(row["close"], 11.92)
        self.assertEqual(row["pct_change"], 1.71)
        self.assertEqual(row["provider"], "eastmoney_public")

    def test_minute_rows(self):
        payload = {"data": {"trends": ["2026-09-01 09:31,10,10.1,10.2,9.9,100,1000,10.05"]}}
        with patch.object(em, "_request_json", return_value=payload):
            row = em.realtime_minutes(["601975.SH"])[0]
        self.assertEqual(row["datetime"], "2026-09-01 09:31")
        self.assertEqual(row["close"], 10.1)

    def test_daily_rows(self):
        payload = {"data": {"klines": ["2026-08-31,10,10.2,10.3,9.8,100,1000,5,2,0.2,1.5"]}}
        with patch.object(em, "_request_json", return_value=payload):
            row = em.historical_daily(["601975.SH"], 1)[0]
        self.assertEqual(row["trade_date"], "2026-08-31")
        self.assertEqual(row["turnover_rate"], 1.5)

    def test_lunch_session(self):
        tz = timezone(timedelta(hours=8))
        status = em.market_status(datetime(2026, 9, 1, 12, 0, tzinfo=tz))
        self.assertEqual(status["session"], "LUNCH_BREAK")

    def test_invalid_code_is_rejected(self):
        with self.assertRaises(ValueError):
            em.realtime_quotes(["AAPL"])


if __name__ == "__main__":
    unittest.main()
