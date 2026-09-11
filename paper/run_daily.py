#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可选双账本日更（非默认）。默认请用: python -m paper.cli init|run

本脚本保留 A=510880 + B=S1 双账本演练；默认单账本 10 万 S1 见 paper.cli。
纯纸面；禁止真实券商下单。不构成投资建议。
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PAPER_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PAPER_DIR))

from broker import (  # noqa: E402
    ensure_ledger_header,
    load_account,
    mark_to_market,
    nav_row_from_account,
    new_account,
    save_account,
    upsert_nav,
    NAV_FIELDS,
)
from ledger_a import ACCOUNT_A, LEDGER_A, NAV_A, daily_mtm as mtm_a, initialize_buy_if_flat  # noqa: E402
from ledger_b import (  # noqa: E402
    ACCOUNT_B,
    LEDGER_B,
    NAV_B,
    daily_mtm as mtm_b,
    maybe_auto_fill,
    scan_candidates,
)

CHINA = ZoneInfo("Asia/Shanghai")
NAV_COMBINED = PAPER_DIR / "nav_combined.csv"
STARTED = "2026-09-11T10:51:00+08:00"


def ensure_initialized() -> None:
    PAPER_DIR.joinpath("accounts").mkdir(parents=True, exist_ok=True)
    PAPER_DIR.joinpath("data").mkdir(parents=True, exist_ok=True)
    PAPER_DIR.joinpath("reports").mkdir(parents=True, exist_ok=True)
    if not ACCOUNT_A.exists():
        save_account(new_account("A_main", 25000.0, "红利ETF-510880-buyhold", STARTED), ACCOUNT_A)
    if not ACCOUNT_B.exists():
        save_account(new_account("B_s1", 25000.0, "S1-U0-UNIVERSE_REDUCED", STARTED), ACCOUNT_B)
    ensure_ledger_header(LEDGER_A)
    ensure_ledger_header(LEDGER_B)
    for path, book in [(NAV_A, "A"), (NAV_B, "B")]:
        if not path.exists() or path.stat().st_size == 0:
            acc = load_account(ACCOUNT_A if book == "A" else ACCOUNT_B)
            upsert_nav(path, nav_row_from_account(acc, "2026-09-11", note="day0 init"))
    if not NAV_COMBINED.exists() or NAV_COMBINED.stat().st_size == 0:
        a = load_account(ACCOUNT_A)
        b = load_account(ACCOUNT_B)
        _write_combined("2026-09-11", a, b, note="day0 init")


def _write_combined(trade_date: str, a: dict, b: dict, note: str = "") -> None:
    fields = [
        "date", "equity_A", "equity_B", "equity_combined",
        "cash_A", "cash_B", "peak_combined", "drawdown_combined", "note",
    ]
    eq_a = float(a["equity"])
    eq_b = float(b["equity"])
    eq = eq_a + eq_b
    # peak：读已有最大 combined 或当前
    peak = eq
    rows: list[dict[str, str]] = []
    if NAV_COMBINED.exists() and NAV_COMBINED.stat().st_size > 0:
        with NAV_COMBINED.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("date") == trade_date:
                    continue
                rows.append(r)
                try:
                    peak = max(peak, float(r.get("peak_combined") or 0), float(r.get("equity_combined") or 0))
                except ValueError:
                    pass
    peak = max(peak, eq)
    dd = 1.0 - eq / peak if peak > 0 else 0.0
    rows.append(
        {
            "date": trade_date,
            "equity_A": f"{eq_a:.2f}",
            "equity_B": f"{eq_b:.2f}",
            "equity_combined": f"{eq:.2f}",
            "cash_A": f"{float(a['cash']):.2f}",
            "cash_B": f"{float(b['cash']):.2f}",
            "peak_combined": f"{peak:.2f}",
            "drawdown_combined": f"{dd:.4f}",
            "note": note,
        }
    )
    rows.sort(key=lambda r: r["date"])
    with NAV_COMBINED.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def write_summary(
    report_dir: Path,
    trade_date: str,
    a_init: dict,
    a_mtm: dict,
    b_scan: dict,
    b_mtm: dict,
    auto_fill: dict | None,
) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    a_acc = a_mtm.get("account") or load_account(ACCOUNT_A)
    b_acc = b_mtm.get("account") or load_account(ACCOUNT_B)
    gate = b_scan.get("gate") or {}
    lines = [
        f"# 纸面双账本日摘要 {trade_date}",
        "",
        "> **Paper only / 历史与模拟研究。不构成投资建议。**",
        "",
        "## 标签",
        "",
        "- 账本 B：`UNIVERSE_REDUCED`（公开缩减宇宙，非全市场 S1）",
        f"- 生成时间：{datetime.now(CHINA).isoformat(timespec='seconds')}",
        "",
        "## 账本 A（Main / 510880）",
        "",
        f"- 动作：{a_init.get('action')}",
        f"- 成交：{a_init.get('filled')}",
        f"- 说明：{'; '.join(a_init.get('messages') or []) or '—'}",
        f"- 现金：{float(a_acc['cash']):.2f} RMB",
        f"- 持仓市值：{float(a_acc.get('positions_mv') or 0):.2f} RMB",
        f"- 权益：{float(a_acc['equity']):.2f} RMB",
        f"- 持仓：{json.dumps(a_acc.get('positions') or [], ensure_ascii=False)}",
        f"- 行情源：{a_mtm.get('source') or a_init.get('source') or '—'}",
        "",
        "## 账本 B（S1 U0 / Satellite）",
        "",
        f"- **UNIVERSE_REDUCED** 宇宙来源：`{b_scan.get('universe_source')}`",
        f"- 宇宙规模：{b_scan.get('universe_size')}",
        f"- 市场开关：{'ON' if gate.get('gate_on') else 'OFF'} | {gate.get('reason')}",
        f"- 开关数据日：{gate.get('date', '—')} close={gate.get('close', '—')} MA20={gate.get('ma20', '—')} MA60={gate.get('ma60', '—')}",
        f"- 信号日：{b_scan.get('signal_date', '—')}",
        f"- 候选数：{len(b_scan.get('candidates') or [])}",
        f"- 消息：{'; '.join(b_scan.get('messages') or []) or '—'}",
        f"- 错误：{'; '.join(b_scan.get('errors') or []) or '无'}",
        f"- 现金：{float(b_acc['cash']):.2f} RMB",
        f"- 权益：{float(b_acc['equity']):.2f} RMB",
        f"- 持仓数：{len(b_acc.get('positions') or [])}",
        "",
        "### 延后规则（分时入场）",
        "",
    ]
    for d in b_scan.get("deferred_rules") or []:
        lines.append(f"- {d}")
    lines.extend(["", "### 候选卡片", ""])
    cands = b_scan.get("candidates") or []
    if not cands:
        lines.append("_无候选或门控关闭 / 数据不足_")
    else:
        for c in cands[:20]:
            lines.append(
                f"- `{c['symbol']}` score={c.get('score')} close={c.get('close')} "
                f"stop_est={c.get('stop_distance_est')} abandon={c.get('abandon_if_stop_gt_6pct')} "
                f"tag={c.get('tag')}"
            )
    if auto_fill is not None:
        lines.extend(
            [
                "",
                "### --auto-paper-fill 结果",
                "",
                f"```json",
                json.dumps(auto_fill, ensure_ascii=False, indent=2),
                "```",
            ]
        )
    eq_c = float(a_acc["equity"]) + float(b_acc["equity"])
    lines.extend(
        [
            "",
            "## 合计",
            "",
            f"- 组合权益：{eq_c:.2f} RMB（A {float(a_acc['equity']):.2f} + B {float(b_acc['equity']):.2f}）",
            f"- 初始虚拟本金：50,000 RMB（A/B 各 25,000）",
            "",
            "## 免责声明",
            "",
            "本摘要仅记录纸面规则执行结果，不构成任何投资建议；纸面成交 ≠ 实盘。",
            "",
        ]
    )
    path = report_dir / "summary.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    (report_dir / "B_scan.json").write_text(json.dumps(b_scan, ensure_ascii=False, indent=2), encoding="utf-8")
    (report_dir / "A_init.json").write_text(json.dumps(a_init, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if auto_fill is not None:
        (report_dir / "B_auto_fill.json").write_text(json.dumps(auto_fill, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="虚拟双账本日更（paper only）")
    parser.add_argument("--date", dest="asof", default=None, help="业务日 YYYY-MM-DD，默认上海当日")
    parser.add_argument(
        "--auto-paper-fill",
        action="store_true",
        help="对 B 候选按次日开盘近似自动纸面成交（默认只出卡片）",
    )
    parser.add_argument("--max-universe", type=int, default=30, help="缩减宇宙最大股票数")
    args = parser.parse_args(argv)

    ensure_initialized()
    asof = args.asof or datetime.now(CHINA).strftime("%Y-%m-%d")
    report_dir = PAPER_DIR / "reports" / asof

    # A：建仓（若空）+ MTM
    a_init = initialize_buy_if_flat(asof=asof)
    a_mtm = mtm_a(asof=asof, note=a_init.get("action") or "mtm")

    # B：扫描 + MTM（默认不成交）
    try:
        b_scan = scan_candidates(asof=asof, max_names=args.max_universe)
    except Exception as exc:  # noqa: BLE001
        b_scan = {
            "tag": "UNIVERSE_REDUCED",
            "gate": {"ok": False, "gate_on": False, "reason": str(exc)},
            "candidates": [],
            "errors": [str(exc)],
            "messages": [f"扫描异常: {exc}"],
            "deferred_rules": [],
            "universe_source": "error",
            "universe_size": 0,
        }
    auto_fill = None
    if args.auto_paper_fill:
        auto_fill = maybe_auto_fill(b_scan, asof=asof)
    b_mtm = mtm_b(asof=asof, note="UNIVERSE_REDUCED|" + ("gate_on" if b_scan.get("gate", {}).get("gate_on") else "gate_off"))

    a_acc = a_mtm["account"]
    b_acc = b_mtm["account"]
    _write_combined(asof, a_acc, b_acc, note="daily")

    summary = write_summary(report_dir, asof, a_init, a_mtm, b_scan, b_mtm, auto_fill)
    print(f"[ok] summary -> {summary}")
    print(f"A equity={float(a_acc['equity']):.2f} cash={float(a_acc['cash']):.2f} pos={len(a_acc.get('positions') or [])}")
    print(f"B equity={float(b_acc['equity']):.2f} cash={float(b_acc['cash']):.2f} gate={b_scan.get('gate', {}).get('gate_on')} cands={len(b_scan.get('candidates') or [])}")
    print("UNIVERSE_REDUCED | paper only | not investment advice")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
