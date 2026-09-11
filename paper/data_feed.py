"""公开行情拉取与本地缓存。腾讯优先作日线备用；akshare 作现货/指数补充。"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

PAPER_DIR = Path(__file__).resolve().parent
DATA_DIR = PAPER_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

ASHARE_ETF_DATA = Path("/workspace/ashare-etf-quant/data")


def _tencent_market(symbol: str) -> str:
    code = symbol.split(".")[0]
    if code.startswith(("5", "6", "9")) or symbol.upper().endswith(".SH"):
        return "sh"
    return "sz"


def fetch_kline_tencent(
    symbol: str,
    start_date: str = "20240101",
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """腾讯财经前复权日 K（按年分段）。symbol 可为 510880 / 000905 / 600519.SH。"""
    code = symbol.split(".")[0]
    end_date = end_date or datetime.now().strftime("%Y%m%d")
    market = _tencent_market(symbol if "." in symbol else code)
    # 指数 000905 用 sh
    if code in {"000905", "000300", "000016", "399001", "399006"}:
        market = "sh" if code.startswith("000") else "sz"
    start_y = int(start_date[:4])
    end_y = int(end_date[:4])
    rows: list = []
    for y in range(start_y, end_y + 1):
        param = f"{market}{code},day,{y}-01-01,{y}-12-31,800,qfq"
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={param}"
        r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        node = ((r.json().get("data") or {}).get(f"{market}{code}")) or {}
        days = node.get("qfqday") or node.get("day") or []
        rows.extend(days)
        time.sleep(0.15)
    by_date = {p[0]: p for p in rows}
    ordered = [by_date[k] for k in sorted(by_date)]
    if not ordered:
        raise ValueError(f"腾讯源无数据: {symbol}")
    df = pd.DataFrame(ordered, columns=["date", "open", "close", "high", "low", "volume"])
    df["date"] = pd.to_datetime(df["date"])
    start_ts = pd.to_datetime(start_date)
    end_ts = pd.to_datetime(end_date)
    df = df[(df["date"] >= start_ts) & (df["date"] <= end_ts)].copy()
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    df["symbol"] = code
    # 成交额近似：均价 * 量（手→股不确定；腾讯 volume 对股票多为手）。用 close*volume 作相对流动性排序即可。
    df["amount"] = df["close"] * df["volume"] * 100.0
    return df


def load_or_fetch_bars(
    symbol: str,
    *,
    start_date: str = "20240101",
    end_date: Optional[str] = None,
    cache_name: Optional[str] = None,
    prefer_offline: bool = False,
) -> tuple[pd.DataFrame, str]:
    """返回 (df, source_note)。优先本地 parquet，再腾讯，再 ashare-etf 缓存。"""
    code = symbol.split(".")[0]
    cache_name = cache_name or f"{code}.parquet"
    cache_path = DATA_DIR / cache_name
    end_date = end_date or datetime.now().strftime("%Y%m%d")

    def _ok(df: pd.DataFrame) -> bool:
        return df is not None and not df.empty and "close" in df.columns

    if cache_path.exists():
        df = pd.read_parquet(cache_path)
        df["date"] = pd.to_datetime(df["date"])
        if prefer_offline or _ok(df):
            # 若缓存末日过旧且非 prefer_offline，尝试刷新
            last = df["date"].max()
            if prefer_offline or (pd.Timestamp(end_date) - last).days <= 3:
                return df.sort_values("date").reset_index(drop=True), f"cache:{cache_path.name}"

    offline = ASHARE_ETF_DATA / f"{code}.parquet"
    if offline.exists():
        df = pd.read_parquet(offline)
        df["date"] = pd.to_datetime(df["date"])
        if "amount" not in df.columns:
            df["amount"] = df["close"] * df["volume"] * 100.0
        if prefer_offline:
            df.to_parquet(cache_path, index=False)
            return df.sort_values("date").reset_index(drop=True), f"offline:{offline}"

    try:
        df = fetch_kline_tencent(code, start_date=start_date, end_date=end_date)
        df.to_parquet(cache_path, index=False)
        return df, "tencent"
    except Exception as exc:  # noqa: BLE001
        if offline.exists():
            df = pd.read_parquet(offline)
            df["date"] = pd.to_datetime(df["date"])
            if "amount" not in df.columns:
                df["amount"] = df["close"] * df["volume"] * 100.0
            df.to_parquet(cache_path, index=False)
            return df.sort_values("date").reset_index(drop=True), f"offline_fallback:{exc}"
        if cache_path.exists():
            df = pd.read_parquet(cache_path)
            df["date"] = pd.to_datetime(df["date"])
            return df.sort_values("date").reset_index(drop=True), f"stale_cache:{exc}"
        raise


def latest_close(df: pd.DataFrame, asof: Optional[str] = None) -> tuple[pd.Timestamp, float]:
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    if asof:
        d = d[d["date"] <= pd.Timestamp(asof)]
    if d.empty:
        raise ValueError("无可用收盘价")
    row = d.iloc[-1]
    return pd.Timestamp(row["date"]), float(row["close"])


def market_gate_csi500(asof: Optional[str] = None) -> dict:
    """中证500：close>MA20 且 MA20>MA60。"""
    errors: list[str] = []
    try:
        df, src = load_or_fetch_bars("000905", start_date="20240101", end_date=None)
        d = df.copy()
        d["date"] = pd.to_datetime(d["date"])
        if asof:
            d = d[d["date"] <= pd.Timestamp(asof)]
        d = d.sort_values("date")
        if len(d) < 60:
            return {
                "ok": False,
                "gate_on": False,
                "reason": f"指数历史不足60根 (n={len(d)})",
                "source": src,
                "asof": str(asof or ""),
            }
        d["ma20"] = d["close"].rolling(20, min_periods=20).mean()
        d["ma60"] = d["close"].rolling(60, min_periods=60).mean()
        last = d.iloc[-1]
        gate = bool(last["close"] > last["ma20"] and last["ma20"] > last["ma60"])
        return {
            "ok": True,
            "gate_on": gate,
            "date": str(pd.Timestamp(last["date"]).date()),
            "close": float(last["close"]),
            "ma20": float(last["ma20"]),
            "ma60": float(last["ma60"]),
            "source": src,
            "reason": "ON" if gate else "OFF: 未满足 close>MA20 且 MA20>MA60",
        }
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
        return {
            "ok": False,
            "gate_on": False,
            "reason": f"市场开关数据失败: {exc}",
            "errors": errors,
            "asof": str(asof or ""),
        }


def build_reduced_universe(max_names: int = 40) -> tuple[list[dict], str]:
    """构建缩减主板宇宙。优先 akshare 现货成交额；失败则用静态高流动性主板列表。"""
    tag = "UNIVERSE_REDUCED"
    cache = DATA_DIR / "reduced_universe.json"
    static = [
        "600519", "601318", "600036", "601166", "600900", "601288", "601398",
        "600028", "601088", "600030", "601628", "600276", "601012", "600887",
        "601668", "600031", "601857", "600050", "601225", "600309",
        "000001", "000002", "000063", "000333", "000651", "000858", "002415",
        "002594", "002714", "000725", "002304", "000538", "002142", "000776",
        "002027", "000166", "002236", "000568", "002352", "000338",
    ]

    def _filter_code(code: str) -> bool:
        code = str(code).zfill(6)
        if code.startswith(("300", "301", "688", "689")):
            return False
        if code.startswith(("4", "8")):  # BJ-ish
            return False
        return code.startswith(("600", "601", "603", "605", "000", "001", "002", "003"))

    try:
        import akshare as ak

        spot = ak.stock_zh_a_spot_em()
        # 列名兼容
        code_col = "代码" if "代码" in spot.columns else "code"
        name_col = "名称" if "名称" in spot.columns else "name"
        amt_col = "成交额" if "成交额" in spot.columns else None
        rows = []
        for _, r in spot.iterrows():
            code = str(r[code_col]).zfill(6)
            name = str(r.get(name_col, ""))
            if not _filter_code(code):
                continue
            if "ST" in name.upper() or "st" in name:
                continue
            amt = float(r[amt_col]) if amt_col and pd.notna(r[amt_col]) else 0.0
            rows.append({"symbol": code, "name": name, "amount": amt})
        rows.sort(key=lambda x: x["amount"], reverse=True)
        rows = rows[:max_names]
        if rows:
            payload = {
                "tag": tag,
                "built_at": datetime.now().isoformat(timespec="seconds"),
                "source": "akshare.stock_zh_a_spot_em",
                "symbols": rows,
            }
            cache.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return rows, f"{tag}|akshare_spot"
    except Exception as exc:  # noqa: BLE001
        err = str(exc)
        if cache.exists():
            payload = json.loads(cache.read_text(encoding="utf-8"))
            return payload.get("symbols") or [], f"{tag}|cache_after_error:{err}"
        rows = [{"symbol": c, "name": "", "amount": None} for c in static if _filter_code(c)][:max_names]
        payload = {
            "tag": tag,
            "built_at": datetime.now().isoformat(timespec="seconds"),
            "source": f"static_fallback:{err}",
            "symbols": rows,
        }
        cache.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return rows, f"{tag}|static_fallback:{err}"

    rows = [{"symbol": c, "name": "", "amount": None} for c in static][:max_names]
    return rows, f"{tag}|static"


def fetch_universe_bars(symbols: list[str], start_date: str = "20250101") -> tuple[pd.DataFrame, list[str]]:
    """批量拉取缩减宇宙日线；失败的代码记入 errors。"""
    frames: list[pd.DataFrame] = []
    errors: list[str] = []
    for sym in symbols:
        code = sym.split(".")[0] if isinstance(sym, str) else str(sym)
        try:
            df, src = load_or_fetch_bars(code, start_date=start_date)
            df = df.copy()
            df["symbol"] = code
            df["source"] = src
            frames.append(df)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{code}:{exc}")
        time.sleep(0.12)
    if not frames:
        return pd.DataFrame(), errors
    out = pd.concat(frames, ignore_index=True)
    path = DATA_DIR / "universe_bars.parquet"
    out.to_parquet(path, index=False)
    return out, errors


def _symbol_to_ts_code(symbol: str) -> str:
    code = str(symbol).split(".")[0].zfill(6)
    if "." in str(symbol):
        return str(symbol).upper()
    if code.startswith(("5", "6", "9")):
        return f"{code}.SH"
    return f"{code}.SZ"


def fetch_public_minutes(
    symbol: str,
    trade_date: str,
    *,
    prefer_offline: bool = False,
) -> tuple[Optional[pd.DataFrame], dict]:
    """尝试获取公开 1 分钟行情。

    返回 (df|None, meta)。df 列至少含 datetime/open/high/low/close/volume，尽量含 amount。
    公开源局限（请在报告中写明）：
      - 东财 trends2 多为「当日/近几日」分时，历史 T+1 回放常不可得；
      - akshare 1 分钟历史窗口短且易被限流/断连；
      - 无稳定免费全历史分钟源时，必须 deferred，不得静默用日线开盘伪装冻结入场。
    """
    code = str(symbol).split(".")[0].zfill(6)
    ts_code = _symbol_to_ts_code(symbol)
    trade_date = str(pd.Timestamp(trade_date).date())
    meta: dict = {
        "symbol": code,
        "trade_date": trade_date,
        "attempts": [],
    }
    cache_path = DATA_DIR / "minutes" / f"{code}_{trade_date.replace('-', '')}.parquet"
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    def _normalize(df: pd.DataFrame, source: str) -> pd.DataFrame:
        out = df.copy()
        # 列名兼容
        rename = {}
        for a, b in [
            ("时间", "datetime"),
            ("day", "datetime"),
            ("date", "datetime"),
            ("开盘", "open"),
            ("收盘", "close"),
            ("最高", "high"),
            ("最低", "low"),
            ("成交量", "volume"),
            ("成交额", "amount"),
            ("turnover", "amount"),
            ("average", "average"),
        ]:
            if a in out.columns and b not in out.columns:
                rename[a] = b
        if rename:
            out = out.rename(columns=rename)
        if "datetime" not in out.columns:
            raise ValueError(f"分钟数据缺 datetime: cols={list(out.columns)}")
        out["datetime"] = pd.to_datetime(out["datetime"])
        out = out[out["datetime"].dt.strftime("%Y-%m-%d") == trade_date].copy()
        for c in ("open", "high", "low", "close", "volume"):
            if c in out.columns:
                out[c] = pd.to_numeric(out[c], errors="coerce")
        if "amount" in out.columns:
            out["amount"] = pd.to_numeric(out["amount"], errors="coerce")
        elif "turnover" in out.columns:
            out["amount"] = pd.to_numeric(out["turnover"], errors="coerce")
        out = out.dropna(subset=["datetime", "open", "close"]).sort_values("datetime")
        out["symbol"] = code
        out["source"] = source
        return out.reset_index(drop=True)

    if cache_path.exists():
        try:
            df = pd.read_parquet(cache_path)
            df = _normalize(df, f"cache:{cache_path.name}")
            if not df.empty:
                meta["source"] = f"cache:{cache_path.name}"
                meta["n_bars"] = len(df)
                return df, meta
            meta["attempts"].append("cache_empty_for_date")
        except Exception as exc:  # noqa: BLE001
            meta["attempts"].append(f"cache_error:{exc}")

    if prefer_offline:
        meta["reason"] = "prefer_offline 且无可用本地分钟缓存"
        return None, meta

    # 1) 东财 trends2（多为当日分时；ndays 有限）
    try:
        import sys

        adapters = str(PAPER_DIR.parent / "adapters")
        if adapters not in sys.path:
            sys.path.insert(0, adapters)
        from eastmoney_readonly import realtime_minutes  # type: ignore

        rows = realtime_minutes([ts_code])
        if rows:
            df = _normalize(pd.DataFrame(rows), "eastmoney_trends2")
            if not df.empty:
                df.to_parquet(cache_path, index=False)
                meta["source"] = "eastmoney_trends2"
                meta["n_bars"] = len(df)
                meta["attempts"].append("eastmoney_ok")
                return df, meta
            meta["attempts"].append("eastmoney_no_bars_for_date")
        else:
            meta["attempts"].append("eastmoney_empty")
    except Exception as exc:  # noqa: BLE001
        meta["attempts"].append(f"eastmoney:{exc}")

    # 2) akshare 分钟（窗口短 / 易断连）
    try:
        import akshare as ak

        start = f"{trade_date} 09:30:00"
        end = f"{trade_date} 15:00:00"
        raw = ak.stock_zh_a_hist_min_em(
            symbol=code,
            start_date=start,
            end_date=end,
            period="1",
            adjust="",
        )
        if raw is not None and not raw.empty:
            df = _normalize(raw, "akshare.stock_zh_a_hist_min_em")
            if not df.empty:
                df.to_parquet(cache_path, index=False)
                meta["source"] = "akshare.stock_zh_a_hist_min_em"
                meta["n_bars"] = len(df)
                meta["attempts"].append("akshare_hist_min_ok")
                return df, meta
            meta["attempts"].append("akshare_hist_min_empty_for_date")
        else:
            meta["attempts"].append("akshare_hist_min_empty")
    except Exception as exc:  # noqa: BLE001
        meta["attempts"].append(f"akshare_hist_min:{exc}")

    try:
        import akshare as ak

        # 仅当日分时；若 trade_date 不是今天则通常无效
        today = datetime.now().strftime("%Y-%m-%d")
        if trade_date == today:
            raw = ak.stock_intraday_em(symbol=code)
            if raw is not None and not raw.empty:
                df = _normalize(raw, "akshare.stock_intraday_em")
                if not df.empty:
                    df.to_parquet(cache_path, index=False)
                    meta["source"] = "akshare.stock_intraday_em"
                    meta["n_bars"] = len(df)
                    meta["attempts"].append("akshare_intraday_ok")
                    return df, meta
            meta["attempts"].append("akshare_intraday_empty")
        else:
            meta["attempts"].append("akshare_intraday_skipped_not_today")
    except Exception as exc:  # noqa: BLE001
        meta["attempts"].append(f"akshare_intraday:{exc}")

    meta["reason"] = (
        "公开分钟行情不可用（东财/akshare 失败或无目标日数据）；"
        "禁止静默用次日开盘伪装冻结入场。可 --approx-next-open 显式近似。"
    )
    return None, meta
