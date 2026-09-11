"""输出 SuperMind 全量底库的只读覆盖状态。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from prepare_supermind_scan_data import inspect_daily_bundle_coverage


def main() -> None:
    parser = argparse.ArgumentParser(description="检查 SuperMind 全量底库完整性")
    parser.add_argument("--runtime", default="runtime")
    parser.add_argument("--output", default="runtime/supermind_base_status.json")
    args = parser.parse_args()

    status = inspect_daily_bundle_coverage(Path(args.runtime))
    rendered = json.dumps(status, ensure_ascii=False, indent=2)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
