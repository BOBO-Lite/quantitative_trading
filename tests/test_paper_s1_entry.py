"""S1 纸交易 T+1 入场确认（两段式 / 分钟 §3）。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "paper"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(PAPER))

from entry_confirm import (  # noqa: E402
    approx_next_open_entry,
    confirm_s1_entry,
    load_scan_cards,
    run_entry,
)
import entry_confirm as entry_mod  # noqa: E402
import s1_runner  # noqa: E402


def _minutes(
    day: str = "2026-09-11",
    *,
    open_px: float = 10.05,
    trigger_at: str = "09:50",
    trigger_close: float = 10.35,
    next_open: float = 10.36,
    vwap_level: float = 10.10,
) -> pd.DataFrame:
    """构造开盘 + 窗口内触发 + 下一分钟开盘。"""
    rows = []
    # 09:30 open bar
    rows.append(
        {
            "datetime": f"{day} 09:30:00",
            "open": open_px,
            "high": open_px + 0.05,
            "low": open_px - 0.05,
            "close": open_px,
            "volume": 1000.0,
            "amount": open_px * 1000.0,
        }
    )
    # fillers before trigger with close below signal high
    for hm in ["09:45", "09:46", "09:47", "09:48", "09:49"]:
        if hm >= trigger_at:
            break
        px = open_px + 0.02
        rows.append(
            {
                "datetime": f"{day} {hm}:00",
                "open": px,
                "high": px + 0.02,
                "low": px - 0.02,
                "close": px,
                "volume": 800.0,
                "amount": px * 800.0,
            }
        )
    # trigger bar
    rows.append(
        {
            "datetime": f"{day} {trigger_at}:00",
            "open": trigger_close - 0.02,
            "high": trigger_close + 0.01,
            "low": trigger_close - 0.05,
            "close": trigger_close,
            "volume": 2000.0,
            "amount": vwap_level * 2000.0,  # keep running vwap controllable-ish
        }
    )
    # next minute for fill
    hh, mm = map(int, trigger_at.split(":"))
    mm2 = mm + 1
    hh2 = hh + (1 if mm2 >= 60 else 0)
    mm2 = mm2 % 60
    rows.append(
        {
            "datetime": f"{day} {hh2:02d}:{mm2:02d}:00",
            "open": next_open,
            "high": next_open + 0.02,
            "low": next_open - 0.02,
            "close": next_open + 0.01,
            "volume": 1000.0,
            "amount": next_open * 1000.0,
        }
    )
    return pd.DataFrame(rows)


class ConfirmS1EntryTests(unittest.TestCase):
    def setUp(self):
        self.card = {
            "symbol": "600001",
            "signal_date": "2026-09-10",
            "close": 10.0,
            "high": 10.2,
            "score": 88.0,
            "stop_distance_est": 0.05,
            "abandon_if_stop_gt_6pct": False,
        }

    def test_confirms_first_break_above_high_and_vwap(self):
        mins = _minutes(open_px=10.05, trigger_close=10.35, next_open=10.36)
        out = confirm_s1_entry(self.card, mins)
        self.assertEqual(out["status"], "CONFIRMED")
        self.assertEqual(out["mode"], "FROZEN_MINUTE")
        self.assertAlmostEqual(out["raw_fill"], 10.36, places=4)
        self.assertLessEqual(out["raw_fill"], self.card["close"] * 1.04 + 1e-9)

    def test_rejects_open_gap_too_high(self):
        mins = _minutes(open_px=10.50)  # +5%
        out = confirm_s1_entry(self.card, mins)
        self.assertEqual(out["status"], "REJECTED_OPEN_GAP")

    def test_rejects_open_gap_too_low(self):
        mins = _minutes(open_px=9.80)  # -2%
        out = confirm_s1_entry(self.card, mins)
        self.assertEqual(out["status"], "REJECTED_OPEN_GAP")

    def test_rejects_price_cap_on_next_open(self):
        # gap ok (+1%), trigger ok, but next open > 10*1.04=10.4
        mins = _minutes(open_px=10.10, trigger_close=10.35, next_open=10.45)
        out = confirm_s1_entry(self.card, mins)
        self.assertEqual(out["status"], "REJECTED_PRICE_CAP")

    def test_no_trigger_when_never_above_high(self):
        mins = _minutes(open_px=10.05, trigger_close=10.15, next_open=10.16)  # < high 10.2
        out = confirm_s1_entry(self.card, mins)
        self.assertIn(out["status"], {"NO_TRIGGER_IN_WINDOW", "REJECTED_WINDOW_EXPIRED"})

    def test_empty_minutes_deferred(self):
        out = confirm_s1_entry(self.card, pd.DataFrame())
        self.assertEqual(out["status"], "DEFERRED_NO_MINUTE_DATA")

    def test_fill_uses_next_bar_not_same_bar(self):
        mins = _minutes(trigger_at="09:50", trigger_close=10.40, next_open=10.22)
        out = confirm_s1_entry(self.card, mins)
        self.assertEqual(out["status"], "CONFIRMED")
        self.assertAlmostEqual(out["raw_fill"], 10.22, places=4)
        self.assertNotAlmostEqual(out["raw_fill"], 10.40, places=4)


class ApproxAndRunEntryTests(unittest.TestCase):
    def test_approx_flag_is_labeled_not_frozen(self):
        card = {
            "symbol": "600001",
            "signal_date": "2026-09-10",
            "close": 10.0,
            "high": 10.2,
            "score": 80,
            "stop_distance_est": 0.04,
        }
        daily = pd.DataFrame(
            [
                {"date": "2026-09-10", "open": 9.9, "high": 10.2, "low": 9.8, "close": 10.0, "volume": 1e6},
                {"date": "2026-09-11", "open": 10.1, "high": 10.3, "low": 10.0, "close": 10.2, "volume": 1e6},
            ]
        )
        with mock.patch("entry_confirm.load_or_fetch_bars", return_value=(daily, "test")):
            out = approx_next_open_entry(card)
        self.assertEqual(out["status"], "CONFIRMED_APPROX")
        self.assertEqual(out["mode"], "APPROX_NEXT_OPEN")
        self.assertIn("非 S1_FROZEN_SPEC", out["warning"])

    def test_run_entry_defers_when_minutes_missing_no_silent_open(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            runtime = td_path / "runtime"
            reports = runtime / "reports"
            signal_dir = reports / "2026-09-10"
            signal_dir.mkdir(parents=True)
            scan = {
                "tag": "UNIVERSE_REDUCED",
                "signal_date": "2026-09-10",
                "gate": {"ok": True, "gate_on": True, "reason": "ON"},
                "candidates": [
                    {
                        "symbol": "600001",
                        "signal_date": "2026-09-10",
                        "close": 10.0,
                        "high": 10.2,
                        "score": 90.0,
                        "stop_distance_est": 0.04,
                        "abandon_if_stop_gt_6pct": False,
                        "tag": "UNIVERSE_REDUCED",
                    }
                ],
            }
            (signal_dir / "scan.json").write_text(
                json.dumps(scan, ensure_ascii=False), encoding="utf-8"
            )
            cfg = {
                "mode": "s1_only",
                "capital": 100000.0,
                "runtime_dir": str(runtime),
                "account_file": str(runtime / "account.json"),
                "ledger_file": str(runtime / "ledger.csv"),
                "nav_file": str(runtime / "daily_nav.csv"),
                "reports_dir": str(reports),
            }

            def _paths(c=None):
                return {
                    "runtime": runtime,
                    "account": runtime / "account.json",
                    "ledger": runtime / "ledger.csv",
                    "nav": runtime / "daily_nav.csv",
                    "reports": reports,
                    "data": td_path / "data",
                }

            with mock.patch.object(s1_runner, "ensure_runtime_dirs", side_effect=lambda c=None: _paths()):
                with mock.patch.object(s1_runner, "load_paper_config", return_value=cfg):
                    s1_runner.init_account(100000.0, force=True, cfg=cfg)

            with mock.patch.object(entry_mod, "ensure_runtime_dirs", side_effect=lambda c=None: _paths()):
                with mock.patch.object(entry_mod, "load_paper_config", return_value=cfg):
                    with mock.patch.object(
                        entry_mod,
                        "fetch_public_minutes",
                        return_value=(None, {"reason": "mock: no public minutes"}),
                    ):
                        out = run_entry(
                            entry_date="2026-09-11",
                            signal_date="2026-09-10",
                            dry_run=True,
                            approx_next_open=False,
                            cfg=cfg,
                        )
            self.assertEqual(out["n_cards"], 1)
            self.assertEqual(len(out["filled"]), 0)
            self.assertEqual(len(out["deferred"]), 1)
            self.assertEqual(out["deferred"][0]["status"], "DEFERRED_NO_MINUTE_DATA")
            self.assertIn("禁止静默", out["deferred"][0]["reason"] + out["deferred"][0].get("hint", ""))

    def test_load_scan_cards_from_signal_date(self):
        with tempfile.TemporaryDirectory() as td:
            reports = Path(td) / "reports"
            d = reports / "2026-09-10"
            d.mkdir(parents=True)
            payload = {"signal_date": "2026-09-10", "candidates": [{"symbol": "600519"}]}
            (d / "scan.json").write_text(json.dumps(payload), encoding="utf-8")
            loaded, path = load_scan_cards(reports, signal_date="2026-09-10")
            self.assertEqual(loaded["candidates"][0]["symbol"], "600519")
            self.assertTrue(path.exists())

    def test_cli_entry_help_mentions_approx_default_off(self):
        from cli import build_parser

        p = build_parser()
        # ensure subcommand registered
        ns = p.parse_args(["entry", "--dry-run"])
        self.assertTrue(ns.dry_run)
        self.assertFalse(ns.approx_next_open)


if __name__ == "__main__":
    unittest.main()
