# 真实日线特征与组合样本连接

本轮完成真实历史技术特征计算和分钟组合接口连接。由于财报日历、完整股票池排名及行业特征缺证据，回放明确禁止开仓；零订单不能解释为策略没有机会或收益为零。

## 真实导出证据

报告：https://quant.10jqka.com.cn/view/study-index.html#/backtest-result?id=6a9fdb7054104300b63c389a

页面确认2019-04-22至23分钟回测、1秒完成；只在22日盘前导出，23日跳过。取得招商银行、平安银行各160根原始日线，以及中证500的160根收盘日线，共480行，终点为2019-04-19。9个分片重建3个包，沿用长度和SHA256核验。首次同日起止的页面提交未生成可见报告，改为两日区间后完成；不据此推断平台所有单日任务均不支持。

源码：`adapters/supermind_feature_history_probe.py`；实际上传快照：`feature_export_uploaded_6a9fdb7054104300b63c389a.py`；原始日志：`feature_export_6a9fdb7054104300b63c389a.txt`。完成后编辑器恢复普通v5并确认保存。

## 特征计算规则

新增 `src/research_daily_features.py`：

- 先按信号日截断，再校验、计算；导出时拥有较晚数据，不等于较晚数据可以进入过去特征。
- MA20、MA60包含信号日；五日斜率与五日前的MA20比较。前20日突破、均量、均额以及前10日结构窗口排除信号日。
- RSI登记为14日简单平均涨跌幅（Cutler口径），ATR20为20日简单TR均值；这些是研究计算定义，不是本轮挑收益后的参数选择。
- 原始价格最近61日必须复权因子一致；因子变化报错，尚未执行公司行动归一化，不混算虚假的均线或结构止损。
- 股票最近61个日期必须与基准匹配，缺行不能当成停牌；至少120根有效收盘记录才可计入上市行情下限，上市前空记录不计数。
- 相对强度只计算本股相对基准收益，不把两个股票样本相互排名冒充全市场百分位。`rs_percentile=null`、`event_clear=false`、`pit_verified=false`，缺项原因逐行保留。

2019-04-16、17、18、19四个信号日，两只股票共8行技术特征计算成功，错误0；分别仅使用截至当日的157、158、159、160根观察记录。

## 组合连接结果

新增 `src/build_history_sample_bundle.py` 将上述前日特征与已核验的1440行分钟样本连接，并核对收盘原始价格和因子。三天完整运行，6行前日股票信号均保留3项缺失证据，订单0、成交0。

结果状态为 `INPUT_GATES_BLOCKED_NO_STRATEGY_TRADES`，`performance_interpretation_allowed=false`。此连接器专门用于验证缺证据时的真实样本行为，拒绝通过简单设置verified标志解锁；未来完整证据流程应单独实现验收入口。

输出：

- `portfolio_replay/historical_daily_features.json`：真实技术特征与缺证据原因；
- `portfolio_replay/real_gated_bundle.json`：真实日线/分钟连接包；
- `portfolio_replay/real_gated_replay.json`：失败关闭回放结果，不能作绩效报告。

```powershell
.\.venv\Scripts\python.exe src/research_daily_features.py --log reports/s2_research/feature_export_6a9fdb7054104300b63c389a.txt --output reports/s2_research/portfolio_replay/historical_daily_features.json
.\.venv\Scripts\python.exe src/build_history_sample_bundle.py --features reports/s2_research/portfolio_replay/historical_daily_features.json --minutes reports/s2_research/portfolio_replay/historical_minute_sample.json --output-dir reports/s2_research/portfolio_replay
```

## 验证与剩余工作

新增13项测试：未来数据不变性（含真实样本）、突破/量比排除信号日、缺日期、除权窗口、空上市记录、缺ST状态、基准截断、真实日线分钟连接、门禁标志不可任意解锁、收盘口径冲突等。全套模块170/170、核心6/6，共176/176，完整性PASS；冻结S1源码未变。

下一阶段要补齐历史时点股票池的完整横截面排名、当时已经知道的财报预约/事件日历，以及行业归属和强度特征；不能用事后实际公告日期冒充事前已知日历。还需统一公司行动及开盘/跨午休撮合口径。目前160日两股样本不是全市场、长周期有效性证据，正式8次绩效实验仍0/8。
