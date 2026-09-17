# S1 早盘入场报告 2026-09-15

> **Paper only / UNIVERSE_REDUCED / NOT_VALIDATED。两段式：T日收盘扫描 → T+1 09:45–10:30 入场。**

- signal_date：None
- scan_file：`/workspace/quantitative_trading/paper/runtime/reports/2026-09-11/scan.json`
- approx_next_open：False
- dry_run：False
- cards：0
- filled：0
- deferred：0
- rejected：0
- skipped：0

## 说明

- 默认必须公开分钟行情按 S1_FROZEN_SPEC §3 确认；拿不到分钟数据时 **deferred**，不静默用次日开盘伪装冻结入场。
- `--approx-next-open` 为显式近似（mode=APPROX_NEXT_OPEN），非冻结规格原样。

```json
{
  "filled": [],
  "deferred": [],
  "rejected": [],
  "skipped": [],
  "messages": [
    "扫描无候选卡片；无需入场"
  ]
}
```
