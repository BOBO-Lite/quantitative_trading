"""汇总固定ETF研究版本的全部成本结果、独立核账与历史边界。"""
import hashlib,json
from datetime import date
from pathlib import Path
from etf_dataset import OUT,ROOT

def main():
    extended=OUT/'extended_2018_2026'
    out=extended if (extended/'cost1.5.json').exists() else OUT
    rs=[json.loads((out/f'cost{c}.json').read_text(encoding='utf8')) for c in (1.,1.5)]
    parity=json.loads((out/'rqalpha_parity.json').read_text(encoding='utf8')) if (out/'rqalpha_parity.json').exists() else []
    lines=['# ETF1.0 宽基ETF研究结果','',
           '研究范围已获用户同意。固定两只境内股票ETF，周频入场、日收盘风控，真实09:35分钟成交模型；本报告不是买卖指令。',
           '',f"连续区间：{rs[0]['daily'][0]['date']}—{rs[0]['final']['date']}，{rs[0]['days']}交易日，30000元现金起步，无年度重置。",'',
           '| 指标 | 基准成本 | 1.5倍成本 |','|---|---:|---:|']
    fields=[('期末权益',[f"{r['final']['equity']:.2f}元" for r in rs]),('累计扣费收益',[f"{r['metrics']['marked_return']:.2%}" for r in rs]),('最大日收盘回撤',[f"{r['metrics']['max_close_drawdown']:.2%}" for r in rs]),('成交笔数',[str(len(r['fills'])) for r in rs]),('佣金合计',[f"{r['metrics']['fees']:.2f}元" for r in rs]),('到账分红',[f"{r['metrics']['dividends_paid']:.2f}元" for r in rs]),('开仓暂停',[str(r['final']['paused']) for r in rs])]
    lines+=['| '+' | '.join([name]+values)+' |' for name,values in fields]
    lines+=['','滑点计入成交价；佣金万2、最低5元是研究假设，未据用户券商实际费率确认。日收盘回撤不等于分钟最大回撤，不能与TECH1分钟回撤直接同口径比较。',
            '', '## 分阶段收益（同一连续账户，不重置本金）','', '| 区间 | 基准成本 | 1.5倍成本 |','|---|---:|---:|']
    for start,end in [('2018-01-01','2022-12-31'),('2023-01-01','2024-12-31'),('2025-01-01','2026-12-31')]:
        vals=[]
        for r in rs:
            rows=[x for x in r['daily'] if start<=x['date']<=end]
            prior=[x for x in r['daily'] if x['date']<start]
            vals.append(f"{rows[-1]['equity']/(prior[-1]['equity'] if prior else 30000)-1:.2%}" if rows else '未完成')
        lines.append('| '+' | '.join([start[:4]+'—'+end[:4]]+vals)+' |')
    lines+=['','2023以后是固定版本在已存在历史中的后续验证，不是真正未见未来。若触发暂停，后续空仓期间仍计入连续账户，但不能冒充新的活跃交易样本。',
            '', '## 独立执行验证','']
    if parity:
        lines.append(f"RQAlpha真实ETF事件/撮合/账户两档通过，共核对{sum(r['daily_comparisons'] for r in parity)}个日收盘账户、{sum(r['fills'] for r in parity)}笔成交；最大现金/权益差{max(r['max_cash_equity_difference'] for r in parity):.3g}元。相同订单意图，独立执行及原生基金现金分红；不等于独立选股验证。")
    else:lines.append('当前区间独立RQAlpha核验尚未完成。')
    long_dir=OUT/'long_trend'
    if (long_dir/'cost1.5.json').exists():
        long_results=[json.loads((long_dir/f'cost{c}.json').read_text(encoding='utf8')) for c in (1.,1.5)]
        lines+=['','## ETF2.0月度200日均线对照（另行预登记，无参数搜索）','',
                '| 口径 | 基准成本 | 1.5倍成本 |','|---|---:|---:|',
                '| 累计收益 | '+' | '.join(f"{r['metrics']['marked_return']:.2%}" for r in long_results)+' |',
                '| 日收盘最大回撤 | '+' | '.join(f"{r['metrics']['max_close_drawdown']:.2%}" for r in long_results)+' |',
                '| 成交笔数 | '+' | '.join(str(len(r['fills'])) for r in long_results)+' |',
                '| 首次暂停日期 | '+' | '.join(next((d['date'] for d in r['daily'] if d['paused']),'未暂停') for r in long_results)+' |',
                '', '该版本也不支持启用。ETF研究共2个版本、4档成本结果全部保留；没有提高账户风险限额、重置历史峰值或挑选最佳成本档。ETF2的实现扩展后ETF1逐日及逐笔结果保持完全一致，见etf1_regression.json。']
        if (long_dir/'rqalpha_parity.json').exists():
            lp=json.loads((long_dir/'rqalpha_parity.json').read_text(encoding='utf8'))
            lines.append(f"ETF2独立RQAlpha核验通过：{sum(r['daily_comparisons'] for r in lp)}个日收盘账户、{sum(r['fills'] for r in lp)}笔成交。两版本完整区间合计{sum(r['daily_comparisons'] for r in lp+parity)}次日收盘核对、{sum(r['fills'] for r in lp+parity)}笔成交核对；不可将重叠工程窗口相加冒充更多独立交易样本。")
    lines+=['','## 结论及限制','',
            '是否上线必须看扣费后的收益与风险证据。2018—2022两档五年累计收益仅3.09%/0.86%，收益余量很薄；不能仅凭正数、回撤低于12%或软件测试通过就认定可用。后续结果全部披露，不选择更好成本档或临时调整参数。',
            '', '2022-12-05有一处分钟聚合与独立日线高低价不一致：新浪日线确认日线极值，原始分钟未改，例外已逐项记录。2022年510500份额拆分并未在本次实际持仓中产生权益；如另一个账户跨登记日持有，该版本仍必须中止，不能宣称通用拆分账户已实现。',
            '', '结论：当前两个ETF版本均不启用。只测试了固定两只宽基与两套规则，不能据此证明所有股票ETF策略无效。用户已于2026-09-09接受国债/黄金ETF范围，ETF3已完成独立报告，见../multiasset_research/RESULT.md；无需再次确认范围，也无需用真实交易补历史证据。',
            '', '原实盘账户、东吴证券2000股记录、冻结S1与原实盘协议均未因ETF研究改变。无自动交易。规则与来源见PROTOCOL.md、SOURCES.md；原始数据、失败导出和全部逐笔记录均保留。']
    (OUT/'RESULT.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    report_path=out/('TRAINING_RESULT.md' if out==OUT else 'RESULT.md')
    report_path.write_text('\n'.join(lines)+'\n',encoding='utf8')
    if out==extended:
        checks=[]
        for c,r in zip((1.,1.5),rs):
            old=json.loads((OUT/f'cost{c}.json').read_text(encoding='utf8'))
            equivalent=old['daily']==[d for d in r['daily'] if d['date']<='2022-12-30'] and old['fills']==[f for f in r['fills'] if f['datetime'][:10]<='2022-12-30']
            checks.append(dict(cost=c,training_prefix_identical=equivalent))
            if not equivalent:raise ValueError('扩展回放改变了既有研究前缀')
        (out/'prefix_equivalence.json').write_text(json.dumps(checks,indent=2),encoding='utf8')
    files=[ROOT/p for p in ('src/etf_dataset.py','src/etf_replay.py','src/validate_etf_rqalpha.py','adapters/rqalpha_etf_mod.py','tests/test_etf_research.py')]
    files += [OUT/'PROTOCOL.md',OUT/'SOURCES.md',report_path,out/'data_audit.json',out/'probe_export.txt',out/'minute_export.txt',out/'cost1.0.json',out/'cost1.5.json']
    if parity:files.append(out/'rqalpha_parity.json')
    files += [OUT/'ETF2_PROTOCOL.md',OUT/'module_tests.txt',OUT/'platform_restore.json',OUT/'etf1_regression.json',OUT/'NEXT_RESEARCH_SCOPE.md']
    if (long_dir/'rqalpha_parity.json').exists():files += [long_dir/'cost1.0.json',long_dir/'cost1.5.json',long_dir/'rqalpha_parity.json']
    (out/'manifest.json').write_text(json.dumps(dict(scope='ETF1 research evidence, not deployment acceptance',sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}),ensure_ascii=False,indent=2),encoding='utf8')
    print('ETF报告及输入摘要已生成')

if __name__=='__main__':main()
