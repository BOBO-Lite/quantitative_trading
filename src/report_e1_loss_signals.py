"""Report loss-warning research without converting pair deltas into account returns."""
import json,hashlib
from e1_loss_signal_study import ROOT,OUT,save

def main():
    study=json.loads((OUT/'fixed_entry_exits.json').read_text(encoding='utf8'))
    pre=json.loads((OUT/'preentry.json').read_text(encoding='utf8'))
    statuses=json.loads((OUT/'run_status.json').read_text(encoding='utf8'))
    assert len(statuses)==2 and all(s['status']=='COMPLETED' for s in statuses)
    accounts=[]
    for s in statuses:
        cost=s['cost'];r=json.loads((OUT/f'filtered_F3_cost{cost}.json').read_text(encoding='utf8'))
        a=json.loads((ROOT/f'reports/exit_research/extension_2020/E1_cost{cost}.json').read_text(encoding='utf8'))
        b=json.loads((ROOT/f'reports/e1_conditions/ma20_far10_cost{cost}.json').read_text(encoding='utf8'))
        assert len(r['daily'])==730 and len(r['minute_curve'])==175200
        cash=30000+sum((-1 if f['buy'] else 1)*f['price']*f['quantity']-f['fees'] for f in r['fills'])+r['final']['dividend_income']-r['final']['dividend_tax']
        assert abs(cash-r['final']['cash'])<1e-5
        previous=30000.;years={}
        for year in ('2018','2019','2020'):
            end=[x for x in r['daily'] if x['date'].startswith(year)][-1]['equity'];years[year]=(end/previous-1)*100;previous=end
        accounts.append(dict(cost=cost,e1_return_pct=a['metrics']['marked_return']*100,filtered_return_pct=b['metrics']['marked_return']*100,new_return_pct=r['metrics']['marked_return']*100,new_annualized_pct=((r['final']['equity']/30000)**(1/3)-1)*100,max_drawdown_pct=r['metrics']['max_minute_close_drawdown']*100,final_equity=r['final']['equity'],delta_vs_filtered=r['final']['equity']-b['final']['equity'],delta_vs_e1=r['final']['equity']-a['final']['equity'],buys=sum(f['buy'] for f in r['fills']),yearly=years))
    decision='优于过滤版但尚未稳定超过原E1'
    if all(r['delta_vs_e1']>0 for r in accounts):decision='两档样本内收益超过原E1，仅作待验证候选'
    elif all(r['delta_vs_filtered']<=0 for r in accounts):decision='两档均未改善过滤版，不采用'
    elif any(r['delta_vs_filtered']<=0 for r in accounts):decision='成本档方向不一致，不采用'
    save('account_comparison.json',dict(decision=decision,rows=accounts))
    lines=['# 亏损预警、盈利差异与仓位研究','', '2026-09-09；已见2018—2020历史上的探索。标签、固定买入试验、完整账户回测是不同层次，不互相冒充。','',
      '## 买入前：更急的上涨没有自动带来更高成功率','',
      '|原E1事前特征中位数|盈利13笔|亏损25笔|','|---|---:|---:|']
    med=study['summaries']['E1']['entry_medians']
    for key,label in [('ret5_pct','近5日涨幅%'),('prior5_pct','此前5日涨幅%'),('acceleration_pp','两段涨幅差百分点'),('volume5_vs_previous5','近5日/此前5日均量'),('atr5_vs20','5日/20日平均真实波幅')]:
        lines.append(f"|{label}|{med['winner']['features'][key]:.3f}|{med['loser']['features'][key]:.3f}|")
    lines+=['','这只是小样本分布差异，不能用中位数为单只股票判定输赢。全候选另外固定4个条件做同日两组对照。',f"有效候选案例{len(pre['rows'])}个；缺失/剔除：{pre['missing']}。",'',
      '|事前条件|2018—2019的10日收益差百分点|2020收益差百分点|2018—2019跌超5%比例差百分点|2020跌超5%比例差百分点|','|---|---:|---:|---:|---:|']
    names={'decelerating':'近5日比此前5日涨得慢','volume_fading':'近5日均量下降','volatility_expanding':'5日波幅超过20日1.25倍','weak_close':'收盘位于当日区间下半部'}
    for row in pre['contrasts']:
        a=row['periods']['2018_2019'];b=row['periods']['2020']
        lines.append(f"|{names[row['flag']]}|{a['mean_return_difference_pp']:+.3f}|{b['mean_return_difference_pp']:+.3f}|{a['mean_down5_difference_pp']:+.3f}|{b['mean_down5_difference_pp']:+.3f}|")
    lines+=['','同一天必须同时有满足/不满足条件的候选，先组内平均，再按日期平均。不同条件覆盖日期不同，不能直接按表排名。后续收益为次日开盘至第10日收盘复权价格变化，未扣费；跌超5%比例不是实际交易亏损概率。重复和重叠案例不独立，未做确认性统计检验。',
      '四个简单条件都没有形成“两段历史平均收益更低、跌超5%风险更高”的一致预警。涨速变缓反而在两段中平均收益较高、跌超5%比例较低；不能据此反向挑选阈值并直接上线。','',
      '## 买入后：识别到亏损，还要考虑误卖代价','',
      '|原买入集合|早退条件|触发数|原亏损交易损益改善|原盈利交易损益改善|全部差额|','|---|---|---:|---:|---:|---:|']
    for name in ('E1','filtered'):
        for mode in ('F1','F3'):
            r=study['summaries'][name][mode]
            lines.append(f"|{name}|{mode}|{r['trigger_count']}|{r['original_losers_difference']:+.2f}|{r['original_winners_difference']:+.2f}|{r['total_pnl_difference']:+.2f}|")
    lines+=['','F1：买入首日收盘低于买入参考；F3：持有第3个交易日收盘低于参考。两者最早在下一交易日09:32成交。先发生的原退出照旧，原分红/税和分钟撮合约束保留。正数为改善、负数为变差，单位元。',
      '79笔原买卖逐笔复现，两个账户原权益合计核对通过；3种路径共237次逐笔资金核对。卖出资金未重新投资、原买入与数量固定，所以表中差额不是新组合收益。F3只在过滤版中有正向线索，2019/2020分别+378.43/+1164.24元；原E1中为负向，不能推广成所有突破买入三天不涨就卖。','',
      '## 接回完整账户：过滤版加F3','',
      '|成本|原E1三年累计|过滤版三年累计|过滤版+F3三年累计|新方案最大分钟回撤|比原E1多赚|','|---|---:|---:|---:|---:|---:|']
    for r in accounts:lines.append(f"|{r['cost']}|{r['e1_return_pct']:.2f}%|{r['filtered_return_pct']:.2f}%|{r['new_return_pct']:.2f}%|{r['max_drawdown_pct']:.2f}%|{r['delta_vs_e1']:+.2f}元|")
    lines+=['',decision+'。','', '|成本|2018|2019|2020|买入次数|期末权益|','|---|---:|---:|---:|---:|---:|']
    for r in accounts:lines.append(f"|{r['cost']}|{r['yearly']['2018']:.2f}%|{r['yearly']['2019']:.2f}%|{r['yearly']['2020']:.2f}%|{r['buys']}|{r['final_equity']:.2f}元|")
    normal_path=OUT/'normal_account_path_audit.json'
    if normal_path.exists():
        audit=json.loads(normal_path.read_text(encoding='utf8'))
        lines+=['',f"正常成本新账户有{audit['new_buy_times']}次相对过滤版新增买入时点，对应交易净损益{audit['new_entry_trade_pnl']:+.2f}元；{audit['common_buy_times']}次相同买入时点对应净损益{audit['common_entry_trade_pnl']:+.2f}元。2020-01-16触发原15%硬停止。相同买入时点不保证数量、卖点相同；新增交易贡献也不等于纯粹的规则因果效应。"]
    lines+=['','730交易日、3万元、正常和1.5倍原费率。完整账户会改变后续现金、开仓和暂停路径；不能把差额全归为原来几笔交易少亏。两档350400个分钟账户点与最终现金流核对；不称新的RQAlpha独立撮合验证。','',
      '## 低仓位的来源','',
      '原E1日收盘空仓635天：553天为大盘防守；63天为趋势环境且有候选，但日收盘回撤>=12%；其余19天为无候选或未形成最终收盘持仓。原定仓函数在回撤>=12%时直接禁止新开仓，并非仅把单笔仓位减半。这里的交叉分布不是每个盘中拒单原因的唯一归因。',
      '过滤版596个收盘空仓日中558天为市场防守，30天趋势环境下没有过滤后候选，8天有候选但最终空仓。两套均无15%硬停止日。不能把全部空仓说成硬止损锁死，也不能通过扩大单笔仓位解决市场过滤造成的空仓。',
      '仓位优化应独立检验市场允许开仓的环境与回撤恢复机制，不能直接取消防守。此前恢复机制和取消防守的试验结果仍有效，本轮未重写风控或扩大实盘仓位。','',
      '## 机构量化收益','',
      '见INSTITUTIONAL_RETURNS.md及官方网页快照。截至2026-08-31，QMNIX近5/10年年化19.73%/6.54%；AQMIX为14.49%/4.88%。两个公开实例不是行业平均，也不是本项目目标收益承诺。机构使用量化还考虑低相关、多策略组合、基准超额与执行效率。','',
      '## 验证边界','',
      '353项模块测试通过（新增4项：未来特征隔离、第三天收盘触发边界、原防守优先、停牌保护）；数据缺失不填造。补充请求、分钟日线核对、平台恢复和哈希见本目录审计文件。',
      '本轮不训练预测模型，不宣称发现确定亏损信号。正式策略与实盘协议保持不变；历史正向候选仍需未参与选取的新时期复核。']
    (OUT/'RESULT.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps(dict(decision=decision,rows=accounts),ensure_ascii=False))

if __name__=='__main__':main()
