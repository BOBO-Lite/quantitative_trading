"""完整退出样本后续走势与组合结果；缺失不填零，不挑赢家。"""
import json
from statistics import mean,median
from exit_research import OUT,BASE
from simple_history_replay import load_inputs

def roundtrips(result):
    held={};closed=[]
    for f in result['fills']:
        s=f['symbol']
        if f['buy']:
            if s in held:raise ValueError('不支持叠加买入')
            held[s]=dict(symbol=s,entry_time=f['fill_time'],entry_price=f['price'],entry_quantity=f['quantity'],remaining=f['quantity'],realized_pnl_excluding_dividends=0.,exit_fills=[])
        else:
            p=held[s];p['remaining']-=f['quantity'];p['realized_pnl_excluding_dividends']+=f['net_pnl'];p['exit_fills'].append(f)
            if p['remaining']==0:
                p['exit_time']=f['fill_time'];p['last_exit_reason']=f['reason'];closed.append(p);del held[s]
    return closed,list(held.values())

def main():
    cache,days=load_inputs(2019);calendar=[d['date'] for d in days];by_day={d:i for i,d in enumerate(calendar)}
    results={};diagnostics=[];summaries=[]
    for variant in ('E0','E1','E2'):
        for cost in (1.,1.5):
            r=json.loads((OUT/f'{variant}_cost{cost}.json').read_text(encoding='utf8'));results[variant,cost]=r
            closed,opened=roundtrips(r)
            (OUT/f'{variant}_trades_cost{cost}.json').write_text(json.dumps(dict(closed=closed,open=opened),ensure_ascii=False,indent=2),encoding='utf8')
            if variant!='E0':continue
            rows=[]
            for trade in closed:
                s=trade['symbol'];d=trade['exit_time'][:10];history=cache.daily[s];start=history.get(d)
                item={k:v for k,v in trade.items() if k!='exit_fills'};item['forward']={}
                for horizon in (5,10):
                    index=by_day[d]+horizon
                    if index>=len(calendar):item['forward'][str(horizon)]=dict(status='SAMPLE_END');continue
                    target=calendar[index];end=history.get(target)
                    if not start or not end or any(r.get(k) is None or r[k]<=0 for r in (start,end) for k in ('close','factor')):
                        item['forward'][str(horizon)]=dict(status='MISSING_DAILY',date=target);continue
                    item['forward'][str(horizon)]=dict(status='OK',date=target,adjusted_close_return=end['close']*end['factor']/(start['close']*start['factor'])-1)
                rows.append(item)
            diagnostics.append(dict(cost=cost,trades=rows))
            for horizon in (5,10):
                values=[r['forward'][str(horizon)]['adjusted_close_return'] for r in rows if r['forward'][str(horizon)]['status']=='OK']
                summaries.append(dict(cost=cost,horizon=horizon,total_trades=len(rows),available=len(values),unavailable=len(rows)-len(values),up=sum(v>0 for v in values),down=sum(v<0 for v in values),flat=sum(v==0 for v in values),mean=mean(values) if values else None,median=median(values) if values else None))
    common=[]
    for cost in (1.,1.5):
        keys=lambda r:{(f['symbol'],f['fill_time']) for f in r['fills'] if f['buy']}
        original=keys(results['E0',cost])
        for v in ('E1','E2'):
            candidate=keys(results[v,cost]);common.append(dict(variant=v,cost=cost,original_entries=len(original),candidate_entries=len(candidate),common=len(original&candidate),only_original=len(original-candidate),only_candidate=len(candidate-original)))
    detail=dict(fixed_baseline_exit_samples=diagnostics,forward_summary=summaries,entry_overlap=common,note='退出日收盘到后5/10交易日复权收盘变化，不是卖出成交价到后续可成交价收益；不含额外持有费用，不能视作可执行策略。')
    (OUT/'diagnostics.json').write_text(json.dumps(detail,ensure_ascii=False,indent=2),encoding='utf8')
    lines=['# EXIT1 个股退出对照结果','','固定2018-01-02—2019-12-31共487交易日，3万元连续账户。E0原TECH1、E1收盘确认2ATR、E2收盘确认3ATR跟踪；初始风险/入场/市场退出规则不变。三版本各两档全部结果如下。',
        '', '| 版本 | 基准累计收益 | 压力累计收益 | 基准最大分钟收盘回撤 | 压力最大分钟收盘回撤 |','|---|---:|---:|---:|---:|']
    for v in ('E0','E1','E2'):
        a,b=results[v,1.],results[v,1.5]
        lines.append(f"| {v} | {a['metrics']['marked_return']:.2%} | {b['metrics']['marked_return']:.2%} | {a['metrics']['max_minute_close_drawdown']:.2%} | {b['metrics']['max_minute_close_drawdown']:.2%} |")
    lines+=['','E0两档与原TECH1完整输出逐项一致。E1/E2期末仍各有3只股票持仓，收益含未实现盈亏；没有虚构期末强平。原E0空仓且处于12%回撤暂停，不能将候选相对改善全归因于同一批交易卖得更好。',
        '', '## 全部原退出样本的后续走势','', '| 成本 | 退出后交易日 | 可计算/总数 | 上涨/下跌/持平 | 平均变化 | 中位数 |','|---|---:|---:|---:|---:|---:|']
    for s in summaries:lines.append(f"| {s['cost']} | {s['horizon']} | {s['available']}/{s['total_trades']} | {s['up']}/{s['down']}/{s['flat']} | {s['mean']:.2%} | {s['median']:.2%} |")
    lines+=['','以上是退出日收盘至后续复权收盘变化，缺失/样本终点不足均显式保留。不能把平均变化加到原账户净值，也不能据招商南油一例推断全体退出有问题。',
        '', '## 入场样本是否相同','', '| 版本 | 成本 | 原买入次数 | 候选买入次数 | 同代码同成交时点 |','|---|---:|---:|---:|---:|']
    for s in common:lines.append(f"| {s['variant']} | {s['cost']} | {s['original_entries']} | {s['candidate_entries']} | {s['common']} |")
    lines+=['','保持同一入场规则不等于实际成交样本相同：退出改变现金、仓位、风险和暂停路径。同成交时点的数量也可能不同，不能当严格同仓位的配对实验。']
    p=OUT/'rqalpha_parity.json'
    if p.exists():
        checks=json.loads(p.read_text(encoding='utf8'));passed=[r for r in checks if r['status']=='PASS_EXIT_MINUTE_ACCOUNT_PARITY']
        lines+=['','## 独立核账','',f"新退出候选通过{len(passed)}/4档RQAlpha核验，共{sum(r['minute_comparisons'] for r in passed)}次分钟现金/权益和{sum(r['fills'] for r in passed)}笔成交核对。共用订单意图；不等于独立选股或未来盈利验证。"]
    paired=OUT/'paired_trades.json'
    if paired.exists():
        pairs=json.loads(paired.read_text(encoding='utf8'))
        lines+=['','## 固定同一买入时点和数量的配对','', '| 成本 | 候选 | 完整配对数 | 改善/恶化/相同 | 每笔平均损益差 | 中位数 |','|---|---|---:|---:|---:|---:|']
        for s in pairs['summary']:
            lines.append(f"| {s['cost']} | {s['variant']} | {s['paired_closed']}/{s['total']} | {s['improved']}/{s['worse']}/{s['same']} | {s['mean_pnl_difference']:.2f}元 | {s['median_pnl_difference']:.2f}元 |")
        lines+=['','每笔E0入场及退出的价格、数量、成交时点、费用均与原成交逐项复现；全部25/37个样本可配对，无分钟缺口或期末截尾。两档样本重叠，不能算62个独立市场事件。隔离账户之间可能重叠占资，表中差额不能相加当作3万元组合收益。',
            '', '基准档配对均值改善，但压力档配对均值转负，而压力档组合仍改善。这支持进一步研究退出与后续资金路径的共同作用，不支持“只要卖晚一点就能修好收益”的结论。初次隔离尝试因包含账户成立前已除息事件被账本门禁拒绝，修正现金起步的公司行动边界后完成；被拒绝结果保存在paired_rejected_initial_boundary.json，未改原账本门禁。']
    lines+=['','## 阶段决定','','收盘确认在这两年样本中有改善线索，继续保留E1/E2研究，不修改冻结S1或原持仓保护单。3ATR不是所有费用档都优于2ATR，尚无统一赢家。收盘确认可能承担更大的盘中下跌与隔夜跳空，计划止损金额不保证实际损失上限。',
        '', '尚未完成：更长活跃历史和冻结后未见未来检验。现有2018—2019历史已被反复用于研究，不能把本次正收益当作样本外通过。2020扩展已登记，243个交易日、3701个股票日分钟请求分5批准备，覆盖1090只候选/年末持仓股票；目前尚未导出，不把请求数视为买入数。下一步保持E1/E2规则不变扩展连续历史，记录所有缺口和失败；不继续围绕这两年搜索参数。']
    (OUT/'RESULT.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps(dict(forward_summary=summaries,entry_overlap=common),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
