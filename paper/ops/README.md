# 纸交易工作记录（可推送）

本目录保存**脱敏后**的模拟盘操作与晚报，供 GitHub 留痕。

- 来源：本地 `paper/runtime/`（该路径 gitignore，不直接入库）
- 不含：行情缓存 parquet、密钥、券商凭证
- 更新：收盘扫描 / 早盘入场 / 晚报任务结束后同步并推送

文件说明：

| 路径 | 内容 |
|---|---|
| `account_snapshot.json` | 最新账户快照（纸面） |
| `daily_nav.csv` | 日净值 |
| `ledger.csv` | 成交流水（尚无成交时仅表头） |
| `reports/YYYY-MM-DD/` | 当日扫描 / 入场摘要 |
| `evening/YYYY-MM-DD.md` | 晚报 |
