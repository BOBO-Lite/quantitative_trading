from pathlib import Path
import ast
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "adapters" / "supermind_daily_parts_export.py"


class SuperMindDailyPartsExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SCRIPT.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_script_compiles(self):
        compile(self.source, str(SCRIPT), "exec")

    def test_batch_size_is_five(self):
        assignments = {
            node.targets[0].id: ast.literal_eval(node.value)
            for node in self.tree.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in {"BATCH_SIZE", "END_BATCH"}
        }
        self.assertEqual(assignments["BATCH_SIZE"], 5)
        self.assertEqual(assignments["END_BATCH"], 2)

    def test_restricted_operations_are_absent(self):
        lowered = self.source.lower()
        for forbidden in ("open(", "pathlib", "getattr", "hasattr"):
            self.assertNotIn(forbidden, lowered)

    def test_no_order_or_account_api(self):
        lowered = self.source.lower()
        for forbidden in (
            "tradeapi", "order_target", "order_value", "order_volume",
            "cancel_order", "get_account", "get_position",
        ):
            self.assertNotIn(forbidden, lowered)

    def test_uses_pandas_json_writer_and_read_only_sources(self):
        self.assertIn("pd.Series(payload, dtype=object).to_json", self.source)
        self.assertIn("get_all_securities", self.source)
        self.assertIn("get_price", self.source)


if __name__ == "__main__":
    unittest.main()
