# A股只读数据接口方案 v2.2

## 选型结论

| 层级 | 首选 | 可读取内容 | 限制 |
|---|---|---|---|
| 实时行情 | Tushare Pro | 全A实时日线、最新价、买一卖一、1—60分钟行情 | 需要Token并单独开通实时权限；不读取券商账户 |
| 账户与持仓 | 同花顺SuperMind TradeAPI | 可用资金、总资产、持仓、成本、可卖数量、最新价 | 必须在本机打开SuperMind客户端并登录资金账户 |
| 实时/历史行情首选 | SuperMind研究环境 `get_price` | 日线、分钟线，研究环境内支持实时行情 | 个人体验版不能直接作为本地SDK调用；需下载只读快照 |
| 无Token本地兜底 | 东方财富公开行情 | 最新报价、当日1分钟线、历史日线 | 非官方服务承诺；只作研究/交叉核对，不单独承担实盘止损 |
| 历史回测 | SuperMind＋时点股票池导出 | 日线、分钟、tick、回测与模拟 | 正式报告仍要保存代码、参数和交易明细 |
| 券商备用 | 中信证券QMT/CATS | 行情、交易、账户能力取决于获批权限 | 需要向中信证券申请，不假设普通账户已经开通 |

不把网页抓取、非官方东财/新浪接口或盘中搜索结果作为唯一止损数据源。它们可以交叉核对，但稳定性、延迟和字段口径不足以承担实盘风控。

## 当前环境能做到什么

- 当前ChatGPT网页会话不能直接读取你电脑的本地进程或本地文件；
- ChatGPT桌面版/Codex CLI可以连接本机STDIO MCP服务；
- 本项目提供的 `adapters/ashare_readonly_mcp.py` 只暴露行情、账户快照和持仓读取，不暴露下单、撤单或转账；
- SuperMind账户快照由 `adapters/supermind_snapshot_export.py` 在本机生成；Token只放环境变量，禁止写入策略文件、日志或聊天。

## 本机接入顺序

1. 无Token且没有SuperMind快照时，MCP自动使用东方财富公开只读行情；
2. 在SuperMind研究环境运行 `adapters/supermind_market_export.py`；
3. 下载快照到 `runtime/supermind_market_snapshot.json`；出现快照后自动优先于东方财富；
4. 若以后需要全自动低延迟，再评估Tushare实时权限或获批的SuperMind本地SDK；
5. Tushare Token只保存为本机环境变量 `TUSHARE_TOKEN`；
6. 在SuperMind研究环境运行账户快照导出脚本，输出到仅本机可读目录；
7. 安装Python依赖 `mcp`，启动只读MCP服务；
8. 在ChatGPT桌面版“设置 → MCP servers”添加STDIO服务，或在Codex CLI执行：

```bash
codex mcp add ashare-readonly --env TUSHARE_TOKEN=你的本机环境变量值 -- \
  python /绝对路径/A股波段系统_v2.0/adapters/ashare_readonly_mcp.py
```

实际配置时不要把Token粘贴到聊天中。账户快照默认路径可用环境变量 `ASHARE_ACCOUNT_SNAPSHOT` 指定。

本地无MCP验收命令：

```powershell
.\.venv\Scripts\python.exe adapters\query_ashare.py status
.\.venv\Scripts\python.exe adapters\query_ashare.py quote 000001.SZ 601975.SH 601555.SH
.\.venv\Scripts\python.exe adapters\query_ashare.py minute 000001.SZ --limit 3
.\.venv\Scripts\python.exe adapters\query_ashare.py daily 000001.SZ --limit 3
```

可用 `ASHARE_PROVIDER=eastmoney` 或 `ASHARE_PROVIDER=supermind` 显式选择；默认 `auto`。

## 验收条件

接口只有同时满足下列条件才标记为LIVE：

- 同一股票的最新价和交易时间与同花顺客户端连续三次一致；
- 1分钟K线的开高低收、成交量口径核对通过；
- 账户总资产、可用资金、持仓数量、可卖数量逐字段一致；
- 行情时间戳超过90秒视为陈旧，策略不产生新开仓建议；
- 数据异常或接口断线时只允许管理已有保护单，不允许用上一次报价开新仓。

## 每日增量更新

- 初始121根日线仍由SuperMind全量底库提供，只执行一次；
- 此后由 `src/update_daily_incremental.py` 在交易日15:20以后读取东方财富
  批量收盘快照，只追加一个已完成交易日；
- 东方财富成交量字段单位为“手”，写入SuperMind底库前固定乘100换算为“股”；
- 中证500日线独立读取并与股票日线同时提交，禁止只更新其中一份；
- 同一日期重复运行结果一致时返回 `ALREADY_CURRENT`，内容冲突时拒绝覆盖；
- 有效覆盖率门槛为99.5%，低于门槛时状态为 `FAILED_CLOSED`；
- 每次成功更新在 `runtime/daily_updates/YYYY-MM-DD.json` 保存来源、覆盖率和
  更新前后SHA-256；
- 股票代码池来自最近一次验收元数据，新股代码池仍需周期性刷新，未完成前
  增量结果保持研究用途。
