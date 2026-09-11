# SuperMind运行手册

官方资料：

- API文档：https://quant.10jqka.com.cn/view/help/4
- 回测引擎：https://quant.10jqka.com.cn/view/help/12
- 官方证券接口：`get_all_securities(ty=None, date=None)`，指定历史日期可返回当时上市证券；
  官方文档同时明确证券简称不可作为历史ST判断依据。
- A股日行情字段支持 `is_st`、`is_paused`、`high_limit`、`low_limit` 和 `factor`；
  正式SuperMind回测应直接使用这些时点字段，不用今天的名称倒推历史状态。
- 研究环境与实盘差异：https://quant.10jqka.com.cn/view/help/14

## 推荐流程

1. 打开SuperMind客户端并登录体验账号，进入“量化交易 → 研究环境”；
2. 上传或粘贴 `adapters/supermind_market_export.py`，先修改顶部 `SYMBOLS`；
3. 运行脚本并下载生成的 `supermind_market_snapshot.json`；
4. 将文件保存为本地项目 `runtime/supermind_market_snapshot.json`；
5. 本地接口会检查 `market_data_at`，超过90秒拒绝作为实时行情；
6. 在研究环境按 data_templates/ 的字段导出当时股票池、日线和分钟线；
7. 先用本地测试验证字段、信号和风险公式；
8. 在SuperMind选择“分钟回测”，不要用日回测代理9:45—10:30触发；
9. 通过 set_commission 设置佣金、最低佣金、印花税；通过 set_slippage 设置单边0.1%滑点；
10. 回测订单必须在信号确认后的下一根分钟K线撮合；
11. 保存回测参数、逐笔交易、未成交订单和日志；
12. 先跑基线配置，再跑费用/滑点+50%压力配置；
13. 不把回测代码直接接实盘；先完成至少10笔模拟执行。

## 全 A 股历史日线分片导出

使用 `adapters/supermind_daily_parts_export.py`。2026-09-02 在当前研究环境实测：

- `get_all_securities()` 返回143281条证券，其中 `type == "stock"` 为5801只；按四个上市日期字段过滤后仍为5801只沪深北股票；
- 一次请求5只、每只121根日线时，5/5返回，耗时约7.7秒；
- 一次请求20只超过约50秒仍未返回，且中断无效，因此脚本把 `BATCH_SIZE` 固定为5；
- 全市场约1161批，按实测速率估计至少约2.5小时，不能把测试批次直接当成全量完成。

首次验收保持 `START_BATCH = 0`、`END_BATCH = 2`，应得到：

- `supermind_universe.json`
- `supermind_export_manifest.json`
- `supermind_benchmark.json`（冻结配置要求的中证500 `000905.SH`）
- `supermind_daily_part_0000.json`
- `supermind_daily_part_0001.json`

下载并验证这四个文件后，才把 `END_BATCH` 改为 `None` 运行全量。若中途停止，根据清单中的 `last_completed_batch`，把 `START_BATCH` 改为下一批编号后续跑；已完成的分片不要删除或覆盖。每次续跑会新建本次清单，因此开始前应先下载并保存上一份清单。

研究环境限制：脚本不得加入普通文件读写、路径库或动态属性访问；JSON统一由 pandas 写入。输出只用于本地研究候选筛选，不构成可执行委托名单。

下载到 `runtime/` 后运行 `src/prepare_supermind_scan_data.py`。适配层把 SuperMind 的成交额字段 `turnover` 映射为冻结引擎使用的 `amount`，并结合股票池生成 `paused`、`st` 和 `listing_days`；基准必须是配置中的中证500，不能临时替换。

## 个人体验版边界

- 官方 `get_price()` 可在研究环境读取日线、分钟线并支持实时行情；
- 体验版安装目录本身不提供可供普通个人账户直接导入的本地Python包；
- 官方本地SDK申请面向符合条件的机构，不能把体验版DLL当作公开SDK逆向调用；
- 因此当前采用“研究环境导出 → 本地只读校验”的桥接方式；若以后获批本地SDK，再替换导出层，MCP上层接口不变。
- 若研究环境暂时无法加载，本地接口自动降级到东方财富公开只读行情；该降级源不替代券商/官方行情的实盘风控验收。

## 必须人工核对的差异

- 平台默认佣金和印花税可能与本系统不同，必须显式覆盖；
- 回测计算耗时可能使实盘下单晚于理论时间，必须记录信号时间与委托时间；
- 涨跌停、停牌、部分成交和订单撤销必须出现在日志中；
- 实盘查询持仓、资金和委托接口可能限频，不能每个tick反复调用；
- 任何平台API变更都先在模拟环境验证，不直接修改实盘版本。
