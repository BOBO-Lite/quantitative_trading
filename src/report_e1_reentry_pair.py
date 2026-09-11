"""Separate entry recovery effects from F exit effects."""
import json,hashlib
from statistics import mean
from collections import Counter
from run_e1_reentry_pair import ROOT,OUT,save
from e1_reentry_pair import MODES
from report_e1_asymmetric import decomposition

def read(p):return json.loads(p.read_text(encoding='utf8'))
def reentry_audit(r):
    peak=30000.;dd={};soft=None;hard=None
    for v in r['minute_curve']:
        peak=max(peak,v['equity']);d=1-v['equity']/peak;dd[v['datetime']]=d
        if soft is None and d>=.12:soft=v['datetime']
        if hard is None and d>=.15:hard=v['datetime']
    buys=[f for f in r['fills'] if f['buy']]
    recovery=[dict(symbol=f['symbol'],intent_time=f['intent_time'],fill_time=f['fill_time'],price=f['price'],quantity=f['quantity'],intent_drawdown=dd[f['intent_time']]) for f in buys if dd[f['intent_time']]>=.12]
    return dict(first_soft_cross=soft,first_hard_cross=hard,actual_buys_with_intent_drawdown_at_least_12=recovery,last_buy=buys[-1]['fill_time'] if buys else None,flat_close_days=sum(abs(d['equity']-d['cash']-d['dividend_receivable'])<1e-6 for d in r['daily']))

def main():
    assert len(read(OUT/'run_status.json'))==12
    rows=[];attr={};audits={};base_rows=[]
    refs={'E1':ROOT/'reports/exit_research/extension_2020','F':ROOT/'reports/e1_confirmation'}
    for b,folder in refs.items():
        for cost in (1.,1.5):
            r=read(folder/f'{b}_cost{cost}.json');audits[f'{b}_{cost}']=reentry_audit(r)
            base_rows.append(dict(mode=b,cost=cost,return_pct=r['metrics']['marked_return']*100,drawdown_pct=r['metrics']['max_minute_close_drawdown']*100))
    for m in MODES:
        for cost in (1.,1.5):
            r=read(OUT/f'{m}_cost{cost}.json');baseline='F' if m.startswith('F') else 'E1';old=read(refs[baseline]/f'{baseline}_cost{cost}.json')
            assert len(r['daily'])==730 and len(r['minute_curve'])==175200
            cash=30000+sum((-1 if f['buy'] else 1)*f['quantity']*f['price']-f['fees'] for f in r['fills'])+r['final']['dividend_income']-r['final']['dividend_tax']
            assert abs(cash-r['final']['cash'])<1e-6
            a=decomposition(r,old);attr[f'{m}_vs_{baseline}_{cost}']=a;ra=reentry_audit(r);audits[f'{m}_{cost}']=ra
            events=read(OUT/f'{m}_cost{cost}_events.json');previous=30000.;years={}
            for y in ('2018','2019','2020'):
                eq=[d['equity'] for d in r['daily'] if d['date'].startswith(y)][-1];years[y]=(eq/previous-1)*100;previous=eq
            rows.append(dict(mode=m,cost=cost,return_pct=r['metrics']['marked_return']*100,annualized_pct=((r['final']['equity']/30000)**(1/3)-1)*100,drawdown_pct=r['metrics']['max_minute_close_drawdown']*100,baseline=baseline,delta_yuan=a['total_delta'],final=r['final'],buys=sum(f['buy'] for f in r['fills']),recovery_buys=len(ra['actual_buys_with_intent_drawdown_at_least_12']),flat_days=ra['flat_close_days'],first_soft_cross=ra['first_soft_cross'],first_hard_cross=ra['first_hard_cross'],last_buy=ra['last_buy'],yearly=years,mean_exposure_pct=mean((d['equity']-d['cash']-d['dividend_receivable'])/d['equity'] for d in r['daily'])*100,event_counts=dict(Counter(e['event'] for e in events))))
    pairs=[]
    for suffix in ('R','U','H'):
        for cost in (1.,1.5):
            f=read(OUT/f'F{suffix}_cost{cost}.json');e=read(OUT/f'E1{suffix}_cost{cost}.json');a=decomposition(f,e);attr[f'F{suffix}_vs_E1{suffix}_{cost}']=a
            pairs.append(dict(recovery=suffix,cost=cost,f_minus_e1_yuan=a['total_delta'],f_minus_e1_pct=(f['final']['equity']-e['final']['equity'])/30000*100))
    for cost in (1.,1.5):
        attr[f'FH_vs_FR_{cost}']=decomposition(read(OUT/f'FH_cost{cost}.json'),read(OUT/f'FR_cost{cost}.json'))
    save('comparison.json',dict(baselines=base_rows,rows=rows,pairs=pairs));save('attribution.json',attr);save('reentry_audit.json',audits)
    names=dict(E1='原E1＋旧12%停止',F='原F＋旧12%停止',E1R='E1＋趋势确认小仓恢复',FR='F＋趋势确认小仓恢复',E1U='E1取消12%停止',FU='F取消12%停止',E1H='E1＋恢复状态锁定',FH='F＋恢复状态锁定')
    lines=['# 12%回撤重新开仓与退出信号交叉检验','', '2026-09-10。用户最终版要求已写入FINAL_STRATEGY_REQUIREMENTS.md：旧12%停止只能作为研究对照，不能因空仓净值无法自我修复而无条件长期禁止重新开仓。此要求不等于所有重新开仓都有正收益。', '',
      '固定2018—2020连续三年、初始3万元、正常/1.5倍成本。R在12%—15%区间市场连续5天趋势确认后允许半风险、最多1只/20%仓位、剩余硬停止风险空间的一半内小仓恢复。U仅取消12%禁止入场，按原正常风险交易，作为对照。两者保留15%硬停止及所有原成交约束；不重置历史高点。', '',
      'H为恢复状态锁定：达到12%后保持小仓，直到回撤修复至10%且市场趋势连续确认5天才恢复正常风险。这里的H不是上一阶段同名盈利确认信号。最初8条路径事前固定，新增4条H路径是在发现12%附近仓位切换问题后追加的已见历史探索，见HYSTERESIS_AMENDMENT.md。', '',
      '|方案|正常三年累计|压力三年累计|正常最大回撤|压力最大回撤|', '|---|---:|---:|---:|---:|']
    for m in ('E1','F')+MODES:
        rr=[r for r in base_rows+rows if r['mode']==m];a,b=rr
        lines.append(f"|{names[m]}|{a['return_pct']:+.2f}%|{b['return_pct']:+.2f}%|{a['drawdown_pct']:.2f}%|{b['drawdown_pct']:.2f}%|")
    lines+=['','这是三年累计，不是年化。成本变化会改变整手仓位、后续持仓及风险阈值触发时点，必须对照完整账户。', '',
      '## 相同恢复机制下F是否更好','', '|恢复机制|成本|F比E1多赚|累计收益差|', '|---|---:|---:|---:|']
    for p in pairs:lines.append(f"|{p['recovery']}|{p['cost']}|{p['f_minus_e1_yuan']:+.2f}元|{p['f_minus_e1_pct']:+.2f}个百分点|")
    lines+=['','## 12%后是否真的重新买入','', '恢复次数按真实成交的原委托分钟回撤计算，不能用允许下单事件数代替成交数。12%后可能修复回撤，表中仅统计委托时仍不低于12%的买入。逐笔日期、股票、金额见reentry_audit.json。', '',
      '|方案|成本|12%区间真实买入|全部买入|收盘空仓天数|首次达到15%|最后买入|比各自旧版多赚|', '|---|---:|---:|---:|---:|---|---|---:|']
    for r in rows:lines.append(f"|{r['mode']}|{r['cost']}|{r['recovery_buys']}|{r['buys']}|{r['flat_days']}|{r['first_hard_cross'] or '未达到'}|{r['last_buy']}|{r['delta_yuan']:+.2f}元|")
    lines+=['','R可能因整手、最小交易金额及剩余风险预算无法买入，这与禁止全部恢复的旧规则不同。U可能更快触发15%硬停止；硬停止不是实际最大回撤的成交保证。', '',
      '## 损益归因','', '|方案|成本|原盈利匹配交易变化|原亏损匹配交易变化|新增或改数量交易损益|移除或改数量旧交易贡献|分红及期末估值差|总差额|', '|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        a=attr[f"{r['mode']}_vs_{r['baseline']}_{r['cost']}"];g=a['matched_original_groups']
        lines.append(f"|{r['mode']}|{r['cost']}|{g['winner']['pnl_change']:+.2f}|{g['loser']['pnl_change']:+.2f}|{a['new_or_resized_pnl']:+.2f}|{a['removed_or_resized_contribution']:+.2f}|{a['dividend_and_open_position_difference']:+.2f}|{a['total_delta']:+.2f}|")
    lines+=['','单位元。严格匹配买入股票/时点/价格/数量；未实现损益单独核账，不假定期末强平。收益差额全部通过账户权益核对。', '',
      '|方案|成本|2018|2019|2020|平均收盘仓位|', '|---|---:|---:|---:|---:|---:|']
    for r in rows:lines.append(f"|{r['mode']}|{r['cost']}|{r['yearly']['2018']:.2f}%|{r['yearly']['2019']:.2f}%|{r['yearly']['2020']:.2f}%|{r['mean_exposure_pct']:.2f}%|")
    lines+=['','## 12%附近仓位切换诊断','',
      'FR正常成本在2020-06-17恢复买入600782.SH后，6月18日10:08回撤短暂修复到11.9756%，原R立即恢复正常定仓；在已有4370元持仓时，10:09又买入000717.SZ 1600股、成交额6694.69元。这笔净亏474.17元。H追加实验针对这处风险状态切换，不改变F退出信号。',
      '下表为完整账户差异，不能把避免上述一笔亏损直接当成最终收益提升：', '',
      '|退出规则|成本|锁定恢复H相对原恢复R的期末权益差|', '|---|---:|---:|']
    for prefix in ('E1','F'):
        for cost in (1.,1.5):
            h=next(r for r in rows if r['mode']==prefix+'H' and r['cost']==cost)
            rr=next(r for r in rows if r['mode']==prefix+'R' and r['cost']==cost)
            lines.append(f"|{prefix}|{cost}|{h['final']['equity']-rr['final']['equity']:+.2f}元|")
    lines+=['','## 本轮判断与下一步','',
      'F＋恢复状态锁定FH是本轮继续研究的优先候选，不是已通过上线的最终策略。相对旧F，正常/压力仅增加81.99/63.92元，最大回撤从12.09%/12.37%升至12.76%/12.71%；不能只报收益提高。相对FR，两档分别增加482.20/362.70元。',
      '正常成本的482.20元改善由移除000717.SZ亏损474.17元及新增交易盈利8.03元构成，35笔严格匹配交易的损益均未改变。压力成本的362.70元来自减少20笔合计亏损的交易，38笔严格匹配交易的损益未改变。改善属于恢复阶段仓位与入场约束，不能归因于退出信号更准确。',
      '直接取消12%且恢复正常风险的U两种退出方案、两档成本均劣于各自旧基准，且都越过15%硬停止。因此保留为负面对照，不纳入当前优先候选。旧12%机制也只作为对照，最终候选必须有不依赖空仓净值自我修复的重新开仓条件。',
      'FH正常/压力近似三年复合年化只有2.65%/1.27%；正常成本730个交易日中620日收盘空仓，平均收盘股票仓位7.38%。收益仍然低，整体资金利用问题尚未解决。下一阶段冻结FH参数并以E1H同风险机制为对照，逐项拆分剩余空仓原因、入场质量与风险预算；修改前先记录试验规则，收益改进需其他时期验证。',
      '保留15%硬停止是本轮隔离12%软规则影响的明确实验边界；并不表示15%永久停机机制已完成最终设计。不得通过重置历史高点、忽略亏损或删除成本来制造恢复。']
    lines+=['','## 验证边界','', '382项模块测试通过，新增9项覆盖软阈值恢复、市场确认、剩余风险预算、同风险机制的E1/F定仓一致和硬停止保留。R/F正常成本旧路径逐笔和175200分钟权益对照一致。12条730日完整账户、2102400个分钟权益点、12条现金核账及20组收益贡献核对通过。',
      '沿用现有历史股票池及数据边界，不能外推为全A股无偏收益。全部为已见历史研究，没有未见验证，没有新RQAlpha独立复验。最终版必须实现可执行恢复机制，但本轮测试并不自动代表某候选已被批准为最终策略。未修改实盘入口、未下单；数据补充及平台恢复见execution_audit.json。']
    (OUT/'RESULT.md').write_text('\n'.join(lines)+'\n',encoding='utf8');print(json.dumps(dict(rows=rows,pairs=pairs),ensure_ascii=False))
if __name__=='__main__':main()
