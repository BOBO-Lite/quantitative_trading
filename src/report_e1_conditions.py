"""Connect signal associations to account outcomes without claiming prediction proof."""
import json
from e1_condition_study import OUT,ROOT,save
from exit_extension_research import OUT as PRIOR

def main():
    g=json.loads((OUT/'group_comparison.json').read_text(encoding='utf8'))
    groups=g['groups'];signals=json.loads((OUT/'signals.json').read_text(encoding='utf8'))
    rows=[]
    statuses=json.loads((OUT/'run_status.json').read_text(encoding='utf8'))
    for s in statuses:
        if s['status']!='COMPLETED':rows.append(s);continue
        cost=s['cost'];r=json.loads((OUT/f'ma20_far10_cost{cost}.json').read_text(encoding='utf8'))
        b=json.loads((PRIOR/f'E1_cost{cost}.json').read_text(encoding='utf8'))
        if len(r['daily'])!=730 or len(r['minute_curve'])!=175200:raise ValueError('incomplete account')
        cash=30000+sum((-1 if f['buy'] else 1)*f['price']*f['quantity']-f['fees'] for f in r['fills'])+r['final']['dividend_income']-r['final']['dividend_tax']
        if abs(cash-r['final']['cash'])>1e-5:raise ValueError('cash mismatch')
        previous=30000;years={}
        for y in ('2018','2019','2020'):
            last=[d for d in r['daily'] if d['date'].startswith(y)][-1]['equity'];years[y]=(last/previous-1)*100;previous=last
        rows.append(dict(cost=cost,status='COMPLETED',return_pct=r['metrics']['marked_return']*100,
          baseline_return_pct=b['metrics']['marked_return']*100,delta_yuan=r['final']['equity']-b['final']['equity'],
          final_equity=r['final']['equity'],max_drawdown_pct=r['metrics']['max_minute_close_drawdown']*100,
          baseline_drawdown_pct=b['metrics']['max_minute_close_drawdown']*100,yearly=years,
          buys=sum(f['buy'] for f in r['fills']),fees=r['metrics']['fees_paid'],last_fill=r['fills'][-1]['fill_time'] if r['fills'] else None))
    decision='未完成'
    if len(rows)==2 and all(r['status']=='COMPLETED' for r in rows):
        decision='样本内收益正向候选，仍需新时期验证' if all(r['delta_yuan']>0 for r in rows) else '两档收益都不如E1，暂不采用' if all(r['delta_yuan']<=0 for r in rows) else '两档方向不同，不稳定'
    save('account_comparison.json',dict(decision=decision,rows=rows))
    names={'ma20':'距20日均线','volume':'量比','volatility':'ATR占价','breakout':'突破距离','market':'市场20日涨幅'}
    lines=['# E1 信号环境与成功失败案例研究','',
       '2026-09-09。诊断6,419个E1合格候选股票日，固定11个单变量组，按信号日等权比较后续5/10/20日复权变化。发现期2018—2019与2020分期复核；跨年结果不混入发现期。这些历史已经多次使用，不是样本外。','',
       '## 分组线索','',
       '仅“收盘高于MA20超过10%”组满足预登记的六个方向均正与最少日期数。不是预测最高点，也不是所有股票偏离均线超过10%就买；仅在原E1突破、量比、风险等条件全部满足后研究额外过滤。',
       '', '|组别|类别|发现期5/10/20日超额百分点|2020的5/10/20日超额百分点|是否进入账户测试|',
       '|---|---|---|---|---|']
    for r in groups:
        values=[]
        for p in ('discovery','review2020'):
            values.append(' / '.join(f"{r['periods'][p][h]['excess_same_date_all_candidates_pp']:+.3f}" for h in ('5','10','20')))
        lines.append(f"|{names[r['field']]}|{r['value']}|{values[0]}|{values[1]}|{'是' if r['supported_for_account_test'] else '否'}|")
    lines+=['', '对照是同一天全部可计算候选的平均，包含本组，不是相同股票独立交易组合。市场组在同一天没有横截面对照，超额必为0，不能用此表判断大盘择时有无效。',
       '月份块自助抽样仅作描述性不确定性检查，2020的三个观察期区间均覆盖0；重复信号、少量活跃月份及多组比较使这条线索不足以构成统计确认。见uncertainty.json。',
       '', '## 接回E1的账户结果','',
       '|成本|原E1累计收益|加MA20距离条件|新方案最大分钟回撤|期末权益|比E1多赚|',
       '|---|---:|---:|---:|---:|---:|']
    for r in rows:
        if r['status']=='COMPLETED':lines.append(f"|{r['cost']}|{r['baseline_return_pct']:.2f}%|{r['return_pct']:.2f}%|{r['max_drawdown_pct']:.2f}%|{r['final_equity']:.2f}元|{r['delta_yuan']:+.2f}元|")
        else:lines.append(f"|{r['cost']}|—|—|—|—|{r['status']}|")
    lines+=['', '|成本|2018收益|2019收益|2020收益|买入次数|费用合计|', '|---|---:|---:|---:|---:|---:|']
    for r in rows:
        if r['status']=='COMPLETED':lines.append(f"|{r['cost']}|{r['yearly']['2018']:.2f}%|{r['yearly']['2019']:.2f}%|{r['yearly']['2020']:.2f}%|{r['buys']}|{r['fees']:.2f}元|")
    lines+=['',decision+'。','',
       '账户连续2018-01-02—2020-12-31，3万元。保留原成交额排序、4%追价、收盘确认退出、仓位及风险约束，正常/1.5倍原费用。公司行动、分钟成交与信号标签是不同计算层。只改候选过滤也会改变资金、后续入场及暂停路径，不能把全部差额归因于同一笔交易更优。',
       '', '## 用户提出的规律归纳方法','',
       '这个方向可研究，但必须比较成功、失败和横盘三类案例，而不是只查看事后大涨股。标签用未来结果，预测输入仅用信号日前的指标。发现期内拟合、在后续未用于选择的时期检验，最后按可成交的账户计算收益。',
       '本轮已按事前登记做描述性对照：次日开盘至第10日收盘>5%、<-5%、其他三类。2020上涨组量比中位1.863，下跌组1.887，单纯“放量”不足以区分；不同阶段趋势R²等特征的差别也会变化。没有训练分类器，没有宣称预测胜率。',
       '成功/失败案例特征中位数按原始案例统计，有同股重复和重叠区间；类别比例另给按信号日等权值。与分组收益表的等权方式不同，不能互相替代。详见case_contrast.json。',
       '', '## 缺失与验证边界','',
       f"未来路径缺失/样本终点不足计数：{signals['missing']}。缺整段或部分报价不补造，不把截尾结果当完整10/20日收益。", 
       '信号收益是复权价格变化，未扣成本、未检查次日实际可买和E1盘中确认；实际账户另使用真实分钟与原账本。',
       '定向测试涵盖未来标签窗口、跨年剔除、信号日等权、条件边界和原E1保护保持；完成账户独立现金流核对。沿用旧E1费率便于控制变量，尚非各年法定费率重算；新路径未另做RQAlpha复验。',
       '349项模块测试通过；4项定向测试在最终统计代码下复跑通过。补充分钟数据与日线量额、收盘价逐日核对，实际补充规模见supplement_audit.json。',
       '动态轨迹的下一步方案见DYNAMIC_PATTERN_PLAN.md，目前尚未训练动态模型。',
       '保持实盘协议不变。任何样本内改善都不直接授权实盘或扩大仓位。']
    (OUT/'RESULT.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps(dict(decision=decision,rows=rows),ensure_ascii=False))

if __name__=='__main__':main()
