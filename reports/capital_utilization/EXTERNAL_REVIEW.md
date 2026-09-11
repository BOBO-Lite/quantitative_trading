# 公开方法与实际问题对照

2026-09-10联网读取官方文档、开源代码和GitHub问题记录。这里只证明问题与分析方法有公开依据，不声称别人使用同样参数已经获得高收益。

1. Quantopian Pyfolio 的 create_position_tear_sheet 明确分析 exposures、gross leverage、holdings；还有交易与容量分析。这支持先测账户资金暴露、持仓与交易构成，而非只看总收益。源码：https://github.com/quantopian/pyfolio/blob/master/pyfolio/tears.py 。本地原文external_0.txt。
2. Alphalens 明确把因子收益、信息系数、换手率和分组分析分开。这支持分别验证选股信号质量和组合执行效果，不能把信号后涨幅直接当账户收益。README：https://github.com/quantopian/alphalens 。本地原文external_1.txt。Quantopian相关平台介绍是旧项目文本，不表示其服务当前仍运营。
3. QuantConnect LEAN官方定仓文档明确：目标比例换算数量为0、或低于MinimumOrderMarginPortfolioPercentage时，SetHoldings不下单且不记录日志；并说明多资产目标需要先减仓后增仓。这与我们需要显式记录最低金额/数量/资金约束相符。文档：https://www.quantconnect.com/docs/v2/writing-algorithms/trading-and-orders/position-sizing 。本地原文external_2.txt。我们的平台不是LEAN，不能直接把它的参数套用。
4. 实际案例：Zipline issue #2732，用户以10000美元开始比特币回测，亏损后账户买不起1个整币，策略便不再买卖。讨论建议按更小单位建模。它确实是先排查交易单位和资金约束，而不是先更换技术指标；但该讨论没有给出已验证的收益改善。链接：https://github.com/quantopian/zipline/issues/2732 。问题与评论均保存。本账户是A股，不能仿照数字资产把100股整手约束删掉，更不能通过虚增资金美化小账户回测。

结论：先分解市场状态、信号、仓位、最低金额、成交限制，再做单因素完整回放，是有成熟分析工具和实际问题依据的流程。没有找到证据证明直接提高仓位或取消防守能稳定提高我们这套策略的收益。先前项目取消市场防守退出的R2在同一段历史两档成本均为负，详见../recovery_research/RESULT.md，不能因为防守日多就直接删掉。

本轮只测试恢复阶段最低金额4000改3000；保留A股整手与风险预算。市场防守主因另作研究，放松市场过滤需要检查防守期日线股票覆盖；原筛选结果不能冒充完整的替代股票池。
