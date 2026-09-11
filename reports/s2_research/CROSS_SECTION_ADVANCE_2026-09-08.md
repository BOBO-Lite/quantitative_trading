# 历史主板横截面与行业归属接入

本轮消除了固定历史样本的全股票池相对强度排名缺口，并接入前月末行业归属。财报事件与可信行业强度仍未补齐，正式绩效实验未开始。

## 数据与平台证据

严格版报告：https://quant.10jqka.com.cn/view/study-index.html#/backtest-result?id=6a9fdf61d8cd0b00b6bd6729

2019-04-17至19盘前，分别按16、17、18日历史股票池取数；23秒完成，无订单函数。135个日志分片重建3个完整包，合计8565行股票状态/收益摘要。首次只读取页面已加载部分时缺39个早期分片，导入器拒绝；加载更多后分片、长度及哈希全部通过，没有绕过缺片检查。

初版报告6a9fddfbb0c63e00b6a5f7be为8秒完成。后续V2加强有效上市行情计数（有限且大于零）及最近61日与基准日历完全一致检查，重跑后以下数量及样本收益/排名不变。两个报告和源码快照均保留。

| 信号日 | 历史主板总数 | 排名纳入 | 低流动性 | 停牌 | ST | 有效上市行情不足120根 |
|---|---:|---:|---:|---:|---:|---:|
| 2019-04-16 | 2855 | 2361 | 350 | 16 | 92 | 36 |
| 2019-04-17 | 2855 | 2358 | 357 | 10 | 94 | 36 |
| 2019-04-18 | 2855 | 2354 | 365 | 8 | 93 | 35 |

每只股票有唯一一行和明确理由，数量能对回历史池；MISSING_HISTORY/INVALID_HISTORY/INVALID_TURNOVER/MISSING_STATE等数据错误不能作为普通策略排除项静默缩小排名分母。没有出现这些数据错误。120根是有效观测下限，不能把这一核验理解为所有历史数据从未缺失的独立证明。

## 排名定义与独立核对

本轮登记研究用rs_percentile：在满足120根有效历史、非ST、非停牌、前20日平均成交额至少5000万元的历史主板集合中，按20日相对中证500收益升序排名，平均秩处理同分，再除以纳入数量。该排名集合不先过滤财报事件，事件作为股票入场门禁独立处理。此处不是冻结S1多项加权总分，也没有依据收益试验选择该定义。

| 信号日 | 平安银行百分位 | 招商银行百分位 |
|---|---:|---:|
| 2019-04-16 | 79.8391% | 75.6459% |
| 2019-04-17 | 78.0322% | 77.0992% |
| 2019-04-18 | 79.6941% | 74.2566% |

两股三个日期共6处ret20与此前独立导出的原始日线特征完全一致，差0。它们是历史研究样本，不能用这些数值建议当前买入。

行业使用本地已导入的2019-03-31历史归属，两股均为T19（银行）；映射日期严格早于信号日。不能取2019-04-30归属或当前归属。已存在的行业收益文件来自当前存续股票，manifest明确formal_backtest_ready=false，本轮没有把它作为可信行业强度输入。

## 已接入的代码与结果

- adapters/supermind_cross_section_probe.py：平台只读完整横截面导出；
- src/audit_historical_cross_section.py：覆盖/排除原因审查、平均秩百分位、收益口径核对、前月末行业连接；
- portfolio_replay/historical_cross_sections.json：三个日期的完整可排名集合与排除统计；
- portfolio_replay/historical_ranked_features.json：补充排名、分母、历史行业归属的真实样本特征；
- portfolio_replay/ranked_gated/：接入排名后的三日组合门禁回放，6行前日信号不再缺排名，仍缺财报事件和行业强度；订单0、禁止绩效解释。

复现：

```powershell
.\.venv\Scripts\python.exe src/audit_historical_cross_section.py --log reports/s2_research/cross_export_6a9fdf61d8cd0b00b6bd6729.txt --features reports/s2_research/portfolio_replay/historical_daily_features.json --mapping runtime/industry_history/monthly_industry.csv.gz --output-dir reports/s2_research/portfolio_replay
.\.venv\Scripts\python.exe src/build_history_sample_bundle.py --features reports/s2_research/portfolio_replay/historical_ranked_features.json --minutes reports/s2_research/portfolio_replay/historical_minute_sample.json --output-dir reports/s2_research/portfolio_replay/ranked_gated
```

## 验证和剩余边界

新增9项测试通过，覆盖缺股票、数据错误排除、错误池日期、同分、ST分母排除、伪造纳入标志、禁止未来行业归属及真实数据连接。全套模块179/179、核心6/6，共185/185，完整性PASS；原冻结S1源码不变，平台编辑器已恢复普通v5并保存。

这里只覆盖三个历史日期的主板股票池及两只股票分钟/技术特征，不是完整股票池分钟回测。下一阶段优先核验当时已知的财报事件日历及不含当前存续偏差的行业强度，再扩展分钟候选覆盖；公司行动与开盘撮合边界仍保留。正式4配置×2成本实验仍0/8，用户实盘账户和条件单未变更。
