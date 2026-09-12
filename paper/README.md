# A股 S1 纸交易（默认单账本 50,000 CNY）

**模式：纯纸面 / Paper only。不对接真实券商，不下真实单，不要求券商密钥。**  
**策略状态：S1.1 `NOT_VALIDATED` — 不宣称稳定盈利，不放宽风控。**  
本目录仅供规则演练与流程验证，**不构成投资建议**。

## 默认路径（请用这个）

| 项 | 约定 |
|---|---|
| 账本模式 | **单账本 S1-only** |
| 初始资金 | **50,000 CNY** |
| 行情 | **公开源**（腾讯日 K / akshare 等） |
| 股票池标签 | **`UNIVERSE_REDUCED`**（缩减主板宇宙，**不是**全市场扫描） |
| 持久账本 | `paper/runtime/`（已加入 `.gitignore`，勿提交 CSV/JSON 运行态） |

可选双账本（A=510880 + B=S1，合计 5 万）仅作配置示例，见 `config/dual_50k.example.json` 与 `python -m paper.cli dual`。**默认入口不会跑双账本。**

旧 5 万双账本实验数据已移至 `archive_dual_50k_20260911/`，**不会**并入新 5 万账本。

## 重要：UNIVERSE_REDUCED

无 SuperMind 全量底库时，候选来自公开数据构建的**缩减宇宙**（高流动性主板样本）。  
每一份报告 / 日摘要必须带标签 **`UNIVERSE_REDUCED`**。  
缩减宇宙上的候选 ≠ 完整 S1 实盘信号；**禁止伪装全市场扫描**。

## Linux 运行命令

推荐使用已有 venv（含 pandas / numpy / requests；akshare 可选）：

```bash
cd /workspace/quantitative_trading
PY=/workspace/ashare-etf-quant/.venv/bin/python   # 或本机 python3 + 依赖

# 1) 初始化 5 万单账本（写 paper/runtime/）
$PY -m paper.cli init --capital 50000

# 2) dry-run：扫描 + 预览，不持久化成交
$PY -m paper.cli dry-run
$PY -m paper.cli dry-run --date 2026-09-11

# 3) T 日收盘扫描：市场开关 + 扫描 + MTM（默认只出卡片、不成交）
$PY -m paper.cli run
$PY -m paper.cli run --date 2026-09-10

# 4) T+1 早盘入场确认（读昨日卡片；默认要分钟行情）
$PY -m paper.cli entry --date 2026-09-11 --signal-date 2026-09-10
$PY -m paper.cli entry --dry-run

# 5) 状态 / 绩效
$PY -m paper.cli status
$PY -m paper.cli performance

# 重建空账本（会删除 runtime 账本文件）
$PY -m paper.cli init --capital 50000 --force
```

独立 venv：

```bash
cd /workspace/quantitative_trading
python3 -m venv .venv
.venv/bin/pip install pandas numpy requests pyarrow akshare
.venv/bin/python -m paper.cli init
.venv/bin/python -m paper.cli dry-run
```

### 两段式节奏（重要）

S1 冻结规格是 **T 日收盘评估候选，T+1 的 09:45–10:30 再买**，不是只在 16:30 跑一次。

| 时段 | 命令 | 做什么 |
|---|---|---|
| 交易日 **15:30**（收盘后） | `python -m paper.cli run` | 市场开关 + 缩减宇宙扫描，写出候选卡片；默认**不成交** |
| 次日 **10:00** 左右（窗口内/稍后） | `python -m paper.cli entry` | 读取昨日卡片；公开分钟可得时按 `S1_FROZEN_SPEC` §3 确认入场 |

```bash
# T 日收盘扫描
$PY -m paper.cli run --date 2026-09-10

# T+1 早盘入场（默认要分钟行情；拿不到则 deferred 并写明原因）
$PY -m paper.cli entry --date 2026-09-11 --signal-date 2026-09-10
$PY -m paper.cli entry --date 2026-09-11 --dry-run

# 仅当明确接受近似时（非冻结规格原样）
$PY -m paper.cli entry --date 2026-09-11 --approx-next-open
```

### 定时调用（cron 示例，Asia/Shanghai）

```cron
# 每个交易日 15:30 收盘扫描（出卡片）
30 15 * * 1-5 cd /workspace/quantitative_trading && /workspace/ashare-etf-quant/.venv/bin/python -m paper.cli run >> paper/runtime/cron_scan.log 2>&1

# 每个交易日 10:00 早盘入场确认（读昨日卡片）
0 10 * * 1-5 cd /workspace/quantitative_trading && /workspace/ashare-etf-quant/.venv/bin/python -m paper.cli entry >> paper/runtime/cron_entry.log 2>&1
```

门控 OFF 或无行情时：**不成交、不伪造收益**；分钟不可用时 **deferred**（禁止静默用次日开盘伪装冻结入场）。

## 风控与成本（U0 / 不放宽）

| 约束 | 数值 |
|---|---:|
| 单笔计划风险 | 本金 × **1.25%** |
| 总仓 ≤ | **70%** |
| 单票 ≤ | **35%** |
| 最多持仓 | **3** |
| 整手 | **100** 股 |
| 排除 | ST、300/301/688/689、北交所 |
| 佣金 | 万 2，最低 **5** 元 |
| 卖出印花税 | **0.05%** |
| 过户费 | 双向 0.01‰ |
| 滑点 | 单边 0.1% |
| T+1 | 买入当日不假设可卖 |

市场开关：中证500 收盘 **> MA20** 且 **MA20 > MA60**；不满足则不产生新买入。

## 产出路径

| 路径 | 说明 |
|---|---|
| `paper/runtime/account.json` | 账户快照（gitignore） |
| `paper/runtime/ledger.csv` | 成交流水（gitignore） |
| `paper/runtime/daily_nav.csv` | 日净值（gitignore） |
| `paper/runtime/reports/YYYY-MM-DD/` | 当日摘要与扫描 JSON |
| `paper/data/*.parquet` | 行情缓存（gitignore） |
| `paper/config/default_s1_100k.json` | 默认可提交配置 |

## 入场说明（S1_FROZEN_SPEC §3）

1. 开盘涨跌幅 **-1.5% ~ +3.0%**
2. **09:45–10:30** 内，某分钟收盘价**首次**高于 T 日最高价，且高于**当日 VWAP**
3. 信号在该分钟收盘后成立，成交用**下一分钟开盘**近似；禁止同 K 线最优价
4. 成交价 **≤ 信号收盘 × 1.04**
5. 股数 / 费用 / 风控 **U0 不变**（整手 100）

公开分钟行情的真实局限：东财 trends 多为当日/近几日分时；akshare 1 分钟历史窗口短且易限流。拿不到分钟数据时命令会 **deferred** 并写明原因，**不会**静默用次日开盘伪装冻结入场。`--approx-next-open`（以及旧的 `run --auto-paper-fill`）仅作**显式**文档化近似，默认关闭。

## 可选双账本

```bash
$PY -m paper.cli dual --date 2026-09-11
```

见 `PROTOCOL.md` 历史双账本说明与 `config/dual_50k.example.json`。

## 免责声明

历史数据、纸面成交与回测结果均不等于未来收益。请勿将本平台输出当作实盘下单依据。S1.1 状态为 **NOT_VALIDATED**。
