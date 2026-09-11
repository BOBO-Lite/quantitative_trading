"""S1 T+1 入场确认（S1_FROZEN_SPEC §3）。

两段式节奏：
  - T 日 15:30 收盘扫描 → 候选卡片（run / dry-run）
  - T+1 日 09:45–10:30 分时确认后再买（本模块 / cli entry）

公开分钟行情不可用时必须明确 deferred，禁止静默用次日开盘伪装冻结入场。
`--approx-next-open` 为显式近似开关，默认关闭。
"""
from __future__ import annotations

import json
from datetime import datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from broker import load_account, mark_to_market, record_fill
from data_feed import fetch_public_minutes, load_or_fetch_bars
from ledger_b import size_u0
from paths import ensure_runtime_dirs, load_paper_config

CHINA = ZoneInfo("Asia/Shanghai")

OPEN_GAP_MIN = -0.015
OPEN_GAP_MAX = 0.03
MAX_ABOVE_SIGNAL_CLOSE = 0.04
ENTRY_START = "09:45"
ENTRY_END = "10:30"
SLIPPAGE_DEFAULT = 0.001


def _to_symbol_code(symbol: str) -> str:
    return str(symbol).split(".")[0].zfill(6)


def previous_trading_day(asof: str, lookback_calendar_days: int = 14) -> Optional[str]:
    """用中证500日线日历找 asof 之前最近一个交易日。"""
    try:
        df, _ = load_or_fetch_bars("000905", start_date="20240101", prefer_offline=True)
    except Exception:  # noqa: BLE001
        return None
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    cutoff = pd.Timestamp(asof)
    prior = d[d["date"] < cutoff].sort_values("date")
    if prior.empty:
        # 兜底：日历回退工作日
        dt = cutoff - timedelta(days=1)
        for _ in range(lookback_calendar_days):
            if dt.weekday() < 5:
                return str(dt.date())
            dt -= timedelta(days=1)
        return None
    return str(prior.iloc[-1]["date"].date())


def load_scan_cards(
    reports_dir: Path,
    *,
    signal_date: Optional[str] = None,
    scan_path: Optional[Path] = None,
    entry_date: Optional[str] = None,
) -> tuple[dict[str, Any], Path]:
    """读取上一交易日收盘扫描留下的候选卡片。"""
    if scan_path is not None:
        path = Path(scan_path)
        if not path.exists():
            raise FileNotFoundError(f"scan 文件不存在: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload, path

    if signal_date:
        path = reports_dir / signal_date / "scan.json"
        if not path.exists():
            raise FileNotFoundError(
                f"未找到信号日扫描: {path}；请先在 T 日运行 python -m paper.cli run"
            )
        return json.loads(path.read_text(encoding="utf-8")), path

    entry_date = entry_date or datetime.now(CHINA).strftime("%Y-%m-%d")
    # 优先用交易日历找前一交易日；再在 reports 里向前扫
    candidates_dates: list[str] = []
    prev = previous_trading_day(entry_date)
    if prev:
        candidates_dates.append(prev)
    dt = pd.Timestamp(entry_date)
    for i in range(1, 12):
        d = str((dt - timedelta(days=i)).date())
        if d not in candidates_dates:
            candidates_dates.append(d)

    last_err: Exception | None = None
    for d in candidates_dates:
        path = reports_dir / d / "scan.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8")), path
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                continue
    raise FileNotFoundError(
        f"在 {reports_dir} 未找到 entry_date={entry_date} 之前的 scan.json"
        + (f"；last_error={last_err}" if last_err else "")
        + "。请先于 T 日 15:30 运行收盘扫描。"
    )


def _session_open_price(minutes: pd.DataFrame) -> float:
    m = minutes.sort_values("datetime")
    # 优先 09:30–09:31 开盘价；否则首根可用分钟开盘
    times = m["datetime"].dt.strftime("%H:%M")
    open_bars = m[times.between("09:30", "09:35")]
    if not open_bars.empty:
        return float(open_bars.iloc[0]["open"])
    return float(m.iloc[0]["open"])


def _ensure_vwap(minutes: pd.DataFrame) -> pd.DataFrame:
    m = minutes.sort_values("datetime").copy()
    if "amount" not in m.columns or m["amount"].isna().all():
        if "turnover" in m.columns and m["turnover"].notna().any():
            m["amount"] = pd.to_numeric(m["turnover"], errors="coerce")
        else:
            # 近似：典型价 * volume（公开源缺成交额时的退化；标注在结果里）
            tp = (m["high"] + m["low"] + m["close"]) / 3.0
            m["amount"] = tp * pd.to_numeric(m["volume"], errors="coerce").fillna(0)
            m["vwap_approx"] = True
    else:
        m["vwap_approx"] = False
    vol = pd.to_numeric(m["volume"], errors="coerce").fillna(0.0)
    amt = pd.to_numeric(m["amount"], errors="coerce").fillna(0.0)
    cum_v = vol.cumsum()
    cum_a = amt.cumsum()
    m["vwap"] = cum_a / cum_v.replace(0, pd.NA)
    # 若源自带 running average（东财 trends），在 cum 无效时回退
    if "average" in m.columns:
        avg = pd.to_numeric(m["average"], errors="coerce")
        m["vwap"] = m["vwap"].fillna(avg)
    return m


def confirm_s1_entry(
    card: dict[str, Any],
    minutes: pd.DataFrame,
    *,
    open_gap_min: float = OPEN_GAP_MIN,
    open_gap_max: float = OPEN_GAP_MAX,
    max_above_signal_close: float = MAX_ABOVE_SIGNAL_CLOSE,
    start_time: str = ENTRY_START,
    end_time: str = ENTRY_END,
    slippage_each_side: float = SLIPPAGE_DEFAULT,
    check_slipped_price_cap: bool = False,
) -> dict[str, Any]:
    """按冻结规格 §3 确认入场。

    成交价用「信号分钟的下一分钟开盘」近似；默认用该开盘价对照 ≤ 信号收盘×1.04
   （与用户纠正一致）。若 check_slipped_price_cap=True，则用含滑点成交价对照（对齐 s1_engine）。
    """
    symbol = _to_symbol_code(card["symbol"])
    signal_close = float(card["close"])
    signal_high = float(card["high"])
    base = {
        "symbol": symbol,
        "signal_date": card.get("signal_date"),
        "mode": "FROZEN_MINUTE",
        "tag": "UNIVERSE_REDUCED",
    }
    if minutes is None or minutes.empty:
        return {**base, "status": "DEFERRED_NO_MINUTE_DATA", "reason": "无公开分钟行情"}

    m = minutes.copy()
    m["datetime"] = pd.to_datetime(m["datetime"])
    m = m.sort_values("datetime").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        if col in m.columns:
            m[col] = pd.to_numeric(m[col], errors="coerce")

    open_px = _session_open_price(m)
    gap = open_px / signal_close - 1.0
    if not (open_gap_min <= gap <= open_gap_max):
        return {
            **base,
            "status": "REJECTED_OPEN_GAP",
            "reason": f"开盘涨跌幅超限 gap={gap:.4f} (需 {open_gap_min:.1%}~{open_gap_max:.1%})",
            "open_price": open_px,
            "open_gap": round(gap, 6),
        }

    m = _ensure_vwap(m)
    start = clock_time.fromisoformat(start_time)
    end = clock_time.fromisoformat(end_time)
    times = m["datetime"].dt.time
    window_idx = m.index[(times >= start) & (times <= end)]
    if len(window_idx) == 0:
        return {
            **base,
            "status": "REJECTED_NO_ENTRY_WINDOW_BARS",
            "reason": f"分钟数据中无 {start_time}-{end_time} 窗口",
            "open_gap": round(gap, 6),
        }

    for idx in window_idx:
        bar = m.loc[idx]
        vwap = bar.get("vwap")
        if pd.isna(vwap) or float(vwap) <= 0:
            continue
        close_px = float(bar["close"])
        if not (close_px > signal_high and close_px > float(vwap)):
            continue
        # 下一分钟开盘成交；禁止同 K 线最优价
        if idx + 1 >= len(m):
            return {
                **base,
                "status": "TRIGGER_WAITING_NEXT_BAR",
                "reason": "已触发但缺少下一分钟开盘（窗口末或行情未到）",
                "confirmed_at": pd.Timestamp(bar["datetime"]).isoformat(),
                "signal_close_px": close_px,
                "vwap": float(vwap),
                "open_gap": round(gap, 6),
            }
        next_bar = m.loc[idx + 1]
        raw_fill = float(next_bar["open"])
        slipped = raw_fill * (1.0 + float(slippage_each_side))
        cap = signal_close * (1.0 + max_above_signal_close)
        price_for_cap = slipped if check_slipped_price_cap else raw_fill
        if price_for_cap > cap + 1e-12:
            return {
                **base,
                "status": "REJECTED_PRICE_CAP",
                "reason": f"成交价 {price_for_cap:.4f} > 信号收盘×1.04={cap:.4f}",
                "raw_fill": raw_fill,
                "slipped_fill": round(slipped, 6),
                "max_price": round(cap, 6),
                "confirmed_at": pd.Timestamp(bar["datetime"]).isoformat(),
                "open_gap": round(gap, 6),
            }
        return {
            **base,
            "status": "CONFIRMED",
            "reason": "S1_FROZEN_SPEC §3 分钟确认通过",
            "open_price": open_px,
            "open_gap": round(gap, 6),
            "confirmed_at": pd.Timestamp(bar["datetime"]).isoformat(),
            "fill_datetime": pd.Timestamp(next_bar["datetime"]).isoformat(),
            "raw_fill": raw_fill,
            "slipped_fill": round(slipped, 6),
            "signal_high": signal_high,
            "signal_close": signal_close,
            "trigger_close": close_px,
            "vwap": float(vwap),
            "vwap_approx": bool(m.get("vwap_approx", pd.Series([False])).iloc[0])
            if "vwap_approx" in m.columns
            else False,
            "max_price": round(cap, 6),
        }

    last_t = pd.Timestamp(m.iloc[-1]["datetime"]).time()
    status = "REJECTED_WINDOW_EXPIRED" if last_t > end else "NO_TRIGGER_IN_WINDOW"
    return {
        **base,
        "status": status,
        "reason": "09:45–10:30 内未出现首次收盘> T日最高且>当日VWAP",
        "open_gap": round(gap, 6),
    }


def approx_next_open_entry(card: dict[str, Any]) -> dict[str, Any]:
    """显式近似：用次日开盘价，不伪装为冻结入场。"""
    symbol = _to_symbol_code(card["symbol"])
    base = {
        "symbol": symbol,
        "signal_date": card.get("signal_date"),
        "mode": "APPROX_NEXT_OPEN",
        "tag": "UNIVERSE_REDUCED",
        "warning": "显式近似，非 S1_FROZEN_SPEC §3 原样；禁止当作冻结入场证据",
    }
    try:
        df, src = load_or_fetch_bars(symbol, start_date="20250101")
    except Exception as exc:  # noqa: BLE001
        return {**base, "status": "SKIPPED", "reason": f"日线拉取失败: {exc}"}
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    sig_dt = pd.Timestamp(card["signal_date"])
    nxt = d[d["date"] > sig_dt].sort_values("date")
    if nxt.empty:
        return {**base, "status": "SKIPPED", "reason": "无次日K线", "source": src}
    row = nxt.iloc[0]
    open_px = float(row["open"])
    signal_close = float(card["close"])
    gap = open_px / signal_close - 1.0
    if not (OPEN_GAP_MIN <= gap <= OPEN_GAP_MAX):
        return {
            **base,
            "status": "REJECTED_OPEN_GAP",
            "reason": f"开盘涨跌幅超限 gap={gap:.4f}",
            "open_gap": round(gap, 6),
            "entry_date": str(pd.Timestamp(row["date"]).date()),
        }
    cap = signal_close * (1.0 + MAX_ABOVE_SIGNAL_CLOSE)
    if open_px > cap:
        return {
            **base,
            "status": "REJECTED_PRICE_CAP",
            "reason": f"次日开盘 {open_px:.4f} > 信号收盘×1.04={cap:.4f}",
            "raw_fill": open_px,
            "max_price": round(cap, 6),
        }
    return {
        **base,
        "status": "CONFIRMED_APPROX",
        "reason": "显式 --approx-next-open：次日开盘近似",
        "raw_fill": open_px,
        "open_gap": round(gap, 6),
        "entry_date": str(pd.Timestamp(row["date"]).date()),
        "fill_datetime": f"{pd.Timestamp(row['date']).date()}T09:30:00",
        "source": src,
        "max_price": round(cap, 6),
        "signal_close": signal_close,
    }


def run_entry(
    *,
    entry_date: Optional[str] = None,
    signal_date: Optional[str] = None,
    scan_path: Optional[str] = None,
    dry_run: bool = False,
    approx_next_open: bool = False,
    persist_fills: bool = True,
    cfg: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """读取候选卡片并尝试 T+1 入场确认。"""
    cfg = cfg or load_paper_config()
    paths = ensure_runtime_dirs(cfg)
    # 绑定 ledger_b 账户路径到 runtime
    import ledger_b as _lb

    _lb.ACCOUNT_B = paths["account"]
    _lb.LEDGER_B = paths["ledger"]
    _lb.NAV_B = paths["nav"]

    entry_date = entry_date or datetime.now(CHINA).strftime("%Y-%m-%d")
    scan, scan_file = load_scan_cards(
        paths["reports"],
        signal_date=signal_date,
        scan_path=Path(scan_path) if scan_path else None,
        entry_date=entry_date,
    )
    cards = list(scan.get("candidates") or [])
    cards = sorted(cards, key=lambda c: float(c.get("score") or 0), reverse=True)

    result: dict[str, Any] = {
        "ok": True,
        "entry_date": entry_date,
        "signal_date": scan.get("signal_date") or signal_date,
        "scan_file": str(scan_file),
        "universe_tag": "UNIVERSE_REDUCED",
        "strategy_status": "NOT_VALIDATED",
        "approx_next_open": bool(approx_next_open),
        "dry_run": bool(dry_run),
        "gate_on": bool((scan.get("gate") or {}).get("gate_on")),
        "n_cards": len(cards),
        "filled": [],
        "deferred": [],
        "rejected": [],
        "skipped": [],
        "messages": [],
    }

    if not paths["account"].exists():
        result["ok"] = False
        result["messages"].append("账户未初始化；请先 python -m paper.cli init")
        return result

    if not cards:
        result["messages"].append("扫描无候选卡片；无需入场")
        _write_entry_report(paths["reports"] / entry_date, result)
        return result

    if not result["gate_on"]:
        # 扫描日门控 OFF 时本不应有候选；若有历史卡片也跳过新买
        result["messages"].append("信号日市场开关 OFF，跳过新买入")
        for c in cards:
            result["skipped"].append({"symbol": c["symbol"], "reason": "gate_off_on_signal_day"})
        _write_entry_report(paths["reports"] / entry_date, result)
        return result

    account = load_account(paths["account"])
    for card in cards:
        sym = _to_symbol_code(card["symbol"])
        if card.get("abandon_if_stop_gt_6pct"):
            result["skipped"].append({"symbol": sym, "reason": "stop_distance>6%"})
            continue

        decision: dict[str, Any]
        minute_meta: dict[str, Any] = {}
        if approx_next_open:
            decision = approx_next_open_entry(card)
        else:
            minutes, minute_meta = fetch_public_minutes(sym, entry_date)
            if minutes is None or minutes.empty:
                detail = minute_meta.get("reason") or "公开分钟行情不可用"
                decision = {
                    "symbol": sym,
                    "signal_date": card.get("signal_date"),
                    "mode": "FROZEN_MINUTE",
                    "status": "DEFERRED_NO_MINUTE_DATA",
                    "reason": f"{detail}；禁止静默用次日开盘伪装冻结入场",
                    "minute_meta": minute_meta,
                    "hint": "可显式传 --approx-next-open 做文档化近似（非冻结规格）",
                }
            else:
                decision = confirm_s1_entry(card, minutes)
                decision["minute_meta"] = minute_meta

        status = decision.get("status") or ""
        if status in {"CONFIRMED", "CONFIRMED_APPROX"}:
            raw_fill = float(decision["raw_fill"])
            stop_dist = float(card.get("stop_distance_est") or 0.05)
            stop_price = raw_fill * (1.0 - stop_dist)
            account = mark_to_market(account)
            plan = size_u0(
                raw_fill,
                stop_price,
                float(account["equity"]),
                float(account["cash"]),
                len(account.get("positions") or []),
                float(account.get("positions_mv") or 0),
            )
            if not plan:
                result["rejected"].append(
                    {**decision, "status": "REJECTED_RISK_SIZING", "reason": "定仓失败/风控 U0"}
                )
                continue
            fill_rec = {
                **decision,
                "quantity": int(plan["quantity"]),
                "stop_price": plan["stop_price"],
                "stop_distance": plan["stop_distance"],
            }
            if dry_run or not persist_fills:
                fill_rec["persisted"] = False
                result["filled"].append(fill_rec)
            else:
                note = (
                    f"S1 entry {decision.get('mode')}; signal={card.get('signal_date')}; "
                    f"entry_date={entry_date}; UNIVERSE_REDUCED; NOT_VALIDATED"
                )
                fill = record_fill(
                    account,
                    symbol=sym,
                    side="buy",
                    qty=int(plan["quantity"]),
                    raw_price=raw_fill,
                    ledger_path=paths["ledger"],
                    account_path=paths["account"],
                    book="S1_paper",
                    note=note,
                )
                account = fill["account"]
                fill_rec["persisted"] = True
                fill_rec["trade_id"] = fill["trade_id"]
                fill_rec["fill_price"] = fill["fill_price"]
                result["filled"].append(fill_rec)
        elif status.startswith("DEFERRED") or status in {
            "TRIGGER_WAITING_NEXT_BAR",
            "NO_TRIGGER_IN_WINDOW",
        }:
            # NO_TRIGGER 在窗口未结束时算 deferred；窗口已过算 rejected
            if status == "NO_TRIGGER_IN_WINDOW":
                # 若入场日已过窗口，记 rejected；否则 deferred
                now = datetime.now(CHINA)
                if entry_date < now.strftime("%Y-%m-%d") or (
                    entry_date == now.strftime("%Y-%m-%d") and now.time() > clock_time(10, 30)
                ):
                    result["rejected"].append(decision)
                else:
                    result["deferred"].append(decision)
            else:
                result["deferred"].append(decision)
        elif status.startswith("REJECTED") or status.endswith("EXPIRED"):
            result["rejected"].append(decision)
        else:
            result["skipped"].append(decision)

    result["messages"].append(
        f"entry done filled={len(result['filled'])} deferred={len(result['deferred'])} "
        f"rejected={len(result['rejected'])} skipped={len(result['skipped'])}"
    )
    report_dir = paths["reports"] / entry_date
    if dry_run:
        report_dir = paths["reports"] / f"{entry_date}_entry_dryrun"
    result["report"] = str(_write_entry_report(report_dir, result))
    return result


def _write_entry_report(report_dir: Path, result: dict[str, Any]) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / "entry.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    lines = [
        f"# S1 早盘入场报告 {result.get('entry_date')}",
        "",
        "> **Paper only / UNIVERSE_REDUCED / NOT_VALIDATED。两段式：T日收盘扫描 → T+1 09:45–10:30 入场。**",
        "",
        f"- signal_date：{result.get('signal_date')}",
        f"- scan_file：`{result.get('scan_file')}`",
        f"- approx_next_open：{result.get('approx_next_open')}",
        f"- dry_run：{result.get('dry_run')}",
        f"- cards：{result.get('n_cards')}",
        f"- filled：{len(result.get('filled') or [])}",
        f"- deferred：{len(result.get('deferred') or [])}",
        f"- rejected：{len(result.get('rejected') or [])}",
        f"- skipped：{len(result.get('skipped') or [])}",
        "",
        "## 说明",
        "",
        "- 默认必须公开分钟行情按 S1_FROZEN_SPEC §3 确认；拿不到分钟数据时 **deferred**，不静默用次日开盘伪装冻结入场。",
        "- `--approx-next-open` 为显式近似（mode=APPROX_NEXT_OPEN），非冻结规格原样。",
        "",
        "```json",
        json.dumps(
            {
                "filled": result.get("filled"),
                "deferred": result.get("deferred"),
                "rejected": result.get("rejected"),
                "skipped": result.get("skipped"),
                "messages": result.get("messages"),
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        "```",
        "",
    ]
    (report_dir / "entry_summary.md").write_text("\n".join(lines), encoding="utf-8")
    return path
