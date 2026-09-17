#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S1 单账本纸交易 CLI（默认 100000 CNY / UNIVERSE_REDUCED）。

用法示例：
  python -m paper.cli init
  python -m paper.cli dry-run          # T 日收盘扫描演练
  python -m paper.cli run --date ...   # T 日 15:30 收盘扫描（出卡片）
  python -m paper.cli entry            # T+1 09:45–10:30 分时入场确认
  python -m paper.cli status
  python -m paper.cli performance

纯纸面；禁止真实券商下单。不构成投资建议。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PAPER_DIR = Path(__file__).resolve().parent
if str(PAPER_DIR) not in sys.path:
    sys.path.insert(0, str(PAPER_DIR))
ROOT = PAPER_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from paths import DEFAULT_CAPITAL, load_paper_config  # noqa: E402
from s1_runner import init_account, performance, run_day, status  # noqa: E402
from entry_confirm import run_entry  # noqa: E402


def _print_json(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def cmd_init(args: argparse.Namespace) -> int:
    capital = float(args.capital)
    result = init_account(capital, force=bool(args.force))
    print(f"[init] created={result['created']} path={result['path']}")
    print(f"[init] {result['message']}")
    acc = result["account"]
    print(
        f"[init] cash={float(acc['cash']):.2f} equity={float(acc['equity']):.2f} "
        f"tag=UNIVERSE_REDUCED status=NOT_VALIDATED"
    )
    print("paper only | no live broker | not investment advice")
    return 0


def cmd_dry_run(args: argparse.Namespace) -> int:
    out = run_day(
        asof=args.date,
        dry_run=True,
        auto_paper_fill=False,
        max_universe=args.max_universe,
    )
    _print_result(out)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    out = run_day(
        asof=args.date,
        dry_run=False,
        auto_paper_fill=bool(args.auto_paper_fill),
        max_universe=args.max_universe,
    )
    _print_result(out)
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    st = status()
    if not st.get("ok"):
        print(f"[status] ERROR: {st.get('error')} | {st.get('hint', '')}")
        return 1
    gate = st.get("market_gate") or {}
    print("[status] mode=s1_only | UNIVERSE_REDUCED | NOT_VALIDATED")
    print(
        f"[status] capital_init={st.get('initial_capital')} cash={st['cash']:.2f} "
        f"equity={st['equity']:.2f} peak={st['peak_equity']:.2f} "
        f"dd={st['drawdown_from_peak']:.4f} positions={st['n_positions']}"
    )
    print(
        f"[status] gate={'ON' if gate.get('gate_on') else 'OFF'} "
        f"reason={gate.get('reason')} date={gate.get('date')}"
    )
    if st.get("positions"):
        print(f"[status] positions={json.dumps(st['positions'], ensure_ascii=False)}")
    print(f"[status] account={st['paths']['account']}")
    print("paper only | no live broker")
    return 0


def cmd_performance(_: argparse.Namespace) -> int:
    perf = performance()
    if not perf.get("ok"):
        print(f"[perf] ERROR: {perf.get('error')}")
        return 1
    print("[perf] UNIVERSE_REDUCED | NOT_VALIDATED")
    print(
        f"[perf] initial={perf['initial_capital']:.2f} equity={perf['equity']:.2f} "
        f"return_pct={perf['return_pct']:.4f}% peak={perf['peak_equity']:.2f} "
        f"dd={perf['drawdown_from_peak']:.4f}"
    )
    print(
        f"[perf] nav_days={perf['n_nav_days']} trades={perf['n_trades']} "
        f"positions={perf['n_positions']}"
    )
    print(f"[perf] {perf['disclaimer']}")
    return 0



def cmd_entry(args: argparse.Namespace) -> int:
    """T+1 早盘入场：读取上一交易日候选卡片，按 S1_FROZEN_SPEC §3 确认。"""
    out = run_entry(
        entry_date=args.date,
        signal_date=args.signal_date,
        scan_path=args.scan,
        dry_run=bool(args.dry_run),
        approx_next_open=bool(args.approx_next_open),
        persist_fills=not bool(args.dry_run),
    )
    tag = "entry-dry" if out.get("dry_run") else "entry"
    print(f"[{tag}] entry_date={out.get('entry_date')} signal_date={out.get('signal_date')} UNIVERSE_REDUCED")
    print(f"[{tag}] scan={out.get('scan_file')}")
    print(
        f"[{tag}] cards={out.get('n_cards')} filled={len(out.get('filled') or [])} "
        f"deferred={len(out.get('deferred') or [])} rejected={len(out.get('rejected') or [])} "
        f"skipped={len(out.get('skipped') or [])}"
    )
    if out.get("approx_next_open"):
        print(f"[{tag}] WARNING: --approx-next-open 显式近似，非冻结规格原样")
    for d in (out.get("deferred") or [])[:10]:
        print(f"[{tag}] deferred {d.get('symbol')}: {d.get('status')} | {d.get('reason')}")
    for r in (out.get("rejected") or [])[:10]:
        print(f"[{tag}] rejected {r.get('symbol')}: {r.get('status')} | {r.get('reason')}")
    for f in (out.get("filled") or [])[:10]:
        print(
            f"[{tag}] filled {f.get('symbol')} qty={f.get('quantity')} "
            f"raw={f.get('raw_fill')} mode={f.get('mode')} persisted={f.get('persisted')}"
        )
    if out.get("messages"):
        print(f"[{tag}] messages: {'; '.join(out['messages'])}")
    if out.get("report"):
        print(f"[{tag}] report -> {out['report']}")
    print("paper only | minute confirm or explicit approx | no silent next-open freeze fake")
    return 0 if out.get("ok", True) else 1


def cmd_dual(args: argparse.Namespace) -> int:
    """可选：调用旧双账本日更（非默认）。"""
    from run_daily import main as dual_main

    argv = []
    if args.date:
        argv.extend(["--date", args.date])
    if args.auto_paper_fill:
        argv.append("--auto-paper-fill")
    if args.max_universe:
        argv.extend(["--max-universe", str(args.max_universe)])
    print("[dual] 可选双账本模式（非默认）；默认请用 init/run")
    return dual_main(argv)


def _print_result(out: dict) -> None:
    tag = "dry-run" if out.get("dry_run") else "run"
    print(f"[{tag}] date={out.get('date')} UNIVERSE_REDUCED NOT_VALIDATED")
    print(
        f"[{tag}] gate={'ON' if out.get('gate_on') else 'OFF'} "
        f"reason={out.get('gate_reason')}"
    )
    print(
        f"[{tag}] universe_size={out.get('universe_size')} "
        f"source={out.get('universe_source')} candidates={out.get('candidates')}"
    )
    print(
        f"[{tag}] cash={out.get('cash'):.2f} equity={out.get('equity'):.2f} "
        f"positions={out.get('n_positions')}"
    )
    if out.get("scan_messages"):
        print(f"[{tag}] messages: {'; '.join(out['scan_messages'])}")
    if out.get("scan_errors"):
        print(f"[{tag}] errors: {'; '.join(out['scan_errors'])}")
    if out.get("mtm_errors"):
        print(f"[{tag}] mtm_errors: {'; '.join(out['mtm_errors'])}")
    print(f"[{tag}] summary -> {out.get('summary')}")
    print("paper only | public data | no fabricated fills when gate OFF / no quotes")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="paper.cli",
        description="A股 S1 单账本纸交易（默认本金 100000 CNY，UNIVERSE_REDUCED）",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="初始化纸账户（默认 100000）")
    p_init.add_argument("--capital", type=float, default=DEFAULT_CAPITAL)
    p_init.add_argument("--force", action="store_true", help="删除 runtime 账本后重建")
    p_init.set_defaults(func=cmd_init)

    p_dry = sub.add_parser("dry-run", help="单日演练：扫描+预览，不持久化成交")
    p_dry.add_argument("--date", default=None, help="YYYY-MM-DD，默认上海当日")
    p_dry.add_argument("--max-universe", type=int, default=30)
    p_dry.set_defaults(func=cmd_dry_run)

    p_run = sub.add_parser("run", help="T日收盘扫描+MTM（默认只出卡片；入场用 entry）")
    p_run.add_argument("--date", default=None)
    p_run.add_argument("--max-universe", type=int, default=30)
    p_run.add_argument(
        "--auto-paper-fill",
        action="store_true",
        help="旧近似：次日开盘成交（非冻结规格）；正式入场请用 entry",
    )
    p_run.set_defaults(func=cmd_run)

    p_st = sub.add_parser("status", help="查看账户与市场开关")
    p_st.set_defaults(func=cmd_status)

    p_pf = sub.add_parser("performance", help="查看净值与收益率")
    p_pf.set_defaults(func=cmd_performance)


    p_entry = sub.add_parser(
        "entry",
        help="T+1 早盘入场：读昨日候选卡片，公开分钟按 §3 确认（默认不成交近似）",
    )
    p_entry.add_argument("--date", default=None, help="入场日 YYYY-MM-DD，默认上海当日")
    p_entry.add_argument("--signal-date", default=None, help="信号日（T日）；默认取前一交易日 scan")
    p_entry.add_argument("--scan", default=None, help="直接指定 scan.json 路径")
    p_entry.add_argument("--dry-run", action="store_true", help="确认但不持久化成交")
    p_entry.add_argument(
        "--approx-next-open",
        action="store_true",
        help="显式用次日开盘近似（非冻结规格；默认关闭，禁止静默启用）",
    )
    p_entry.set_defaults(func=cmd_entry)

    p_dual = sub.add_parser("dual", help="可选：旧双账本日更（非默认）")
    p_dual.add_argument("--date", default=None)
    p_dual.add_argument("--max-universe", type=int, default=30)
    p_dual.add_argument("--auto-paper-fill", action="store_true")
    p_dual.set_defaults(func=cmd_dual)

    return p


def main(argv: list[str] | None = None) -> int:
    # 确保默认配置存在且为本金 10 万
    cfg = load_paper_config()
    if float(cfg.get("capital", 0)) != DEFAULT_CAPITAL:
        print(
            f"[warn] config capital={cfg.get('capital')} != {DEFAULT_CAPITAL}; "
            "CLI init 仍可用 --capital 覆盖"
        )
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
