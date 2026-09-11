# 真实历史分钟接入与组合统计推进

本轮把离线执行验证从合成输入推进到真实历史分钟样本；没有增加用户实盘交易，也没有运行正式选股收益优化。

## 数据证据

只读导出报告：https://quant.10jqka.com.cn/view/study-index.html#/backtest-result?id=6a9fd871acb66d00b64c4fda

- 页面区间2019-04-17至22、分钟频率、0秒完成；17至19日导出分钟，22日仅取得19日已经完成的日线用于对账。
- 招商银行600036.SH、平安银行000001.SZ，3个交易日，每股每日240分钟，总计1440行。
- 原始日志23个分片，重建11个包（3个分钟包、8个前日日线包）。长度、SHA256、解压边界、分片完整性和唯一性均验证。
- 6组股票/交易日的分钟覆盖、总成交量与日收盘价全部核账通过；第一分钟开盘与日开盘亦全部一致。成交额最大绝对差0.49元，其他招商银行差0.06/0.16元，平安银行为0。
- OHLC关系、量额、因子与停牌/ST状态检查通过。分钟对象未直接提供的factor/is_st明确使用**同一历史日期**原始日线核补，每行记录核补来源；没有使用当前状态或默认false。
- 初次导出报告6a9fd7f2281b0f00b64b80dc因沙箱禁止getattr失败；已改为显式字段读取。失败日志保留，未删除平台记录。
- 成功上传源码及日志分别为minute_export_uploaded_6a9fd871acb66d00b64c4fda.py、minute_export_6a9fd871acb66d00b64c4fda.txt；导出后编辑器已恢复普通v5并保存。

数据文件：`portfolio_replay/historical_minute_sample.json`。它只是两个固定股票的执行样本，不是无偏股票池或正式策略特征输入。

## 本地真实行情执行回放

`src/replay_historical_minute_probe.py` 使用本地ReplayBroker，在17日09:45发固定买入意图，19日09:45发固定退出意图，均由下一分钟真实开盘价加减滑点撮合。

| 分钟参与率 | 平安银行买/卖 | 招商银行买/卖 | 结果 |
|---|---|---|---|
| 25% | 500/500股 | 600/600股 | 四笔成交，期末无持仓，现金与已实现损益一致 |
| 0.1% | 500/500股 | 300/300股 | 招商银行买单部分成交并取消余量，四笔成交，账本一致 |

四个成交价分别为14.36435、35.88585、14.43555、36.04392元，与之前固定平台诊断的分钟成交价一致。参与率0.1%时招商银行该分钟350600股，保守买入整百股上限为300股；平台此前全额成交600股，差异仍未消除。

这里调整固定测试买单限价为平安银行14.5、招商银行36元，确保两笔订单最高含费预留同时不超过30000元；不能依赖平台同步回调提前释放现金。它与原平台cap38测试不是完全相同的委托集合。本地卖出税0.05%，平台样例0.10%，费用最低计提也不同，不能要求净现金相同。这些差异明确登记，不以更好盈亏判定引擎优劣。

输出：`portfolio_replay/historical_execution_replay.json`。两种场景均为固定指令执行诊断，**不是选股策略绩效**。

## 组合统计补充

research_portfolio.py 新增：

- 分钟收盘权益高水位到低点的最大回撤及峰谷时间，起始现金为初始高水位；不宣称刻画分钟内或盘口瞬时最大回撤。
- 分支已实现、未实现及合计盈亏，自动检查分支合计等于组合权益减初始本金；终点不虚构强平。
- 输出估值收益和实际成交费用合计。原合成基准/压力结果已重新生成。

## 验证与后续

新增9项导入/真实样本测试、2项组合统计测试。模块157/157，核心6/6，共163/163；完整性PASS。冻结S1平台源码哈希未变。

重放命令：

```powershell
.\.venv\Scripts\python.exe src/import_supermind_minute_probe.py --log reports/s2_research/minute_export_6a9fd871acb66d00b64c4fda.txt --output reports/s2_research/portfolio_replay/historical_minute_sample.json
.\.venv\Scripts\python.exe src/replay_historical_minute_probe.py --dataset reports/s2_research/portfolio_replay/historical_minute_sample.json --output reports/s2_research/portfolio_replay/historical_execution_replay.json
```

下一步仍需真实历史时点特征与事件门禁、完整股票池/基准、公司行动及开盘/跨午休撮合口径。不能把两个固定股票三天的核验推广到全部股票和所有日期。当前已有可复用的导出、核验、回放链路，但完整四分支历史绩效尚未运行；登记8次绩效实验仍0/8。
