"""Report extrema-led hypotheses, exact case repair, and full account results."""
import json
from statistics import mean
from e1_turning_research import ROOT,OUT,save
from report_e1_asymmetric import decomposition

def main():
    statuses=json.loads((OUT/'run_status.json').read_text(encoding='utf8'));assert len(statuses)==10 and all(s['status']=='COMPLETED' for s in statuses)
    rows=[];attr={};entry_comparisons={}
    for s in statuses:
        mode,cost=s['mode'],s['cost'];r=json.loads((OUT/f'{mode}_cost{cost}.json').read_text(encoding='utf8'))
        b=json.loads((ROOT/f'reports/exit_research/extension_2020/E1_cost{cost}.json').read_text(encoding='utf8'))
        assert len(r['daily'])==730 and len(r['minute_curve'])==175200
        cash=30000+sum((-1 if f['buy'] else 1)*f['price']*f['quantity']-f['fees'] for f in r['fills'])+r['final']['dividend_income']-r['final']['dividend_tax']
        assert abs(cash-r['final']['cash'])<1e-5
        equity=r['final']['equity'];previous=30000.;years={}
        for y in ('2018','2019','2020'):
            end=[d for d in r['daily'] if d['date'].startswith(y)][-1]['equity'];years[y]=(end/previous-1)*100;previous=end
        events=json.loads((OUT/f'{mode}_cost{cost}_events.json').read_text(encoding='utf8'))
        rows.append(dict(mode=mode,cost=cost,return_pct=r['metrics']['marked_return']*100,annualized_pct=((equity/30000)**(1/3)-1)*100,baseline_return_pct=b['metrics']['marked_return']*100,delta_yuan=equity-b['final']['equity'],max_drawdown_pct=r['metrics']['max_minute_close_drawdown']*100,baseline_drawdown_pct=b['metrics']['max_minute_close_drawdown']*100,final_equity=equity,buys=sum(f['buy'] for f in r['fills']),fees=r['metrics']['fees_paid'],yearly=years,event_counts={k:sum(e['event']==k for e in events) for k in sorted({e['event'] for e in events})},mean_close_exposure_pct=mean((d['equity']-d['cash']-d['dividend_receivable'])/d['equity'] for d in r['daily'])*100))
        attr[f'{mode}_{cost}']=decomposition(r,b)
        original_buys={(f['symbol'],f['fill_time'][:10]):f for f in b['fills'] if f['buy']}
        matches=[]
        for f in r['fills']:
            if f['buy'] and (f['symbol'],f['fill_time'][:10]) in original_buys:
                old=original_buys[f['symbol'],f['fill_time'][:10]]
                matches.append(dict(symbol=f['symbol'],date=f['fill_time'][:10],old_time=old['fill_time'],new_time=f['fill_time'],old_price=old['price'],new_price=f['price'],price_difference_pct=(f['price']/old['price']-1)*100))
        entry_comparisons[f'{mode}_{cost}']=dict(same_symbol_day_matches=len(matches),cheaper=sum(x['price_difference_pct']< -1e-8 for x in matches),more_expensive=sum(x['price_difference_pct']>1e-8 for x in matches),mean_price_difference_pct=mean(x['price_difference_pct'] for x in matches) if matches else None,matches=matches)
    decisions={}
    for mode in ('B','P','Q','PQ','BPQ'):
        rr=[r for r in rows if r['mode']==mode]
        decisions[mode]='两档样本内收益正向，仍需未见验证' if all(r['delta_yuan']>.005 for r in rr) else '两档收益不如E1，不采用' if all(r['delta_yuan']<-.005 for r in rr) else '与E1收益相同，未带来可计量增益' if all(abs(r['delta_yuan'])<=.005 for r in rr) else '成本档方向不同或无改善，未形成稳定增益'
    save('comparison.json',dict(rows=rows,decisions=decisions));save('trade_attribution.json',attr);save('entry_price_comparison.json',entry_comparisons)
    incremental={}
    for cost in (1.,1.5):
        for mode,base_mode,folder in [('P','W',ROOT/'reports/e1_asymmetric'),('PQ','P',OUT),('BPQ','B',OUT)]:
            new=json.loads((OUT/f'{mode}_cost{cost}.json').read_text(encoding='utf8'))
            old=json.loads((folder/f'{base_mode}_cost{cost}.json').read_text(encoding='utf8'))
            incremental[f'{mode}_vs_{base_mode}_{cost}']=decomposition(new,old)
    save('incremental_attribution.json',incremental)
    cases=json.loads((OUT/'original_trade_extrema.json').read_text(encoding='utf8'))['cases']
    losses=[c for c in cases if c['sell']['net_pnl']<0]
    rebound=dict(loss_count=len(losses),trough_before_sell_count=sum(c['rebound_time'] is not None for c in losses),returned_to_entry_after_observed_trough_count=sum(c['best_rebound_after_trough_pct'] is not None and c['best_rebound_after_trough_pct']>=0 for c in losses),warning='Retrospective holding-window prices only; intrabar rebound order is not reconstructed; no after-exit recovery observations. These are not predictive probabilities.')
    save('loss_rebound_summary.json',rebound)
    extrema_groups={}
    for label in ('winner','loser'):
        subset=[c for c in cases if (c['sell']['net_pnl']>=0)==(label=='winner')]
        extrema_groups[label]=dict(count=len(subset),net_profit=sum(c['sell']['net_pnl'] for c in subset),mean_peak_gain_pct=mean(c['peak_gain_pct'] for c in subset),mean_trough_return_pct=mean(c['trough_return_pct'] for c in subset),ever_positive_price_count=sum(c['peak_gain_pct']>0 for c in subset),ever_negative_price_count=sum(c['trough_return_pct']<0 for c in subset))
    save('extrema_groups.json',dict(groups=extrema_groups,warning='Outcome-grouped retrospective diagnostics; extrema include entry-day T+1-locked prices and omit exit-minute prices. Not executable potential profits or prospective classes.'))
    names={'B':'突破后回踩再确认买入','P':'盈利延长+盘中回撤保护','Q':'亏损后反弹未恢复则退出','PQ':'盈利保护+亏损反弹处理','BPQ':'回踩买入+盈利保护+亏损处理'}
    lines=['# 高低点倒推、退出修复与组合检验','', '2026-09-09。已见2018—2020历史探索，先诊断高低点，再固定可执行候选，不把未来高低点读入交易规则。','',
      '## 002317.SZ少赚1108.32元的原因','',
      '买入2019-12-25 09:46，600股，10.75074元。观察区间内最低分钟低价10.73（买入分钟），最高17.17（2020-01-21 09:31）。这只是本次买入日至延长卖出日的观察区间，不是全历史底顶。先前交易日低价买、后续交易日高价卖的事后价格上限约60.02%，未扣费且未验证能否成交。',
      '1月21日冲高后收15.60，1月22日继续收低至14.74。原E1在1月22日收盘安排第20天退出，1月23日09:32卖出15.13485，净赚2615.77元。W因仍有>=2R利润、收盘高于已知前日MA10而取消这次退出。1月23日收盘14.34低于已知MA10 14.358，不再延长，于收盘安排下一交易日卖出。',
      '下一交易日为2月3日，09:32开盘12.91处于跌停价，模型拒绝成交，09:33以13.28670卖出，净赚1507.45元。问题是趋势走弱未及时触发保护、取消期限退出后暴露于休市区间和成交限制；并非始终没有退出计划，也不是整笔交易最终亏损。',
      '', '![实际路径与三种退出](case_002317.png)','',
      '## 单笔修复验证：仍要避免假顶部','',
      '固定原买入时间、价格和600股数量，原E1和W成交全部精确复现。新增P保护在2019-12-27 10:03即以12.42756卖出，净利润992.22元，比原E1少1623.55元，比W还少515.22元。它把早期正常回调当成顶部，未能解决该案例；不能只挑1月21日的高点测试而忽略12月27日同样会出现的信号。',
      '单笔修复使用相同分钟撮合与费用，窗口因子恒定、无现金分红；仅固定该笔买入，不冒充完整账户。图中的盘中峰值与每日收盘不同，不将标出的最高价当作实际卖价。',
      '', '## 原亏损交易的反弹诊断','',
      f"原E1正常成本亏损{len(losses)}笔，其中持有窗口观察低点之后，后续完整分钟高价曾回到买入参考价的有{rebound['returned_to_entry_after_observed_trough_count']}笔。只描述最终仍亏损的交易，不包含退出后20天等未来窗口，不把这个比例用于预测反弹概率。", 
      'Q只在已观察到0.5R亏损后跟踪低点；反弹1ATR却仍低于买价和前日均线时退出，恢复买价则解除预警。保留原止损，不为赌反弹继续拖延。P、Q的运行高低点都是已完成分钟收盘，第一天只在收盘初始化，T+1后逐分钟观察。',
      '', '## 完整账户结果','',
      '|方案|成本|三年累计收益|年化|最大分钟回撤|比原E1多赚|买入次数|','|---|---:|---:|---:|---:|---:|---:|']
    for r in rows:lines.append(f"|{names[r['mode']]}|{r['cost']}|{r['return_pct']:.2f}%|{r['annualized_pct']:.2f}%|{r['max_drawdown_pct']:.2f}%|{r['delta_yuan']:+.2f}元|{r['buys']}|")
    lines+=['','基准原E1正常/压力三年累计+5.75%/+3.49%；此前W为+7.44%/+3.48%，RW为+6.04%/+3.69%。所有区间连续730交易日、初始3万元。', '']
    lines += [f'- {names[k]}：{v}。' for k,v in decisions.items()]
    lines+=['','## 新增规则的实际触发与组合差异','',
      'Q单独接原E1，两档均无weak_rebound_exit事件：这组反弹条件未在原退出之前完整满足，结果与E1一致。它尚未证明可以区分正常回调和趋势失败。',
      '在P基础上加入Q，压力成本路径出现一次603228.SH反弹退出：2019-03-08 10:08退出，较P在3月25日的退出少亏32.93元；但后续交易和数量一起改变，账户合计反而比P少519.96元。该局部改善不能当作整体优化。',
      '', '|增量比较|成本|共同原盈利交易变化|共同原亏损交易变化|账户总差额|', '|---|---:|---:|---:|---:|']
    for k,a in incremental.items():
        label,cost=k.rsplit('_',1);g=a['matched_original_groups']
        lines.append(f"|{label}|{cost}|{g['winner']['pnl_change']:+.2f}元|{g['loser']['pnl_change']:+.2f}元|{a['total_delta']:+.2f}元|")
    lines+=['','P正常成本与原E1保持完全相同买入的交易中，实际改变退出结果的案例如下。它既有正向也有负向，不能只保留事后成功的股票。',
      '', '|股票|原E1退出|P退出|原净利润|P净利润|变化|', '|---|---|---|---:|---:|---:|']
    for r in attr['P_1.0']['matched']:
        if abs(r['delta'])>.005:lines.append(f"|{r['symbol']}|{r['old_sell']}|{r['new_sell']}|{r['old_pnl']:.2f}元|{r['new_pnl']:.2f}元|{r['delta']:+.2f}元|")
    lines+=['','|方案|成本|2018|2019|2020|原盈利匹配交易损益变化|原亏损匹配交易损益变化|','|---|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        a=attr[f"{r['mode']}_{r['cost']}"]['matched_original_groups']
        lines.append(f"|{r['mode']}|{r['cost']}|{r['yearly']['2018']:.2f}%|{r['yearly']['2019']:.2f}%|{r['yearly']['2020']:.2f}%|{a['winner']['pnl_change']:+.2f}元|{a['loser']['pnl_change']:+.2f}元|")
    lines+=['','## 全部原交易的高低点对照','',
      '按最终净盈亏事后分组，用来观察重叠，不将最终输赢作为选股输入。这里高低点限于原实际持仓窗口，包含买入当日不能卖出的T+1锁定价格，且不含卖出分钟；不是完整未来波段，也不代表可成交的最大利润。',
      '', '|原交易分组|笔数|最终净损益|平均最高浮动价格收益|平均最低浮动价格收益|曾高于买价|曾低于买价|', '|---|---:|---:|---:|---:|---:|---:|']
    for label,g in extrema_groups.items():lines.append(f"|{'最终盈利' if label=='winner' else '最终亏损'}|{g['count']}|{g['net_profit']:+.2f}元|{g['mean_peak_gain_pct']:.2f}%|{g['mean_trough_return_pct']:.2f}%|{g['ever_positive_price_count']}|{g['ever_negative_price_count']}|")
    lines+=['','逐笔最高/最低出现时间、幅度和最低点之后反弹情况见original_trade_extrema.json。浮动价格收益按原复权因子比较，最终净损益来自成交账本，两者不混作同一收益口径。','',
      '严格匹配股票、买入时间、价格和数量；买点改变后很多交易不可匹配。新增/移除交易、分红和未实现损益另存trade_attribution.json，所有贡献之和核对为权益差额。表中已匹配盈亏贡献不是完整策略差额。',
      '回踩买入是否更便宜另按同一股票、同一买入日期比较实际成交价，见entry_price_comparison.json；只限共同交易，不能忽略被放弃或新增的股票。',
      '', '## 方法与边界','',
      '高低点倒推可以帮助提出信号，但不能确保事前识别最高/最低。数据中包括成功、失败、假顶部和未恢复的反弹；事后最高价包络只是机会标尺。交易规则源代码没有读取case_002317.json或original_trade_extrema.json等标签。',
      '365项模块测试通过；新增6项覆盖已完成分钟峰值、盈利门槛、反弹预警初始化/解除、原风险优先、回踩需晚于首次确认。10条完整账户共1752000个分钟点，现金和交易贡献核对通过；不称新RQAlpha独立复验。',
      '全部历史已反复用于研究，尚无未见验证。停牌、涨跌停、T+1、整手、原费用、分钟成交及账户风险约束保留。补充分钟与原日线量额核对，平台原研究代码恢复并逐字符校验，审计见本目录。']
    lines+=['','新增持仓600919.SH的2020年12月17日零现金记录，经中国证券报刊登的江苏银行2020-073公告核实为配股除权，股权登记日12月8日、10配3、认购价4.59元。研究输入将其从现金分红中分离，6月24日每股0.278元现金分红重新通过双接口核对。保留原实际持仓跨未支持公司行动登记日即停止的检查；所有完成路径均未触发配股权益处理，未假定免费获得配股、未剔除此股票、未修改旧证据。见corporate_resolution.json。']
    (OUT/'RESULT.md').write_text('\n'.join(lines)+'\n',encoding='utf8');print(json.dumps(dict(rows=rows,decisions=decisions),ensure_ascii=False))
if __name__=='__main__':main()
