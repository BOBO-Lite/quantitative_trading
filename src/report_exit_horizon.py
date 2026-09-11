"""Describe fixed-window results without converting overlapping cases to a portfolio."""
from collections import Counter
from statistics import median
from exit_horizon_audit import ROOT, OUT, read, save
from hold_benchmarks import trade_batches

def main():
    rows=read(OUT/'cases.json'); groups=read(OUT/'groups.json')
    causes=[]
    for cost in (1.0,1.5):
        triggers={(r['symbol'],r['entry_date']):r for r in read(OUT/f'triggers_cost{cost}.json')}
        for t in trade_batches(read(ROOT/f'reports/e1_reentry_pair/FH_cost{cost}.json')):
            b=t['buy']; trigger=triggers[b['symbol'],b['fill_time'][:10]]
            for s in t['sells']:
                assert trigger['trigger_time']<=s['fill_time']
                assert s['reason'] in ('scheduled_exit',trigger['reason'],'drawdown_hard_stop')
                causes.append(dict(cost=cost,symbol=b['symbol'],entry=b['fill_time'],exit=s['fill_time'],
                    fill_reason=s['reason'],origin_reason=trigger['reason'],trigger_time=trigger['trigger_time']))
    save('fill_causes.json',causes)
    eligible=[]
    for reason in sorted({g['reason'] for g in groups}-{'ALL'}):
        selected=[g for g in groups if g['reason']==reason]
        if len(selected)==4 and all(g['complete']>=5 and g['median_difference_pct']>0 for g in selected):eligible.append(reason)
    yearly=[]
    for cost in (1.0,1.5):
        for horizon in (20,60):
            for year in ('2018','2019','2020'):
                for reason in sorted({g['reason'] for g in groups}-{'ALL'}):
                    sample=[r for r in rows if r['cost']==cost and r['horizon']==horizon and r['entry'].startswith(year) and r['trigger']['reason']==reason and r['status']=='COMPLETE']
                    if sample:yearly.append(dict(cost=cost,horizon=horizon,year=year,reason=reason,n=len(sample),
                        median_difference_pct=median(r['difference_pct'] for r in sample),
                        worst_difference_pct=min(r['difference_pct'] for r in sample),
                        best_difference_pct=max(r['difference_pct'] for r in sample)))
    save('annual_groups.json',yearly)
    stop_samples={cost:{(r['symbol'],r['entry']):r for r in rows if r['cost']==cost and r['horizon']==60 and r['status']=='COMPLETE' and r['trigger']['reason']=='close_confirmed_stop'} for cost in (1.0,1.5)}
    common=set(stop_samples[1.0]) & set(stop_samples[1.5])
    paired=[]
    for cost in (1.0,1.5):
        sample=[stop_samples[cost][k] for k in sorted(common)]
        paired.append(dict(cost=cost,n=len(sample),hold_better=sum(r['difference']>0 for r in sample),
            exit_better=sum(r['difference']<0 for r in sample),
            median_difference_pct=median(r['difference_pct'] for r in sample),
            symbols=[r['symbol'] for r in sample]))
    save('matched_stop_cases.json',paired)
    save('candidate_gate.json',dict(eligible_reason_groups=eligible,
        gate='At least five complete cases and positive median in each of both horizons and both costs',
        adoption=False,interpretation='Diagnostic gate only; no blind validation or full-account improvement established'))
    names={'cash_defense':'市场防守','close_confirmed_stop':'收盘确认跌破保护价','time_exit':'持有期限到期','persistent_weak_loss':'持续弱势亏损','drawdown_hard_stop':'账户硬回撤','ALL':'全部'}
    lines=['# FH真实退出原因与固定20/60日窗口结果','',
        '2026-09-10。本轮为归因研究，不修改FH或实盘规则。两档完整回放与封存FH逐字段一致。','',
        '## 真实退出原因','', '|成本|成交记录中的原因|最初触发原因|卖出成交笔数|','|---|---|---|---:|']
    for (cost,old,new),n in sorted(Counter((r['cost'],r['fill_reason'],r['origin_reason']) for r in causes).items()):
        lines.append(f'|{cost}|{old}|{names.get(new,new)}|{n}|')
    lines += ['', '## 相同买点、固定观察窗口', '',
        '买入日为第1日，使用第20/60交易日收盘。原退出必须已在窗口内全部成交；否则单列，不能偷用之后的卖出结果。持有端为扣买入成本、含现金分红的账面权益，未虚构终点卖出，原退出端有实际回测卖出费用及红利税。差额百分比以每笔原投入资金为分母，不是账户收益率。', '',
        '|成本|窗口|真实原因|全部|可比较|持有更好|原退出更好|持有减原退出的中位差额|',
        '|---|---:|---|---:|---:|---:|---:|---:|']
    for g in groups:
        v='—' if g['median_difference_pct'] is None else f"{g['median_difference_pct']:+.2f}个百分点"
        lines.append(f"|{g['cost']}|{g['horizon']}日|{names.get(g['reason'],g['reason'])}|{g['total']}|{g['complete']}|{g['hold_better']}|{g['exit_better']}|{v}|")
    lines += ['', '两档成本敏感性不是独立样本；各买点资金重叠，不加总为3万元组合收益。20日到期退出最早在第21日成交，因此20日窗口不足以评价其退出贡献。未完成的精确原因和日期见cases.json。市场字段是买入日收盘至末日收盘的指数价格变化，仅为行情背景，不能冒充同盘中买入时点的精确超额收益。','',
        '## 候选准入与下一步','',
        '事前登记的初筛要求：同一退出原因在两档成本、两个窗口都至少5个完整案例，且持有减原退出的中位差额均为正。它是研究线索门槛，不是盈利证明。', '',
        '通过初筛的原因：'+('、'.join(names.get(r,r) for r in eligible) if eligible else '无')+'。', '',
        '年度拆分和尾部差额保留于annual_groups.json。任何退出修改必须另行登记一个当时可观测的条件，检查完整账户中的资金占用和后续机会。若本轮不通过，不为制造新版本而删除退出；先处理观察窗口适用性及胜负差异。2018—2020已反复研究，不称盲测。','',
        '两档成本的交易集合不同，不能把保护退出60日中位数正负变化全部归因为手续费。共同的同股同买入日保护退出案例另见matched_stop_cases.json：'+ '; '.join(f"成本{r['cost']}共{r['n']}笔，持有更好{r['hold_better']}笔、退出更好{r['exit_better']}笔，中位差额{r['median_difference_pct']:+.2f}个百分点" for r in paired)+'。', '',
        '本轮决定：不直接取消市场防守、保护退出或期限退出，也不声称获得新的账户收益。后续更有针对性的研究是保护退出后是否出现可交易的恢复信号：先观察重新站回原保护价/短期均线后是否仍有收益，比较再入场成本和再次失败的损失。该方向尚未测试，不能宣称有效；无需为了它恢复12%永久冻结开仓。', '',
        '## 正反案例（正常成本60日，按差额两端展示）','',
        '|股票|买入日|真实原因|原退出损益|持有损益|差额|', '|---|---|---|---:|---:|---:|']
    sample=sorted([r for r in rows if r['cost']==1 and r['horizon']==60 and r['status']=='COMPLETE'],key=lambda r:r['difference'])
    for r in sample[:3]+sample[-3:]:
        lines.append(f"|{r['symbol']}|{r['entry']}|{names.get(r['trigger']['reason'],r['trigger']['reason'])}|{r['original_net']:+.2f}元|{r['hold_net']:+.2f}元|{r['difference']:+.2f}元|")
    (OUT/'RESULT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('Eligible groups:',eligible)
    print('Cause counts:',Counter((r['cost'],r['fill_reason'],r['origin_reason']) for r in causes))

if __name__=='__main__':main()
