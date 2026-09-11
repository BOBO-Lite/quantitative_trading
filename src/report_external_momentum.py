import json
from pathlib import Path
from collections import defaultdict,Counter
from external_momentum import ROOT,OUT

def summary(r):
    peak=30000.;dd=0.;years={};last=30000.
    for row in r['daily']:peak=max(peak,row['equity']);dd=max(dd,1-row['equity']/peak)
    for y in ('2018','2019','2020'):
        rows=[v for v in r['daily'] if v['date'].startswith(y)];end=rows[-1]['equity'];years[y]=end/last-1;last=end
    return dict(total_return=r['daily'][-1]['equity']/30000-1,max_daily_drawdown=dd,years=years,ending_equity=last)

def main():
    events=json.loads((OUT/'corporate_events.json').read_text(encoding='utf8'))['events'];screen=json.loads((OUT/'screen.json').read_text(encoding='utf8'));comparison=[];attributions=[]
    for cost in (1.,1.5):
        r=json.loads((OUT/f'M0_cost{cost}.json').read_text(encoding='utf8'));base=json.loads((ROOT/f'reports/recovery_research/R0_cost{cost}.json').read_text(encoding='utf8'))
        comparison.append(dict(cost=cost,momentum=dict(summary(r),cagr=r['metrics']['cagr'],fills=len(r['fills']),fees=sum(f['fee'] for f in r['fills']),average_close_exposure=sum(x['exposure']/x['equity'] for x in r['daily'])/730),baseline=summary(base)))
        values=defaultdict(float);byday={d['date']:d for d in r['daily']}
        for f in r['fills']:values[f['symbol']]+=f['quantity']*f['price']*(-1 if f['buy'] else 1)-f['fee']-f['dividend_tax']
        for e in events:values[e['symbol']]+=byday.get(e['record_date'],{}).get('positions',{}).get(e['symbol'],0)*e['cash_per_share']
        from run_external_momentum import inputs
        daily,_,_,_=inputs()
        for s,q in r['final']['positions'].items():values[s]+=q*daily[s][r['final']['date']]['close']
        values={s:v for s,v in values.items() if v or any(f['symbol']==s for f in r['fills'])}
        if abs(sum(values.values())-(r['final']['equity']-30000))>1e-6:raise ValueError('attribution does not sum to equity gain')
        attributions.append(dict(cost=cost,net_contribution=dict(sorted(values.items(),key=lambda x:x[1])),order_reasons=dict(Counter(o['reason'] for o in r['orders'])),peak=max(r['daily'],key=lambda x:x['equity']),trough=max(r['daily'],key=lambda x:x['drawdown'])))
    bm=screen['benchmark'];benchmark=bm['2020-12-31']/bm['2017-12-29']-1
    (OUT/'comparison.json').write_text(json.dumps(dict(comparisons=comparison,benchmark_price_return=benchmark,benchmark_note='CSI500 price index, excludes dividends; not a directly tradable investment return'),ensure_ascii=False,indent=2),encoding='utf8')
    (OUT/'attribution.json').write_text(json.dumps(attributions,ensure_ascii=False,indent=2),encoding='utf8')
    lines=['# EXT-MOM1第一套外部规则回测结果','','2018-01-02—2020-12-31，730交易日，3万元连续账户。M0为Clenow思路的中证500主板、小账户适配，非作者原版、美股收益或实盘记录。本轮完成M0两档，不启用账户交易。','','|方案|成本|三年累计|年化CAGR|日收盘最大回撤|期末权益|','|---|---|---:|---:|---:|---:|']
    for c in comparison:
        m=c['momentum'];b=c['baseline'];lines.append(f"|M0动量适配|{c['cost']}倍|{m['total_return']:.2%}|{m['cagr']:.2%}|{m['max_daily_drawdown']:.2%}|{m['ending_equity']:.2f}元|")
        lines.append(f"|E1原对照|{c['cost']}倍|{b['total_return']:.2%}|见前期结果|{b['max_daily_drawdown']:.2%}|{b['ending_equity']:.2f}元|")
    lines+=['','表中两者回撤均重新按日收盘权益计算，不把新策略日回撤与旧策略分钟回撤直接混比。交易费用口径一致；M0目标5只、95%仓位与25%单股目标上限，保留月度卖出，但没有E1的账户暂停/硬停止覆盖，风险预算不同。并非全变量控制的选股隔离实验。','','|年份|正常成本|1.5倍成本|','|---|---:|---:|']
    for y in ('2018','2019','2020'):lines.append(f"|{y}|{comparison[0]['momentum']['years'][y]:.2%}|{comparison[1]['momentum']['years'][y]:.2%}|")
    lines+=['','## 研究判断','','M0没有提高收益，当前不采用。2018年没有实际成交，收益为0；首次成交为2019-03-01，不能把三年都叫活跃交易期。2019年春季曾盈利，此后回吐并转亏；2020年继续亏损。不能截取早期上涨作为成功，也不能因一次A股小账户适配失败断言Clenow所有实现或全球动量因子无效。','',f"正常成本累计费用{comparison[0]['momentum']['fees']:.2f}元，压力档{comparison[1]['momentum']['fees']:.2f}元。两档各56笔成交（含调仓和部分成交，不等于56笔独立完整交易）。期末均持有601717.SH 400股，权益含该持仓市值4372元。",'','逐股净损益见attribution.json；它包含买卖现金流、费用、红利税、现金分红和期末市值，合计严格等于期末权益减本金。','','## 证据与限制','','36个月共16252个100日原始窗口在本地独立复算；完整股票池分类、ST/停牌、200日指数均线及排名顺序核验通过。59只候选股只用于缩小行情请求范围，不用于回填过去的排名池。','', '两档各730个日收盘账户、56笔成交，通过另一种以原始购入份额建账的方法复核现金、股份、分红和税费，最大差异0。它消费相同成交，不是RQAlpha独立撮合，也不是另一套数据源独立选股复现。本轮未获得全分钟账户最大回撤。','', '实际持有的股本分配为002414.SH对应深圳代码002414.SZ在2019-05-08每股转增0.5股；执行代码使用002414.SZ。原200股增加100股，按公布可交易日期处理，且与独立分红表核对。其他数据中送股和转增的权益若无实际持仓，不得称实仓路径验收。600195.SH的2020分配比例冲突及000563.SZ配股仍保留为持有时阻塞事件，本轮账户未获得这些事件权益。','', '600270.SH在2018-12-28信号日的成分列表残留，依据此前发布的终止上市消息及已核验证券表单独解析，没有映射到收购方或虚构行情。','', '首次整段导出超过平台日志上限；改成年份分批保留原始源日志。上市前空分钟仅在同日没有有效日线、或明确停牌时接受，不能将活跃股票缺分钟当作不交易。日线/分钟有异常则阻断，不补造价格。','','## 下一项工作','','按既定优先级转向小流通市值＋财务质量规则，先验证历史时点市值、ROE、经营现金流及资产负债表字段。当前M0失败不作为改变90日窗口、月度频率或放宽入场条件的理由。现有账户约束覆盖版尚未运行，正式协议和真实持仓未改变。']
    # Correct code notation explicitly in the generated report.
    text='\n'.join(lines).replace('002414.SH对应深圳代码002414.SZ','002414.SZ')+'\n'
    (OUT/'RESULT.md').write_text(text,encoding='utf8')
    print(json.dumps(dict(comparison=comparison,benchmark=benchmark,largest_losses=list(attributions[0]['net_contribution'].items())[:5]),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
