"""Compare isolated and supported combined changes against original E1."""
import json
from collections import defaultdict
from statistics import mean
from e1_asymmetric import ROOT,OUT,save

def closed_trades(result):
    opened={};closed={}
    for f in result['fills']:
        if f['buy']:assert f['symbol'] not in opened;opened[f['symbol']]=f
        else:
            b=opened.pop(f['symbol']);assert b['quantity']==f['quantity']
            key=(b['symbol'],b['fill_time'],b['price'],b['quantity'])
            closed[key]=dict(buy=b,sell=f,pnl=f['net_pnl'])
    return closed

def decomposition(result,baseline):
    a=closed_trades(result);b=closed_trades(baseline);common=set(a)&set(b);new=set(a)-set(b);removed=set(b)-set(a)
    rows=[dict(symbol=k[0],buy=k[1],quantity=k[3],old_pnl=b[k]['pnl'],new_pnl=a[k]['pnl'],delta=a[k]['pnl']-b[k]['pnl'],old_sell=b[k]['sell']['fill_time'],new_sell=a[k]['sell']['fill_time']) for k in sorted(common)]
    groups={}
    for label in ('winner','loser'):
        rr=[r for r in rows if (r['old_pnl']>=0)==(label=='winner')]
        groups[label]=dict(count=len(rr),pnl_change=sum(r['delta'] for r in rr),helped=sum(r['delta']>1e-7 for r in rr),hurt=sum(r['delta']<-1e-7 for r in rr))
    extras=sum(a[k]['pnl'] for k in new);omitted=-sum(b[k]['pnl'] for k in removed)
    remainder=(result['final']['dividend_income']-result['final']['dividend_tax']+result['final']['unrealized_pnl'])-(baseline['final']['dividend_income']-baseline['final']['dividend_tax']+baseline['final']['unrealized_pnl'])
    total=sum(r['delta'] for r in rows)+extras+omitted+remainder
    assert abs(total-(result['final']['equity']-baseline['final']['equity']))<1e-5
    return dict(matched_original_groups=groups,matched=rows,new_or_resized_count=len(new),new_or_resized_pnl=extras,removed_or_resized_count=len(removed),removed_or_resized_contribution=omitted,dividend_and_open_position_difference=remainder,total_delta=total)

def main():
    statuses=json.loads((OUT/'run_status.json').read_text(encoding='utf8'));selection=json.loads((OUT/'combination_decision.json').read_text(encoding='utf8'))
    extra=any(s['mode']=='RW' for s in statuses) and len(selection['positive_single_modes'])==1
    expected=6+(2 if len(selection['positive_single_modes'])>1 or extra else 0)
    assert len(statuses)==expected and all(s['status']=='COMPLETED' for s in statuses)
    rows=[];attribution={}
    for s in statuses:
        mode,cost=s['mode'],s['cost'];r=json.loads((OUT/f'{mode}_cost{cost}.json').read_text(encoding='utf8'))
        b=json.loads((ROOT/f'reports/exit_research/extension_2020/E1_cost{cost}.json').read_text(encoding='utf8'))
        assert len(r['daily'])==730 and len(r['minute_curve'])==175200
        cash=30000+sum((-1 if f['buy'] else 1)*f['price']*f['quantity']-f['fees'] for f in r['fills'])+r['final']['dividend_income']-r['final']['dividend_tax']
        assert abs(cash-r['final']['cash'])<1e-5
        previous=30000;years={}
        for y in ('2018','2019','2020'):
            end=[d for d in r['daily'] if d['date'].startswith(y)][-1]['equity'];years[y]=(end/previous-1)*100;previous=end
        equity=r['final']['equity'];events=json.loads((OUT/f'{mode}_cost{cost}_events.json').read_text(encoding='utf8'))
        rows.append(dict(mode=mode,cost=cost,return_pct=r['metrics']['marked_return']*100,annualized_pct=((equity/30000)**(1/3)-1)*100,baseline_return_pct=b['metrics']['marked_return']*100,delta_yuan=equity-b['final']['equity'],max_drawdown_pct=r['metrics']['max_minute_close_drawdown']*100,baseline_drawdown_pct=b['metrics']['max_minute_close_drawdown']*100,final_equity=equity,buys=sum(f['buy'] for f in r['fills']),fees=r['metrics']['fees_paid'],yearly=years,mean_close_exposure_pct=mean((d['equity']-d['cash']-d['dividend_receivable'])/d['equity'] for d in r['daily'])*100,flat_close_days=sum(abs(d['equity']-d['cash']-d['dividend_receivable'])<1e-6 for d in r['daily']),events=len(events)))
        attribution[f'{mode}_{cost}']=decomposition(r,b)
    decisions={}
    for mode in dict.fromkeys(r['mode'] for r in rows):
        rr=[r for r in rows if r['mode']==mode]
        if all(r['delta_yuan']>0 for r in rr):decisions[mode]='两档样本内收益正向，需新时期验证'
        elif all(r['delta_yuan']<=0 for r in rr):decisions[mode]='两档收益未改善，不采用'
        else:decisions[mode]='成本档方向不同，不稳定'
    save('comparison.json',dict(rows=rows,decisions=decisions));save('trade_attribution.json',attribution)
    names={'R':'取消恢复前20天等待，小仓恢复','W':'盈利趋势延长至最多40天','L':'前5天半R收盘止损'}
    lines=['# 盈利延续、亏损控制与回撤恢复对照','',
      '2026-09-09。用户明确授权研究修改冻结规则及12%回撤停止开仓。旧E1保留为基准，2018—2020已经多次查看，结果为样本内探索，不能称收益最大化或已证明可实盘盈利。','',
      'R在12%至15%回撤区间，市场连续5天通过原趋势门槛后允许小仓试探，取消旧R1的20天等待。风险减半、最多1只、最多20%股票仓位、风险不超过剩余硬停止空间一半。',
      'W只有持有20天后收盘利润>=2R且高于前一日已知MA10才继续，最多40天；原2ATR跟踪止损、市场防守保留。前日MA10在除息时按原价格调整桥接。',
      'L只在前5个持有交易日收盘亏损达到0.5R时新增退出计划。R是入场初始计划止损距离；止损只能下一交易日按分钟撮合，跳空/跌停可能超过阈值。',
      '', '|方案|成本|三年累计|年化|最大分钟回撤|相对E1增益|买入次数|','|---|---:|---:|---:|---:|---:|---:|']
    for r in rows:lines.append(f"|{names.get(r['mode'],r['mode']+'组合')}|{r['cost']}|{r['return_pct']:.2f}%|{r['annualized_pct']:.2f}%|{r['max_drawdown_pct']:.2f}%|{r['delta_yuan']:+.2f}元|{r['buys']}|")
    lines+=['','原E1正常/压力两档累计+5.75%/+3.49%，最大分钟回撤13.62%/13.22%。初始本金均3万元。','']
    lines += [f"- {names.get(k,k+'组合')}：{v}。" for k,v in decisions.items()]
    lines+=['','原预登记只组合两档收益都优于E1的单项；入选单项：'+str(selection['positive_single_modes'])+'。'+('另按INTERACTION_AMENDMENT.md追加RW互补机制探索，不属于预登记筛选通过的组合，不改参数。' if extra else '没有额外组合。'),'',
      '|方案|成本|2018|2019|2020|平均收盘仓位|收盘空仓天数|','|---|---:|---:|---:|---:|---:|---:|']
    for r in rows:lines.append(f"|{r['mode']}|{r['cost']}|{r['yearly']['2018']:.2f}%|{r['yearly']['2019']:.2f}%|{r['yearly']['2020']:.2f}%|{r['mean_close_exposure_pct']:.2f}%|{r['flat_close_days']}|")
    lines+=['','## 盈利与亏损交易贡献','',
      '|方案|成本|匹配原盈利交易的损益变化|匹配原亏损交易的损益变化|新增/改数量交易损益|移除/改数量旧交易贡献|','|---|---:|---:|---:|---:|---:|']
    for r in rows:
        a=attribution[f"{r['mode']}_{r['cost']}"];g=a['matched_original_groups']
        lines.append(f"|{r['mode']}|{r['cost']}|{g['winner']['pnl_change']:+.2f}|{g['loser']['pnl_change']:+.2f}|{a['new_or_resized_pnl']:+.2f}|{a['removed_or_resized_contribution']:+.2f}|")
    lines+=['','单位元。匹配要求股票、买入时间、成交价、数量完全相同；新买入或数量变化不能冒充同一笔交易纯卖点差异。另计分红/税和期末未实现损益后，贡献和严格等于账户相对E1的权益差额。该分解是账务归因，不是独立的规则因果证明。',
      '本轮W正常成本仅1次延长事件：002317.SZ由2020-01-23卖出延至2020-02-03，净利润从2615.77降至1507.45元，少赚1108.32元。正常成本账户却多508.11元，是因为后续少做6笔亏损交易，贡献+1616.44元。不能将账户改善称为盈利持仓利润扩大，也不能将单次跨春节事件外推。',
      'R正常/压力两档仅新增2笔买卖，原38笔买卖净损益完全不变。相比旧的等待20天R1方案，本轮取消等待的正常成本增益更小（旧R1约+71.44元，本轮+31.88元），压力档相同约+63.92元；不能把取消等待说成已优于所有既有恢复方案。',
      '', '## 验证与下一步','',
      f'{expected}条730交易日连续账户、每条175200个分钟点完成，全部买卖现金流、分红税与期末现金核对通过，交易贡献核对通过。359项模块测试通过，新增6项覆盖恢复风险边界、盈利延长条件、早止损时点和除息均线桥接。',
      '历史最高点只作为诊断参考，未用于决定卖点。研究版没有改写实盘入口或直接下单；用户授权已允许优化旧规则，仍应根据验证结果决定替换。任何样本内改善需要新时期和成本稳定性复核。',
      '未见数据验证与新RQAlpha路径复验尚未完成。旧费率沿用以便控制变量，不宣称各年税费法定版本已重算。']
    (OUT/'RESULT.md').write_text('\n'.join(lines)+'\n',encoding='utf8');print(json.dumps(dict(rows=rows,decisions=decisions),ensure_ascii=False))

if __name__=='__main__':main()
