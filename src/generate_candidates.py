"""从已验收日线生成日期化的 S1 研究候选与全市场失败原因表。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from s1_engine import load_config, prepare_daily_features


ROOT = Path(__file__).resolve().parents[1]
CHINA_TZ = timezone(timedelta(hours=8))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    frame.to_csv(temporary, index=False)
    os.replace(temporary, path)


def _atomic_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _condition_table(rows: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """给目标日每只股票写出每道门槛及失败原因。"""
    u = cfg["universe"]
    s = cfg["signal"]
    symbols = rows["symbol"].astype(str)
    prefixes = tuple(str(value) for value in u.get("excluded_symbol_prefixes", []))
    exchanges = {str(value).upper() for value in u.get("excluded_exchanges", [])}
    account_tradable = ~symbols.str.startswith(prefixes) if prefixes else pd.Series(True, index=rows.index)
    if exchanges:
        account_tradable &= ~symbols.str.rsplit(".", n=1).str[-1].str.upper().isin(exchanges)

    checks: list[tuple[str, str, pd.Series]] = [
        ("account_tradable", "账户权限范围外", account_tradable),
        ("not_paused", "停牌或无成交", ~rows["paused"].astype(bool)),
        ("not_st", "ST股票", ~rows["st"].astype(bool)),
        ("listing_days_ok", "上市不足120日", rows["listing_days"] >= u["min_listing_days"]),
        ("liquidity_ok", "20日均成交额不足", rows["avg_amount20"] >= u["min_avg_turnover_20"]),
        ("market_gate_ok", "中证500市场开关关闭", rows["market_gate"]),
        ("close_above_ma20", "收盘不高于MA20", rows["close"] > rows["ma20"]),
        ("ma20_above_ma60", "MA20不高于MA60", rows["ma20"] > rows["ma60"]),
        ("ma20_rising", "MA20五日未上升", rows["ma20"] > rows["ma20_prev"]),
        ("relative_strength_ok", "20日相对强度未进前35%", rows["excess20_pct"] >= 1 - s["relative_strength_top_fraction"]),
        ("breakout_ok", "收盘未突破此前20日最高收盘", rows["close"] > rows["prior_high_close20"]),
        ("volume_ratio_ok", "量比不在1.3至3.0", rows["volume_ratio"].between(s["volume_ratio_min"], s["volume_ratio_max"], inclusive="both")),
        ("close_location_ok", "收盘位置低于当日振幅65%", rows["close_location"] >= s["close_location_min"]),
        ("compression_ok", "此前10日结构压缩不足", rows["compression10"] <= s["compression_max"]),
    ]
    table = rows.copy()
    for name, _, values in checks:
        table[name] = values.fillna(False).astype(bool)

    def failures(row: pd.Series) -> str:
        return "；".join(label for name, label, _ in checks if not bool(row[name]))

    table["failure_reasons"] = table.apply(failures, axis=1)
    stock_checks = [name for name, _, _ in checks if name != "market_gate_ok"]
    table["passed_stock_setup"] = table[stock_checks].all(axis=1)
    table["passed_all"] = table[[name for name, _, _ in checks]].all(axis=1)
    if not (table["passed_all"] == table["signal"].astype(bool)).all():
        raise ValueError("失败原因表与冻结 S1 signal 计算不一致")
    return table


def generate_research_outputs(
    daily_path: Path,
    benchmark_path: Path,
    config_path: Path,
    signal_date: pd.Timestamp,
    output_dir: Path,
) -> dict[str, Any]:
    """生成候选、全市场原因、中文摘要和可核验清单。"""
    cfg = load_config(config_path)
    daily = pd.read_csv(daily_path)
    benchmark = pd.read_csv(benchmark_path)
    daily["date"] = pd.to_datetime(daily["date"]).dt.normalize()
    benchmark["date"] = pd.to_datetime(benchmark["date"]).dt.normalize()
    date = pd.Timestamp(signal_date).normalize()
    if daily.empty or benchmark.empty:
        raise ValueError("日线或基准为空")
    if date != daily["date"].max() or date != benchmark["date"].max():
        raise ValueError(
            f"候选日必须同时等于日线和基准末日：请求{date.date()}，"
            f"日线{daily['date'].max().date()}，基准{benchmark['date'].max().date()}"
        )

    features = prepare_daily_features(daily, benchmark, cfg)
    rows = features.loc[features["date"] == date].copy()
    if rows.empty:
        raise ValueError(f"目标日 {date.date()} 没有股票数据")
    table = _condition_table(rows, cfg)
    check_names = [
        "account_tradable", "not_paused", "not_st", "listing_days_ok",
        "liquidity_ok", "market_gate_ok", "close_above_ma20",
        "ma20_above_ma60", "ma20_rising", "relative_strength_ok",
        "breakout_ok", "volume_ratio_ok", "close_location_ok", "compression_ok",
    ]
    audit_columns = [
        "date", "symbol", "close", "high", "ma20", "ma60", "atr20",
        "volume_ratio", "excess20_pct", "compression10", "score",
        "structure_low10", "eligible", "market_gate", "signal",
        *check_names, "passed_stock_setup", "passed_all", "failure_reasons",
    ]
    audit = table[audit_columns].sort_values(["signal", "score"], ascending=[False, False])
    candidates = audit.loc[audit["signal"]].copy()
    candidates.insert(0, "research_rank", range(1, len(candidates) + 1))
    candidates["classification"] = "研究候选，须经次日盘前/分钟触发/账户快照复核"
    observation_pool = audit.loc[audit["passed_stock_setup"]].copy()
    observation_pool.insert(0, "observation_rank", range(1, len(observation_pool) + 1))
    observation_pool["classification"] = "个股观察池；未通过市场环境与次日执行门禁，不是买入候选"

    output_dir.mkdir(parents=True, exist_ok=True)
    candidates_path = output_dir / "candidates.csv"
    observation_path = output_dir / "observation_pool.csv"
    audit_path = output_dir / "all_symbols_reasons.csv"
    summary_path = output_dir / "summary.md"
    manifest_path = output_dir / "manifest.json"
    _atomic_csv(candidates, candidates_path)
    _atomic_csv(observation_pool, observation_path)
    _atomic_csv(audit, audit_path)

    gate = bool(rows["market_gate"].iloc[0])
    summary_lines = [
        f"# {date.strftime('%Y-%m-%d')} S1 收盘研究扫描",
        "",
        f"- 中证500市场开关：{'通过' if gate else '关闭'}",
        f"- 扫描股票：{len(audit)} 只",
        f"- 账户权限范围内且通过基础过滤：{int(rows['eligible'].sum())} 只",
        f"- 个股观察池（暂不考虑市场开关）：{len(observation_pool)} 只",
        f"- 冻结S1研究候选：{len(candidates)} 只",
        "- 性质：仅为次日研究名单，不是买入指令；仍需公告、账户快照和09:45—10:30分钟触发复核。",
        "",
    ]
    if candidates.empty:
        summary_lines.append("当日无可执行候选；按规则持有现金，不降低门槛。")
        if not observation_pool.empty:
            summary_lines.extend(["", "## 个股观察池前5（不可直接买入）", ""])
            for _, row in observation_pool.head(5).iterrows():
                summary_lines.append(
                    f"- {row['symbol']}：收盘 {row['close']:.2f}，分数 {row['score']:.2f}。"
                )
    else:
        summary_lines.extend(["## 排名前5", ""])
        for _, row in candidates.head(5).iterrows():
            summary_lines.append(
                f"- {row['symbol']}：收盘 {row['close']:.2f}，分数 {row['score']:.2f}，"
                f"次日价格硬上限 {row['close'] * (1 + cfg['entry']['max_price_above_signal_close']):.2f}。"
            )
    _atomic_text("\n".join(summary_lines) + "\n", summary_path)

    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
        "strategy_version": cfg.get("version"),
        "strategy_status": cfg.get("status"),
        "signal_date": date.strftime("%Y-%m-%d"),
        "read_only_market_data": True,
        "automatic_trading": False,
        "classification": "RESEARCH_CANDIDATES_ONLY",
        "market_gate": gate,
        "scanned_symbols": len(audit),
        "eligible_symbols": int(rows["eligible"].sum()),
        "observation_count": len(observation_pool),
        "candidate_count": len(candidates),
        "displayed_candidate_limit": 5,
        "inputs": {
            "daily": {"path": str(daily_path), "sha256": _sha256(daily_path)},
            "benchmark": {"path": str(benchmark_path), "sha256": _sha256(benchmark_path)},
            "config": {"path": str(config_path), "sha256": _sha256(config_path)},
        },
        "outputs": {
            "candidates": candidates_path.name,
            "observation_pool": observation_path.name,
            "all_symbols_reasons": audit_path.name,
            "summary": summary_path.name,
        },
        "remaining_gates": [
            "次日盘前账户快照复核",
            "公告和财报日历复核",
            "09:45至10:30分钟触发复核",
            "用户在券商客户端最终决定和下单",
        ],
    }
    _atomic_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", manifest_path)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="生成日期化 S1 研究候选和全市场失败原因")
    parser.add_argument("--daily", required=True)
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--config", default=str(ROOT / "config" / "s1_config.json"))
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--output-dir")
    parser.add_argument("--output", help="兼容旧接口：额外复制一份候选CSV")
    args = parser.parse_args()
    date = pd.Timestamp(args.date).normalize()
    output_dir = Path(args.output_dir) if args.output_dir else ROOT / "reports" / "daily" / date.strftime("%Y-%m-%d")
    result = generate_research_outputs(
        Path(args.daily), Path(args.benchmark), Path(args.config), date, output_dir
    )
    if args.output:
        candidates = pd.read_csv(output_dir / "candidates.csv")
        _atomic_csv(candidates, Path(args.output))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
