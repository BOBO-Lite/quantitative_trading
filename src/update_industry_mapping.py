"""下载新浪当前行业分类及成分股，保存为只读研究映射。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
CHINA_TZ = timezone(timedelta(hours=8))
INDUSTRY_LIST_URL = "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"
CONSTITUENTS_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "Market_Center.getHQNodeData"
)


def _request_bytes(url: str, attempts: int = 3) -> bytes:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://finance.sina.com.cn/",
                },
            )
            with urlopen(request, timeout=20) as response:
                return response.read()
        except Exception as exc:
            last_error = exc
            time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"新浪行业请求失败：{last_error}") from last_error


def _symbol(provider_symbol: str) -> str | None:
    value = str(provider_symbol).lower()
    if value.startswith("sh") and len(value) >= 8:
        return f"{value[2:8]}.SH"
    if value.startswith("sz") and len(value) >= 8:
        return f"{value[2:8]}.SZ"
    if value.startswith("bj") and len(value) >= 8:
        return f"{value[2:8]}.BJ"
    return None


def industry_nodes() -> list[tuple[str, str]]:
    text = _request_bytes(INDUSTRY_LIST_URL).decode("gb18030")
    body = text.split("=", 1)[1].strip().rstrip(";\r\n ")
    payload = json.loads(body)
    nodes = []
    for code, raw in payload.items():
        parts = str(raw).split(",")
        name = parts[1].strip() if len(parts) > 1 else str(code)
        nodes.append((str(code), name))
    return sorted(nodes)


def fetch_mapping(delay_seconds: float = 0.12) -> tuple[pd.DataFrame, list[dict]]:
    rows: list[dict] = []
    failures: list[dict] = []
    for index, (industry_code, industry_name) in enumerate(industry_nodes(), 1):
        params = {
            "page": 1,
            "num": 5000,
            "sort": "symbol",
            "asc": 1,
            "node": industry_code,
            "symbol": "",
            "_s_r_a": "page",
        }
        try:
            raw = _request_bytes(f"{CONSTITUENTS_URL}?{urlencode(params)}")
            members = json.loads(raw.decode("gb18030"))
            for item in members or []:
                symbol = _symbol(item.get("symbol"))
                if symbol:
                    rows.append({
                        "symbol": symbol,
                        "industry_code": industry_code,
                        "industry_name": industry_name,
                        "source": "sina_current_industry",
                    })
        except Exception as exc:
            failures.append({"industry_code": industry_code, "error": str(exc)})
        if index % 20 == 0:
            print(f"industry progress: {index}", flush=True)
        time.sleep(delay_seconds)
    frame = pd.DataFrame(rows).drop_duplicates("symbol", keep="first")
    return frame.sort_values("symbol").reset_index(drop=True), failures


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


def _atomic_json(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser(description="更新当前行业映射")
    parser.add_argument("--output-dir", default=str(ROOT / "runtime" / "industry"))
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    frame, failures = fetch_mapping()
    as_of = datetime.now(CHINA_TZ).date().isoformat()
    frame.insert(0, "as_of", as_of)
    path = output_dir / "current_industry.csv"
    _atomic_csv(frame, path)

    universe_path = ROOT / "runtime" / "s1_daily.csv"
    latest_symbols: set[str] = set()
    if universe_path.exists():
        daily = pd.read_csv(universe_path, usecols=["date", "symbol"])
        latest = daily["date"].astype(str).max()
        latest_symbols = set(daily.loc[daily["date"].astype(str) == latest, "symbol"])
    mapped = set(frame["symbol"])
    coverage = len(latest_symbols & mapped) / len(latest_symbols) if latest_symbols else None
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
        "as_of": as_of,
        "source": "sina_current_industry",
        "classification_is_point_in_time": False,
        "mapped_symbols": len(frame),
        "latest_tradable_symbols": len(latest_symbols),
        "latest_tradable_mapped": len(latest_symbols & mapped),
        "latest_tradable_coverage": coverage,
        "failed_industries": failures,
        "csv": str(path),
        "sha256": _sha256(path),
        "limitations": [
            "当前行业分类不能倒推历史行业归属",
            "正式行业轮动回测仍需逐日时点行业映射或可追溯行业指数",
        ],
    }
    _atomic_json(manifest, output_dir / "manifest.json")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
