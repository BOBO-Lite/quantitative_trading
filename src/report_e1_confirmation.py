"""Account attribution, fixed-entry case, and sealed confirmation evidence."""
import json,hashlib
from collections import Counter
from statistics import mean
from run_e1_confirmation import ROOT,OUT,save
from e1_confirmation import MODES
from report_e1_asymmetric import decomposition

def main():
    statuses=json.loads((OUT/'run_status.json').read_text(encoding='utf8'));assert len(statuses)==12
    rows=[];attributions={};fills={}
    refs={'E1':ROOT/'reports/exit_research/extension_2020','W':ROOT/'reports/e1_asymmetric','P':ROOT/'reports/e1_turning'}
    for mode in MODES:
        for cost in (1.,1.5):
            r=json.loads((OUT/f'{mode}_cost{cost}.json').read_text(encoding='utf8'));fills[f'{mode}_{cost}']=r['fills']
            assert len(r['daily'])==730 and len(r['minute_curve'])==175200
            cash=30000+sum((-1 if f['buy'] else 1)*f['price']*f['quantity']-f['fees'] for f in r['fills'])+r['final']['dividend_income']-r['final']['dividend_tax']
            assert abs(cash-r['final']['cash'])<1e-6
            deltas={}
            for ref,folder in refs.items():
                old=json.loads((folder/f'{ref}_cost{cost}.json').read_text(encoding='utf8'));a=decomposition(r,old);attributions[f'{mode}_vs_{ref}_{cost}']=a;deltas[ref]=a['total_delta']
            events=json.loads((OUT/f'{mode}_cost{cost}_events.json').read_text(encoding='utf8'))
            prev=30000;annual={}
            for y in ('2018','2019','2020'):
                eq=[d['equity'] for d in r['daily'] if d['date'].startswith(y)][-1];annual[y]=(eq/prev-1)*100;prev=eq
            rows.append(dict(mode=mode,cost=cost,return_pct=r['metrics']['marked_return']*100,annualized_pct=((r['final']['equity']/30000)**(1/3)-1)*100,drawdown_pct=r['metrics']['max_minute_close_drawdown']*100,equity=r['final']['equity'],delta_yuan=deltas,buys=sum(f['buy'] for f in r['fills']),yearly=annual,event_counts=dict(Counter(e['event'] for e in events)),mean_exposure_pct=mean((d['equity']-d['cash']-d['dividend_receivable'])/d['equity'] for d in r['daily'])*100))
    for cost in (1.,1.5):
        a=json.loads((OUT/f'CF_cost{cost}.json').read_text(encoding='utf8'));b=json.loads((OUT/f'C_cost{cost}.json').read_text(encoding='utf8'));attributions[f'CF_vs_C_{cost}']=decomposition(a,b)
    decisions={}
    for m in MODES:
        rr=[r for r in rows if r['mode']==m]
        decisions[m]='两档样本内收益超过E1，需独立新时期验证' if all(r['delta_yuan']['E1']>.005 for r in rr) else '两档收益低于E1，不替换' if all(r['delta_yuan']['E1']<-.005 for r in rr) else '与E1相同，无新增收益' if all(abs(r['delta_yuan']['E1'])<=.005 for r in rr) else '两档改善方向不一致，不稳定'
    save('comparison.json',dict(rows=rows,decisions=decisions));save('attribution.json',attributions)
    case=json.loads((OUT/'case_confirmation.json').read_text(encoding='utf8'))['results']
    names=dict(V='前日放量下跌确认',S='近5日相对弱势确认',H='均线下30分钟未恢复确认',C='三项至少两项确认',F='连续弱势亏损退出',CF='组合确认＋亏损退出')
    lines=['# 回调确认与趋势失败研究结果','', '2026-09-10。固定六组候选后，完成2018—2020连续3万元账户、正常/1.5倍成本共12条路径。全部为已见历史探索；未使用未来高低点决定成交。规则详见PROTOCOL.md。', '',
      'V/S/H/C保留上轮W盈利延长，仅给上轮P的新增盘中退出增加确认。F单独接原E1，CF组合C与F。原买入、仓位、费用和风险退出不变；与E1、W、P同时比较，避免把修复P误报为优于E1。', '',
      '|方案|正常累计收益|压力累计收益|正常最大回撤|压力最大回撤|结论|','|---|---:|---:|---:|---:|---|',
      '|原E1|5.75%|3.49%|13.62%|13.22%|基准|','|上轮W|7.44%|3.48%|—|—|盈利延长基准|','|上轮P|1.29%|0.84%|13.16%|13.12%|未确认利润保护基准|']
    for m in MODES:
        a,b=[r for r in rows if r['mode']==m];lines.append(f"|{m} {names[m]}|{a['return_pct']:.2f}%|{b['return_pct']:.2f}%|{a['drawdown_pct']:.2f}%|{b['drawdown_pct']:.2f}%|{decisions[m]}|")
    lines+=['','累计为三年总收益，不是年化。','', '## 众生药业固定原买入对照','',
      '保持002317.SZ在2019-12-25 09:46买入600股、10.75074元完全相同；原E1与W的买卖时间、价格、费用、数量精确复现。这是独立单笔实验，不代替完整账户。', '',
      '|规则|卖出时间|净利润|比原E1变化|比上轮P变化|', '|---|---|---:|---:|---:|']
    for m,r in case.items():lines.append(f"|{m}|{r['fills'][1]['fill_time']}|{r['net_pnl']:.2f}元|{r['net_pnl']-case['E1']['net_pnl']:+.2f}元|{r['net_pnl']-case['P']['net_pnl']:+.2f}元|")
    lines+=['','H及C避开12月27日的早卖，并在1月23日下午退出，避免W拖到春节后，但仍比原E1在同日早盘卖出少赚。不能称成功识别最终最高点。V和S仍会把上涨途中的回调当成退出。', '',
      '## 收益来自哪里','', '|方案|成本|比E1多赚|比W多赚|比P多赚|原盈利匹配交易变化|原亏损匹配交易变化|', '|---|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        g=attributions[f"{r['mode']}_vs_E1_{r['cost']}"]['matched_original_groups'];d=r['delta_yuan']
        lines.append(f"|{r['mode']}|{r['cost']}|{d['E1']:+.2f}|{d['W']:+.2f}|{d['P']:+.2f}|{g['winner']['pnl_change']:+.2f}|{g['loser']['pnl_change']:+.2f}|")
    lines+=['','### F的正向账户结果不能误报为准确识别亏损','',
      '正常成本F唯一新增退出为601717.SH：原E1净赚283.23元，F在2019-12-27提前退出净亏176.07元，少赚459.31元。新增交易净亏436.01元，移除6笔原交易带来1540.54元贡献，合计账户多645.22元。它把一笔最终会盈利的交易提前卖成亏损，账户改善主要来自之后不再做的交易。',
      '进一步核对风险路径：正常成本F在2020-02-04达到12.08596%回撤并空仓，此后至年末无新买入、权益保持32369.17元；原E1首次收盘回撤超过12%在2020-05-20。因此F避开后续3月和5月交易，主要关联更早触发账户停止开仓。该门槛与信号存在交互，不能把账户增益全归功于准确识别亏损。下一阶段应分离退出信号与回撤后恢复规则验证。',
      '压力成本F共2个新增退出事件。严格相同买入的600256.SH少亏27.94元，其余新增/少做/改数量的交易共同作用后，账户仅多50.60元。如此少的事件不能证明稳定分类能力。',
      '', '|F成本|共同交易变化|新增/改数量交易损益|移除/改数量旧交易贡献|分红及期末差额|账户总差额|', '|---|---:|---:|---:|---:|---:|']
    for cost in (1.,1.5):
        a=attributions[f'F_vs_E1_{cost}'];g=a['matched_original_groups']
        lines.append(f"|{cost}|{g['winner']['pnl_change']+g['loser']['pnl_change']:+.2f}|{a['new_or_resized_pnl']:+.2f}|{a['removed_or_resized_contribution']:+.2f}|{a['dividend_and_open_position_difference']:+.2f}|{a['total_delta']:+.2f}|")
    lines+=['','单位元。共同交易严格匹配股票、买入时间、价格、数量；新增/少做/数量改变的交易和分红、期末估值另计，38组贡献全部与账户权益差额核对。已匹配交易只是总差额的一部分，不能据此忽略后续机会变化。', '',
      '|方案|成本|2018|2019|2020|买入次数|平均收盘仓位|事件统计|', '|---|---:|---:|---:|---:|---:|---:|---|']
    for r in rows:lines.append(f"|{r['mode']}|{r['cost']}|{r['yearly']['2018']:.2f}%|{r['yearly']['2019']:.2f}%|{r['yearly']['2020']:.2f}%|{r['buys']}|{r['mean_exposure_pct']:.2f}%|{r['event_counts']}|")
    lines+=['','事件日志按股票/入场/日期/接受或否决去重，不等于分钟命中次数或实际成交次数。最终买卖以成交账本为准。', '',
      '## 验证与边界','', '373项模块测试通过，新增8项验证未来数据拒绝、未来日线不影响前日指标、30分钟计数/恢复/跨日重置、组合票数及原风险退出优先。E1和P正常成本全路径对照的逐笔成交一致，分钟权益误差小于1e-6元。12条730日账户、2102400个分钟权益点完成，现金及38组贡献核对通过。',
      '采用前日完整成交量与5日相对收益，而非当天尚未完成的总量。H只计已经结束的分钟，午休不计，收盘重复调用不重复计数；前日均线按原除息桥接。',
      '全部历史已反复使用；没有未见验证，没有新RQAlpha独立复验，不更改实盘入口或下单。原数据股票池及历史事件覆盖限制仍保留，不能把样本内改善当作未来保证。数据补充和平台使用情况见execution_audit.json。']
    (OUT/'RESULT.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps(dict(rows=rows,decisions=decisions),ensure_ascii=False))

if __name__=='__main__':main()
