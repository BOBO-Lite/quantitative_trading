import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters import tushare_readonly


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps({
            "code": 0,
            "data": {"fields": ["ts_code", "close"], "items": [["601975.SH", 4.24]]},
        }).encode()


class TushareReadonlyTests(unittest.TestCase):
    @patch.dict(os.environ, {"TUSHARE_TOKEN": "test-token"})
    @patch("urllib.request.urlopen", return_value=_Response())
    def test_quote_response_is_mapped_to_dict(self, mocked):
        rows = tushare_readonly.realtime_quotes(["601975.SH"])
        self.assertEqual(rows, [{"ts_code": "601975.SH", "close": 4.24}])
        request = mocked.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload["api_name"], "rt_k")
        self.assertEqual(payload["params"]["ts_code"], "601975.SH")

    def test_invalid_minute_frequency_fails_closed(self):
        with self.assertRaises(ValueError):
            tushare_readonly.realtime_minutes(["601975.SH"], "2MIN")


if __name__ == "__main__":
    unittest.main()
