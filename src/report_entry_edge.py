from entry_edge_audit import ROOT,OUT,read,save
from statistics import mean
from collections import Counter

def main():
    summaries=read(OUT/'summary.json');signals=read(OUT/'signal_cases.json');daily=read(OUT/'daily_comparison.json')
    data=read(ROOT/'reports/hold_benchmarks/historical_inputs.json')['daily'];checked=0;conflicts=[]
    packets={}
    for y in (2018,2019,2020):packets.update(read(OUT/f'data_{y}.json'))
    for p in packets.values():
        for row in p['fh']+p['momentum']:
            history=data.get(row['symbol'],{})
            for h,o in row['outcomes'].items():
                if o['status']!='OK':continue
                for day,fields in ((p['windows'][h]['entry'],(('open','open'),('factor','entry_factor'))),(p['windows'][h]['end'],(('close','close'),('factor','end_factor')))):
                    if day not in history:continue
                    for old,new in fields:
                        if abs(history[day][old]-o[new])>1e-8:conflicts.append(dict(symbol=row['symbol'],day=day,field=old))
                        checked+=1
    assert not conflicts
    common_dates={r['date'] for r in daily if r['horizon']==60}
    common=[]
    for h in (5,20,60):
        for group in ('FH_ALL','FH_TOP5','MOM_TOP5'):
            rs=[r for r in daily if r['date'] in common_dates and r['horizon']==h and r['group']==group and r['mean_return'] is not None]
            common.append(dict(group=group,horizon=h,n=len(rs),excess_pool_pct=mean(r['mean_return']-r['pool'] for r in rs)*100,excess_market_pct=mean(r['mean_return']-r['market'] for r in rs)*100))
    save('common_dates.json',common)
    complete_days={h:{p['date'] for p in packets.values() if p['windows'][str(h)] is not None and p['pool_stats'][str(h)]['valid']==p['pool_stats'][str(h)]['n'] and all(r['outcomes'][str(h)]['status']=='OK' for r in p['fh']+p['momentum'])} for h in (5,20,60)}
    complete=[]
    for year in ('ALL','2019','2020'):
        for h in (5,20,60):
            for group in ('FH_ALL','FH_TOP5','MOM_TOP5'):
                rs=[r for r in daily if r['date'] in complete_days[h] and r['horizon']==h and r['group']==group and (year=='ALL' or r['date'].startswith(year))]
                if rs:complete.append(dict(year=year,horizon=h,group=group,dates=len(rs),excess_pool_pct=mean(r['mean_return']-r['pool'] for r in rs)*100,excess_market_pct=mean(r['mean_return']-r['market'] for r in rs)*100))
    save('complete_date_sensitivity.json',complete)
    missing=[dict(date=p['date'],group=g,symbol=r['symbol'],horizon=h,status=o['status']) for p in packets.values() for g in ('fh','momentum') for r in p[g] for h,o in r['outcomes'].items() if o['status'] not in ('OK','CENSORED')]
    save('missing_endpoint_cases.json',missing)
    fh=[r for r in summaries if r['group']=='FH_ALL' and r['year'] in ('2019','2020') and r['horizon'] in (20,60)]
    mom=[r for r in summaries if r['group']=='MOM_TOP5' and r['year'] in ('2019','2020') and r['horizon'] in (20,60)]
    gate=lambda rs:len(rs)==4 and all(r['dates']>=20 and r['excess_pool_pct']>0 and r['excess_market_pct']>0 for r in rs)
    decision=dict(fh_cross_year_price_edge=gate(fh),momentum_cross_year_price_edge=gate(mom),formal_strategy_adopted=False,
        exact_portfolio_comparison_complete=False,
        reason='Daily forward adjusted prices are selection diagnostics, not executable net account returns')
    save('decision.json',decision)
    audit=dict(original_signal_checks=sum(read(OUT/f'audit_{y}.json')['signal_input_checks'] for y in (2018,2019,2020)),
        source_errors=sum(len(read(OUT/f'audit_{y}.json')['errors']) for y in (2018,2019,2020)),
        cached_raw_endpoint_field_checks=checked,conflicts=conflicts,
        signal_statuses=dict(Counter(r['status'] for r in signals)),
        actual_normal=len({(r['symbol'],r['date']) for r in signals if r['actual_cost1']}),
        actual_pressure=len({(r['symbol'],r['date']) for r in signals if r['actual_cost15']}))
    save('coverage_audit.json',audit)
    names={'FH_ALL':'FH全部候选','FH_TOP5':'FH成交额前5','MOM_TOP5':'简单60日动量前5'}
    lines=['# 买点价值检查：扩大样本后的同日比较','',
        '2026-09-10。本轮完成选股层价格统计，不是三套完整账户同资金净收益回测。2018—2020共6419个原条件候选股票-日期，156个信号日；未重新优化退出参数，也未更改FH或实盘。','',
        '## 口径','',
        '四个同日组：FH全部候选、按原成交额排序前5、基本可交易主板池等权、同池60日动量前5。动量仅使用当时已知60日涨幅且价格高于60日均线。所有组均限定在FH有候选的156天，不能推论动量其他日期的完整策略。', '',
        '信号日收盘后选股，下一交易日开盘至第5/20/60个交易日收盘，复权价格变化。先按当天候选等权，再按信号日等权；这是固定窗口平均价格变化，不是年化、累计净值或投资组合。宽基为000905.SH，同日起止开盘/收盘。实际交易仍需盘中确认、整手、费用、股息税、分钟撮合和资金竞争。','',
        '## 全样本同日价格比较','',
        '|窗口|方案|有效日期|平均价格变化|相对基础池平均差额|相对中证500平均差额|开盘不可直接买入的候选计数|',
        '|---|---|---:|---:|---:|---:|---:|']
    for r in summaries:
        if r['year']=='ALL':lines.append(f"|{r['horizon']}日|{names[r['group']]}|{r['dates']}|{r['mean_pct']:+.2f}%|{r['excess_pool_pct']:+.2f}个百分点|{r['excess_market_pct']:+.2f}个百分点|{r['untradable']}|")
    lines+=['','开盘不可直接买入包括停牌、ST及涨停价开盘，保留在价格统计而不冒充已成交收益。各窗口有重复股票和日期，不能将计数相加当独立交易。跨2020年底的窗口标记删失。基础池平均由平台探针聚合，原脚本及日志可复算；本地没有导出并独立重算全部基础池原始价格和动量全排名，不能将签名校验称独立数据源验证。','',
        '## 年份一致性','',
        '|年份|窗口|方案|日期|相对基础池差额|相对中证500差额|', '|---|---|---|---:|---:|---:|']
    for r in summaries:
        if r['year']!='ALL' and r['horizon'] in (20,60):lines.append(f"|{r['year']}|{r['horizon']}日|{names[r['group']]}|{r['dates']}|{r['excess_pool_pct']:+.2f}个百分点|{r['excess_market_pct']:+.2f}个百分点|")
    lines+=['','2018只有2个信号日，不能作为稳定年度优势的证据。common_dates.json另外将三个窗口限制在都有60日结果的相同日期，避免把窗口差异全部归因于持有时长。','',
        '## 实际成交与未成交','',
        '实际FH正常/压力36/38笔分别与紧邻前一日信号匹配；标签只说明后来是否实际成交，不进入事前选股。以下是相同假设开盘入场的逐信号价格统计，不是原成交价净收益，也不能因未成交组更好就断言资金限制错误。','',
        '|成本路径标签|窗口|是否实际成交|有效候选|逐信号平均价格变化|逐信号中位数|','|---|---|---|---:|---:|---:|']
    for r in read(OUT/'actual_vs_unfilled.json'):
        if r['horizon'] in (20,60):lines.append(f"|{r['cost']}|{r['horizon']}日|{'是' if r['actually_filled'] else '否'}|{r['n']}|{r['mean_pct']:+.2f}%|{r['median_pct']:+.2f}%|")
    lines+=['','## 判断与边界','',
        'FH在2019及2020的20/60日均同时超过基础池和指数：'+str(decision['fh_cross_year_price_edge'])+'。简单动量同项：'+str(decision['momentum_cross_year_price_edge'])+'。这是方向检查，不是统计显著性或盈利保证。', '',
        '本轮FH选股层有初步相对优势，保留作候选；简单60日涨幅前5未提供替换依据。2019年20日相对指数仅约0.05个百分点，不能称强优势。下一阶段优先固定规则跨时期迁移，并做完整账户的宽基对照，验证弱优势能否覆盖费用、盘中确认和资金约束；暂不再优化退出。既有M0外部动量适配曾亏损，不得因某个短窗口更好就抹去旧结果或直接上线。', '',
        '终点缺价明细：FH的000418.SZ在2019-04-01信号的60日终点缺价；动量的601313.SH在2018-01-25/26信号的20/60日缺价。基础池5/20/60日分别0/2/33条终点缺失记录，未擅自按0收益填补。主表采用可得价格；complete_date_sensitivity.json另将任何组或基础池有缺价的整个日期从所有组同时排除，作为敏感性核对，不能隐藏主样本缺口。', '',
        '本轮未完成新的宽基可交易持有账户、简单动量与FH三方同规则完整组合，未完成2021以后固定迁移检验。不得用本报告平均价格变化和FH三年累计8.17%直接作绩效优劣比较。','',
        '输入核验：'+str(audit)+'。平台原代码恢复核验见platform_restore.json。']
    (OUT/'RESULT.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(audit);print(decision)

if __name__=='__main__':main()
