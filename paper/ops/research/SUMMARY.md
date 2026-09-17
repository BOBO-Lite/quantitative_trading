# S1.1 研究级公开行情近似回测 SUMMARY

> ## **NOT_VALIDATED** · **APPROX_NEXT_OPEN** · **UNIVERSE_REDUCED** · **非冻结分钟入场**
>
> 本报告**不是**冻结 S1.1 分钟确认回测验收。公开分钟历史不可靠，默认「信号日收盘候选 → 次日开盘成交」，
> 并检查开盘相对信号收盘约 -1.5%~+3% 与成交价 ≤104%×signal_close。**禁止**将其解读为已完成 09:45–10:30 分时确认。

- 生成时间（Asia/Seoul）: 2026-09-17 07:55:55 KST
- 本金: 100,000 CNY
- 入场模式: `APPROX_NEXT_OPEN`
- 数据源: 腾讯日K前复权（`paper/data_feed.py`），缓存 `paper/data/research_*.parquet`（不提交）
- 宇宙: 75/75 只主板缩减池；tag=`UNIVERSE_REDUCED`
- 净值区间: 2019-01-02 → 2026-09-16（暖机日线自约 2018-01 拉取；A/B 均为连续日净值）
- 基准: 中证500 (000905) 市场开关 close>MA20 且 MA20>MA60

## 与冻结 S1.1 差异清单
- 入场：冻结为 09:45–10:30 分钟确认后下一分钟开盘；本回测为 APPROX_NEXT_OPEN（次日开盘+缺口检查），**未做分时确认**
- 宇宙：公开数据缩减高流动性主板池，非全市场扫描（UNIVERSE_REDUCED）
- listing_days：样本起点前已上市标的用「样本内交易日+120」近似，可能低估真实上市天数过滤误差
- ST/停牌：无完整历史状态字段；paused≈成交量/额为0；ST 仅在选池时按现货名称排除（历史 ST 变迁未还原）
- 成交额：腾讯 volume 按「手」×close×100 近似，流动性过滤为近似
- 一字涨停：用 close≥prev_close×1.095 近似排除，非交易所涨停标记
- 本金：研究用 100,000 CNY（config 历史参考权益不同）
- 行业约束（B）：无申万行业历史，跳过
- 状态：NOT_VALIDATED — 不得当作实盘/纸面验收通过证据

## A / B 关键指标

| 版本 | 期末权益 | 总收益 | CAGR | MaxDD | 交易笔数 |
|---|---:|---:|---:|---:|---:|
| A U0 | 131,562.73 | 31.5627% | 3.6247% | -3.0164% | 20 |
| B 决策官硬闸门 | 124,908.05 | 24.9081% | 2.9289% | -2.424% | 20 |

### A 版细节（策略层 U0）
```json
{
  "label": "A_U0",
  "entry_mode": "APPROX_NEXT_OPEN",
  "status": "NOT_VALIDATED",
  "universe_tag": "UNIVERSE_REDUCED",
  "initial_capital": 100000.0,
  "final_equity": 131562.73,
  "total_return": 0.315627,
  "total_return_pct": 31.5627,
  "CAGR": 0.036247,
  "CAGR_pct": 3.6247,
  "MaxDD": -0.030164,
  "MaxDD_pct": -3.0164,
  "n_trades": 20,
  "win_rate": 0.75,
  "avg_net_pnl": 1578.14,
  "start_date": "2019-01-02",
  "end_date": "2026-09-16",
  "n_nav_days": 1871,
  "yearly_returns": {
    "2019": 0.0,
    "2020": 0.037978,
    "2021": 0.052779,
    "2022": 0.016433,
    "2023": 0.03267,
    "2024": 0.0,
    "2025": 0.082128,
    "2026": 0.059958
  },
  "first_nav_equity": 100000.0
}
```

### B 版细节（叠决策官硬闸门）
```json
{
  "label": "B_DECISION_GATES",
  "entry_mode": "APPROX_NEXT_OPEN",
  "status": "NOT_VALIDATED",
  "universe_tag": "UNIVERSE_REDUCED",
  "initial_capital": 100000.0,
  "final_equity": 124908.05,
  "total_return": 0.249081,
  "total_return_pct": 24.9081,
  "CAGR": 0.029289,
  "CAGR_pct": 2.9289,
  "MaxDD": -0.02424,
  "MaxDD_pct": -2.424,
  "n_trades": 20,
  "win_rate": 0.75,
  "avg_net_pnl": 1245.4,
  "start_date": "2019-01-02",
  "end_date": "2026-09-16",
  "n_nav_days": 1871,
  "yearly_returns": {
    "2019": 0.0,
    "2020": 0.037978,
    "2021": 0.041983,
    "2022": 0.013101,
    "2023": 0.026463,
    "2024": 0.0,
    "2025": 0.060288,
    "2026": 0.047423
  },
  "first_nav_equity": 100000.0
}
```

- B 闸门：单票市值≤20%；单笔风险≤预算1%（1000元/@10万）；总仓≤70%；**申万一级行业≤35%：无公开申万行业历史映射，本回测无法执行该条并已跳过（INDUSTRY_GATE_SKIPPED）。**

## 日线退出简化点
- 止损：开盘跌破则开盘价滑点卖出；日内低点触及则按止损价滑点卖出（无分钟路径）
- +1R 保本 / +2R 跟踪：按收盘判定，下一交易日生效
- 8日时间退出 / 20日强制：收盘触发，次日开盘卖出
- T+1：买入当日不可卖
- 成本：佣金万2最低5、卖出印花税0.05%、过户双边0.001%、滑点单边0.1%

## 失败 / 缺口
- （无致命失败）

## 输出文件
- `SUMMARY.md`（本文件）
- `metrics_A.json` / `metrics_B.json`
- `nav_A.csv` / `nav_B.csv`
- `trades_A.csv` / `trades_B.csv`
- `run_meta.json`

