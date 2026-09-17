"""单账本 S1 纸交易日更（公开行情 / UNIVERSE_REDUCED）。不对接券商。"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
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
)
from data_feed import latest_close, load_or_fetch_bars, market_gate_csi500  # noqa: E402
from ledger_b import maybe_auto_fill, scan_candidates  # noqa: E402
from paths import DEFAULT_CAPITAL, ensure_runtime_dirs, load_paper_config  # noqa: E402

CHINA = ZoneInfo("Asia/Shanghai")

# 让 ledger_b 的 ACCOUNT_B 等指向 runtime（初始化后覆盖）
import ledger_b as _lb  # noqa: E402


def _bind_runtime(paths: dict[str, Path]) -> None:
    _lb.ACCOUNT_B = paths["account"]
    _lb.LEDGER_B = paths["ledger"]
    _lb.NAV_B = paths["nav"]


def init_account(
    capital: float = DEFAULT_CAPITAL,
    *,
    force: bool = False,
    cfg: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """初始化单账本 S1 纸账户到 paper/runtime/。不与旧双账本混账。"""
    cfg = cfg or load_paper_config()
    paths = ensure_runtime_dirs(cfg)
    _bind_runtime(paths)
    if paths["account"].exists() and not force:
        acc = load_account(paths["account"])
        return {
            "created": False,
            "account": acc,
            "path": str(paths["account"]),
            "message": "账户已存在；如需重建请传 --force（会清空旧 runtime 账本）",
        }
    if force:
        for key in ("account", "ledger", "nav"):
            p = paths[key]
            if p.exists():
                p.unlink()
    started = datetime.now(CHINA).isoformat(timespec="seconds")
    acc = new_account(
        book="S1_paper",
        cash=float(capital),
        strategy="S1.1-U0-UNIVERSE_REDUCED-NOT_VALIDATED",
        started_at=started,
    )
    acc["initial_capital"] = float(capital)
    acc["universe_tag"] = "UNIVERSE_REDUCED"
    acc["strategy_status"] = "NOT_VALIDATED"
    acc["market_data"] = "public"
    acc["note"] = (
        "虚拟纸面账户；公开行情缩减宇宙 UNIVERSE_REDUCED；"
        "禁止真实券商下单；S1.1 状态 NOT_VALIDATED，不宣称稳定盈利。"
    )
    save_account(acc, paths["account"])
    ensure_ledger_header(paths["ledger"])
    trade_date = datetime.now(CHINA).strftime("%Y-%m-%d")
    upsert_nav(
        paths["nav"],
        nav_row_from_account(acc, trade_date, note="init S1-only capital=%s" % capital),
    )
    return {"created": True, "account": acc, "path": str(paths["account"]), "message": "initialized"}


def status(cfg: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    cfg = cfg or load_paper_config()
    paths = ensure_runtime_dirs(cfg)
    _bind_runtime(paths)
    if not paths["account"].exists():
        return {"ok": False, "error": "账户未初始化", "hint": "先运行: python -m paper.cli init"}
    acc = load_account(paths["account"])
    gate = market_gate_csi500()
    return {
        "ok": True,
        "mode": "s1_only",
        "strategy_status": acc.get("strategy_status", "NOT_VALIDATED"),
        "universe_tag": "UNIVERSE_REDUCED",
        "initial_capital": acc.get("initial_capital", acc.get("peak_equity")),
        "cash": float(acc["cash"]),
        "equity": float(acc["equity"]),
        "peak_equity": float(acc["peak_equity"]),
        "drawdown_from_peak": float(acc.get("drawdown_from_peak") or 0),
        "n_positions": len(acc.get("positions") or []),
        "positions": acc.get("positions") or [],
        "exposure_pct": float(acc.get("exposure_pct") or 0),
        "market_gate": gate,
        "paths": {k: str(v) for k, v in paths.items()},
        "account_updated_at": acc.get("updated_at"),
    }


def performance(cfg: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    import csv

    cfg = cfg or load_paper_config()
    paths = ensure_runtime_dirs(cfg)
    if not paths["account"].exists():
        return {"ok": False, "error": "账户未初始化"}
    acc = load_account(paths["account"])
    initial = float(acc.get("initial_capital") or 100000.0)
    equity = float(acc["equity"])
    ret = (equity / initial - 1.0) if initial else 0.0
    nav_rows: list[dict[str, str]] = []
    if paths["nav"].exists() and paths["nav"].stat().st_size > 0:
        with paths["nav"].open(newline="", encoding="utf-8") as f:
            nav_rows = list(csv.DictReader(f))
    trades = 0
    if paths["ledger"].exists() and paths["ledger"].stat().st_size > 0:
        with paths["ledger"].open(newline="", encoding="utf-8") as f:
            trades = sum(1 for _ in csv.DictReader(f))
    return {
        "ok": True,
        "universe_tag": "UNIVERSE_REDUCED",
        "strategy_status": "NOT_VALIDATED",
        "initial_capital": initial,
        "equity": equity,
        "return_pct": round(ret * 100, 4),
        "peak_equity": float(acc["peak_equity"]),
        "drawdown_from_peak": float(acc.get("drawdown_from_peak") or 0),
        "n_nav_days": len(nav_rows),
        "n_trades": trades,
        "n_positions": len(acc.get("positions") or []),
        "disclaimer": "纸面结果 ≠ 未来收益；S1.1 NOT_VALIDATED；勿宣称稳定盈利。",
    }


def _mtm(paths: dict[str, Path], asof: Optional[str], note: str) -> dict[str, Any]:
    account = load_account(paths["account"])
    marks: dict[str, float] = {}
    errors: list[str] = []
    px_date = asof or ""
    for pos in account.get("positions") or []:
        sym = pos["symbol"]
        try:
            df, _ = load_or_fetch_bars(sym, start_date="20250101")
            dt, px = latest_close(df, asof=asof)
            marks[sym] = px
            px_date = str(dt.date())
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{sym}:{exc}")
    account = mark_to_market(account, marks)
    save_account(account, paths["account"])
    trade_date = asof or px_date
    if trade_date:
        upsert_nav(
            paths["nav"],
            nav_row_from_account(
                account,
                trade_date,
                note=(note or "MTM") + (" | " + ";".join(errors) if errors else ""),
            ),
        )
    return {"account": account, "marks": marks, "errors": errors, "price_date": px_date}


def write_summary(
    report_dir: Path,
    trade_date: str,
    scan: dict[str, Any],
    mtm: dict[str, Any],
    auto_fill: dict[str, Any] | None,
    dry_run: bool,
) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    acc = mtm.get("account") or {}
    gate = scan.get("gate") or {}
    lines = [
        f"# S1 单账本纸面日摘要 {trade_date}",
        "",
        "> **Paper only / 公开行情 / UNIVERSE_REDUCED。不构成投资建议。S1.1 NOT_VALIDATED。**",
        "",
        "## 标签",
        "",
        "- `UNIVERSE_REDUCED`：公开缩减宇宙，**非** SuperMind 全市场扫描",
        f"- dry_run：{dry_run}",
        f"- 生成时间：{datetime.now(CHINA).isoformat(timespec='seconds')}",
        "",
        "## 账户",
        "",
        f"- 现金：{float(acc.get('cash', 0)):.2f} CNY",
        f"- 持仓市值：{float(acc.get('positions_mv') or 0):.2f} CNY",
        f"- 权益：{float(acc.get('equity', 0)):.2f} CNY",
        f"- 峰值权益：{float(acc.get('peak_equity', 0)):.2f} CNY",
        f"- 回撤：{float(acc.get('drawdown_from_peak') or 0):.4f}",
        f"- 持仓数：{len(acc.get('positions') or [])}",
        f"- 暴露：{float(acc.get('exposure_pct') or 0):.4f}",
        "",
        "## 市场开关（中证500）",
        "",
        f"- {'ON' if gate.get('gate_on') else 'OFF'} | {gate.get('reason')}",
        f"- 数据日：{gate.get('date', '—')} close={gate.get('close', '—')} "
        f"MA20={gate.get('ma20', '—')} MA60={gate.get('ma60', '—')}",
        f"- 源：{gate.get('source', '—')}",
        "",
        "## 扫描",
        "",
        f"- 宇宙来源：`{scan.get('universe_source')}`",
        f"- 宇宙规模：{scan.get('universe_size')}",
        f"- 信号日：{scan.get('signal_date', '—')}",
        f"- 候选数：{len(scan.get('candidates') or [])}",
        f"- 消息：{'; '.join(scan.get('messages') or []) or '—'}",
        f"- 错误：{'; '.join(scan.get('errors') or []) or '无'}",
        "",
        "### 延后规则",
        "",
    ]
    for d in scan.get("deferred_rules") or []:
        lines.append(f"- {d}")
    lines.extend(["", "### 候选卡片", ""])
    cands = scan.get("candidates") or []
    if not cands:
        lines.append("_无候选，或门控 OFF / 数据不足。门控 OFF 或无行情时不成交、不伪造收益。_")
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
                "### auto-paper-fill",
                "",
                "```json",
                json.dumps(auto_fill, ensure_ascii=False, indent=2),
                "```",
            ]
        )
    lines.extend(
        [
            "",
            "## 免责声明",
            "",
            "纸面规则演练仅供流程验证；不构成投资建议；纸面成交 ≠ 实盘；"
            "S1.1 状态 NOT_VALIDATED，不得宣称稳定盈利。",
            "",
        ]
    )
    path = report_dir / "summary.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    (report_dir / "scan.json").write_text(
        json.dumps(scan, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    if auto_fill is not None:
        (report_dir / "auto_fill.json").write_text(
            json.dumps(auto_fill, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return path


def run_day(
    *,
    asof: Optional[str] = None,
    dry_run: bool = False,
    auto_paper_fill: bool = False,
    max_universe: int = 30,
    cfg: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """跑一日：市场开关 + 缩减宇宙扫描 + MTM。dry_run 不写账户/ledger/nav。"""
    cfg = cfg or load_paper_config()
    paths = ensure_runtime_dirs(cfg)
    _bind_runtime(paths)
    asof = asof or datetime.now(CHINA).strftime("%Y-%m-%d")

    if not paths["account"].exists():
        init_account(float(cfg.get("capital", DEFAULT_CAPITAL)), cfg=cfg)

    # 扫描（只读行情）
    try:
        scan = scan_candidates(asof=asof, max_names=max_universe)
    except Exception as exc:  # noqa: BLE001
        scan = {
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
    mtm: dict[str, Any]
    if dry_run:
        # 不改账本；用当前账户快照做只读 MTM 预览
        acc = load_account(paths["account"])
        marks: dict[str, float] = {}
        errors: list[str] = []
        for pos in acc.get("positions") or []:
            sym = pos["symbol"]
            try:
                df, _ = load_or_fetch_bars(sym, start_date="20250101")
                _, px = latest_close(df, asof=asof)
                marks[sym] = px
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{sym}:{exc}")
        preview = mark_to_market(acc, marks)
        mtm = {"account": preview, "marks": marks, "errors": errors, "price_date": asof, "dry_run": True}
        note = "dry-run|no-persist"
    else:
        if auto_paper_fill:
            auto_fill = maybe_auto_fill(scan, asof=asof)
        gate_on = bool(scan.get("gate", {}).get("gate_on"))
        note = "UNIVERSE_REDUCED|" + ("gate_on" if gate_on else "gate_off")
        mtm = _mtm(paths, asof, note)

    report_dir = paths["reports"] / asof
    if dry_run:
        report_dir = paths["reports"] / f"{asof}_dryrun"
    summary = write_summary(report_dir, asof, scan, mtm, auto_fill, dry_run=dry_run)

    acc = mtm["account"]
    return {
        "ok": True,
        "dry_run": dry_run,
        "date": asof,
        "universe_tag": "UNIVERSE_REDUCED",
        "strategy_status": "NOT_VALIDATED",
        "gate_on": bool(scan.get("gate", {}).get("gate_on")),
        "gate_reason": (scan.get("gate") or {}).get("reason"),
        "candidates": len(scan.get("candidates") or []),
        "universe_size": scan.get("universe_size"),
        "universe_source": scan.get("universe_source"),
        "cash": float(acc.get("cash", 0)),
        "equity": float(acc.get("equity", 0)),
        "n_positions": len(acc.get("positions") or []),
        "auto_fill": auto_fill,
        "summary": str(summary),
        "scan_messages": scan.get("messages") or [],
        "scan_errors": scan.get("errors") or [],
        "mtm_errors": mtm.get("errors") or [],
    }
