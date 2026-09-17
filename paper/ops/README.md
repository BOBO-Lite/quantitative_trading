# 纸交易工作记录（可推送）

本目录是仓库里**对外可见**的模拟盘操作留痕，与本机 `paper/runtime/` 分离。

## 作用

- 同步账户快照、净值、成交流水
- 归档每日收盘扫描 / 早盘入场摘要
- 归档工作日晚报
- 供 GitHub 查阅进度；**不含**行情 parquet、密钥、券商凭证

## 目录

| 路径 | 作用 |
|---|---|
| `account_snapshot.json` | 最新纸面账户快照 |
| `daily_nav.csv` | 日净值序列 |
| `ledger.csv` | 成交流水（无成交时可能只有表头） |
| `reports/YYYY-MM-DD/` | 当日 `summary` / `scan` / `entry` 等摘要 |
| `evening/YYYY-MM-DD.md` | 晚报归档 |
| `manifest.json` | 最近一次 `ops_sync` 元数据 |
| `README.md` | 本说明 |

## 如何更新

```bash
cd /workspace/quantitative_trading
.venv/bin/python paper/ops_sync.py
# 然后 commit & push paper/ops（定时任务会自动做）
```

来源始终是本地 `paper/runtime/`；该路径保持 gitignore。
