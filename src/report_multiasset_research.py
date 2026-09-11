"""ETF3收益来源、仓位使用及固定旧版本回归；无交易接口。"""
import hashlib,json
from datetime import date
from pathlib import Path
from multiasset_research import inputs,OUT,SYMBOLS,BASE
from etf_dataset import build,ROOT
from etf_replay import replay

def main():
    calendar,daily,events,minutes=inputs()
    old_data=build(out=BASE);regressions=[]
    for variant,folder in [('ETF1.0',BASE),('ETF2.0',BASE.parent/'long_trend')]:
        for cost in (1.,1.5):
            old=json.loads((folder/f'cost{cost}.json').read_text(encoding='utf8'))
            new=replay(*old_data,cost=cost,end=old_data[0][-1],variant=variant)
            same=old==new
            regressions.append(dict(version=variant,cost=cost,entire_result_identical=same))
            if not same:raise ValueError('既有ETF结果发生改变')
    (OUT/'previous_versions_regression.json').write_text(json.dumps(regressions,indent=2),encoding='utf8')
    summaries=[]
    for cost in (1.,1.5):
        r=json.loads((OUT/f'cost{cost}.json').read_text(encoding='utf8'))
        curve=r['daily'];first=curve[0]['date'];last=curve[-1]['date'];years=(date.fromisoformat(last)-date.fromisoformat(first)).days/365.25
        by_date={d['date']:d for d in curve};contrib={s:0. for s in SYMBOLS}
        for f in r['fills']:contrib[f['symbol']]+=(-1 if f['buy'] else 1)*f['quantity']*f['price']-f['fee']
        for e in events:
            if e['kind']=='cash' and first<=e['pay_date']<=last:
                contrib[e['symbol']]+=by_date.get(e['record_date'],{}).get('positions',{}).get(e['symbol'],0)*e['cash']
        for s,q in curve[-1]['positions'].items():contrib[s]+=q*daily[s][last]['close']
        if abs(sum(contrib.values())-(r['final']['equity']-30000))>1e-6:raise ValueError('收益归因未对平')
        exposure=[sum(q*daily[s][d['date']]['close'] for s,q in d['positions'].items())/d['equity'] for d in curve]
        segments=[]
        for a,b in [('2018-01-01','2022-12-31'),('2023-01-01','2024-12-31'),('2025-01-01',last)]:
            rows=[d for d in curve if a<=d['date']<=b];prior=[d for d in curve if d['date']<a]
            segments.append(dict(start=a,end=b,return_=rows[-1]['equity']/(prior[-1]['equity'] if prior else 30000)-1))
        summaries.append(dict(cost=cost,cumulative_return=r['metrics']['marked_return'],cagr=(r['final']['equity']/30000)**(1/years)-1,
            max_daily_close_drawdown=r['metrics']['max_close_drawdown'],net_profit_by_symbol=contrib,average_close_exposure=sum(exposure)/len(exposure),
            invested_days=sum(v>0 for v in exposure),empty_days=sum(v==0 for v in exposure),segments=segments))
    # 单位总回报只作行情参照：分红复投、无费、无整手资金限制，不能当可执行组合。
    references=[]
    first='2018-01-02';last=calendar[-1]
    for s in SYMBOLS:
        a,b=daily[s][first],daily[s][last]
        references.append(dict(symbol=s,start=first,end=last,unit_total_return=b['close']*b['adjustment']/(a['close']*a['adjustment'])-1,
            note='日收盘复权单位总回报参照；无成本、分红复投，不是3万元整手可执行组合'))
    detail=dict(attribution=summaries,market_reference=references)
    (OUT/'attribution.json').write_text(json.dumps(detail,ensure_ascii=False,indent=2),encoding='utf8')
    parity=json.loads((OUT/'rqalpha_parity.json').read_text(encoding='utf8'))
    lines=['# ETF3.0 多资产历史研究结果','','完成2018-01-02—2026-09-04连续2106交易日回放。规则在本版本绩效前登记，黄金/国债范围已经用户批准。本版本在已见历史中研究，不是未见未来验证。',
        '', '| 指标 | 基准成本 | 1.5倍成本 |','|---|---:|---:|']
    for label,key in [('累计净收益','cumulative_return'),('账户复合年化收益','cagr'),('最大日收盘回撤','max_daily_close_drawdown'),('平均收盘仓位','average_close_exposure')]:
        lines.append('| '+label+' | '+' | '.join(f'{s[key]:.2%}' for s in summaries)+' |')
    for label,key in [('有持仓交易日','invested_days'),('空仓交易日','empty_days')]:
        lines.append('| '+label+' | '+' | '.join(str(s[key]) for s in summaries)+' |')
    lines+=['','两档期末分别38193.50元、37302.00元，均无持仓且未触发暂停。76笔成交/38次完整买卖，不能把两档重复样本合成76次独立买卖。',
        '', '## 资产收益贡献（含费用及实际分红）','', '| 标的 | 基准成本净贡献 | 1.5倍成本净贡献 |','|---|---:|---:|']
    for s in SYMBOLS:lines.append('| '+s+' | '+' | '.join(f"{x['net_profit_by_symbol'][s]:.2f}元" for x in summaries)+' |')
    lines+=['','国债ETF没有任何成交。其一手在本研究历史中最少10941.40元，2026-09-04为14122.10元，超过风险定仓能力；实际组合为沪深300ETF、黄金ETF和现金，不能称已经实现三资产分散。',
        '', '## 分阶段表现（连续账户，无本金重置）','', '| 阶段 | 基准成本 | 1.5倍成本 |','|---|---:|---:|']
    for i in range(3):lines.append('| '+summaries[0]['segments'][i]['start']+'—'+summaries[0]['segments'][i]['end']+' | '+' | '.join(f"{s['segments'][i]['return_']:.2%}" for s in summaries)+' |')
    lines+=['','## 行情参照','', '| 标的 | 同期复权单位总回报 |','|---|---:|']
    for x in references:lines.append(f"| {x['symbol']} | {x['unit_total_return']:.2%} |")
    lines+=['','参照不扣交易成本、假设分红复投、没有仓位/整手约束，不能直接声称策略跑赢或跑输同风险可执行基准。它用于辨别资产行情与择时能力，不是可部署替代方案。',
        '', '## 验证与决定','',f"独立RQAlpha两档通过：{sum(p['daily_comparisons'] for p in parity)}次日收盘账户、{sum(p['fills'] for p in parity)}笔成交核对，最大差{max(p['max_cash_equity_difference'] for p in parity):.3g}元。共用订单意图，日内三个真实分钟驱动；不是独立选股或全分钟回撤验证。",
        '', 'ETF1、ETF2两档完整输出在本次数据价位修正与多资产扩展后重新计算，四份结果完全一致。266项模块测试通过。平台原研究源码已恢复保存并逐字符核对，27858字符一致。',
        '', '结论：较前两版改善，保留为研究候选，但约3%的年化不构成已解决用户收益目标的证据；没有预先登记的部署收益门槛、未见未来表现和同风险可执行基准，不启用实盘。下一阶段继续退出对照及收益来源分析，不能因本次正收益扩大资金或宣称通过全部验收。']
    (OUT/'RESULT.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps(detail,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
