"""生成S2市场环境研究报告；不修改S1候选，也不产生交易指令。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from s2_regime_engine import classify_regime, load_regime_config, state_dict


CHINA_TZ = timezone(timedelta(hours=8))


def _atomic_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def generate_s2_regime_report(
    benchmark_path: Path,
    s1_report_dir: Path,
    config_path: Path,
    industry_manifest_path: Path | None = None,
    industry_returns_path: Path | None = None,
) -> dict[str, Any]:
    cfg = load_regime_config(config_path)
    benchmark = pd.read_csv(benchmark_path)
    state = classify_regime(benchmark, cfg)
    s1_manifest_path = s1_report_dir / "manifest.json"
    s1_manifest = (
        json.loads(s1_manifest_path.read_text(encoding="utf-8"))
        if s1_manifest_path.exists() else {}
    )
    industry_manifest = {}
    if industry_manifest_path and industry_manifest_path.exists():
        industry_manifest = json.loads(
            industry_manifest_path.read_text(encoding="utf-8")
        )
    industry_mapping_ready = bool(
        industry_manifest.get("point_in_time_industry_ready", False)
    )
    industry_returns_ready = bool(
        industry_returns_path and industry_returns_path.exists()
    )
    state_payload = state_dict(state)
    if state.regime == "industry_rotation":
        if not industry_mapping_ready:
            state_payload["route_status"] = "WAITING_FOR_POINT_IN_TIME_INDUSTRY_DATA"
        elif not industry_returns_ready:
            state_payload["route_status"] = "WAITING_FOR_INDUSTRY_RETURN_SERIES"
        else:
            state_payload["route_status"] = "INDUSTRY_DATA_READY_RESEARCH_ONLY"
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
        "strategy_version": cfg["version"],
        "strategy_status": cfg["status"],
        "automatic_trading": False,
        "state": state_payload,
        "s1_observation_count": int(s1_manifest.get("observation_count", 0)),
        "drawdown_control": cfg["drawdown_control"],
        "capital_rule": cfg["capital_rule"],
        "market_neutral": cfg["market_neutral"],
        "industry_data": {
            "mapping_ready": industry_mapping_ready,
            "returns_ready": industry_returns_ready,
            "manifest": str(industry_manifest_path) if industry_manifest_path else None,
            "returns_path": str(industry_returns_path) if industry_returns_path else None,
        },
    }
    json_path = s1_report_dir / "s2_regime.json"
    _atomic_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", json_path)

    strategy = cfg["strategies"][state.regime]
    lines = [
        f"# {state.date} S2市场环境研究路由",
        "",
        f"- 当前环境：{state.label}",
        f"- 路由状态：{state_payload['route_status']}",
        f"- 中证500：{state.benchmark_close:.2f}；MA20 {state.ma20:.2f}；MA60 {state.ma60:.2f}",
        f"- S1个股观察池：{payload['s1_observation_count']}只",
        f"- 研究目标仓位：{state.target_exposure:.0%}；单股上限：{state.max_single_exposure:.0%}；最多{state.max_positions}只",
        f"- 选择器状态：{strategy['selector']}",
        f"- 历史行业映射：{'已就绪' if industry_mapping_ready else '未就绪'}；行业收益序列：{'已就绪' if industry_returns_ready else '未就绪'}",
        "- 性质：S2仅研究；除熊市现金防守外，未通过样本外回测前不启用实盘。",
        "",
        "回撤线：8%预警，12%降风险，15%停止新开仓并退回验证。15%不是跳空或跌停下的保证值。",
    ]
    _atomic_text("\n".join(lines) + "\n", s1_report_dir / "s2_regime_summary.md")
    return payload
