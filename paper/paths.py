"""纸面运行路径：默认单账本 S1 → paper/runtime/（持久账本，应 gitignore）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PAPER_DIR = Path(__file__).resolve().parent
ROOT = PAPER_DIR.parent
DEFAULT_CONFIG = PAPER_DIR / "config" / "default_s1_100k.json"
RUNTIME_DIR = PAPER_DIR / "runtime"
S1_CONFIG_PATH = ROOT / "config" / "s1_config.json"

DEFAULT_CAPITAL = 100_000.0


def load_paper_config(path: Path | None = None) -> dict[str, Any]:
    cfg_path = path or DEFAULT_CONFIG
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    return cfg


def _resolve(p: str | Path) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (ROOT / path)


def runtime_paths(cfg: dict[str, Any] | None = None) -> dict[str, Path]:
    cfg = cfg or load_paper_config()
    runtime = _resolve(cfg.get("runtime_dir", "paper/runtime"))
    return {
        "runtime": runtime,
        "account": _resolve(cfg.get("account_file", "paper/runtime/account.json")),
        "ledger": _resolve(cfg.get("ledger_file", "paper/runtime/ledger.csv")),
        "nav": _resolve(cfg.get("nav_file", "paper/runtime/daily_nav.csv")),
        "reports": _resolve(cfg.get("reports_dir", "paper/runtime/reports")),
        "data": PAPER_DIR / "data",
    }


def ensure_runtime_dirs(cfg: dict[str, Any] | None = None) -> dict[str, Path]:
    paths = runtime_paths(cfg)
    paths["runtime"].mkdir(parents=True, exist_ok=True)
    paths["reports"].mkdir(parents=True, exist_ok=True)
    paths["data"].mkdir(parents=True, exist_ok=True)
    return paths
