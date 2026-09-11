from collections import Counter
from statistics import median
from exit_recovery_research import ROOT,OUT,read,save

def main():
    results=read(OUT/'results.json');summaries=[];details=[]
    for p in sorted(OUT.glob('case_*.json')):
        blob=read(p);case=blob['case'];r=blob['result']
        details.append(dict(cost=case['cost'],mode=case['mode'],symbol=case['symbol'],entry=case['entry'],
            signal=case['signal'],status=r['status'],increment=r.get('increment'),
            decisions=r.get('decisions',[]),fills=r.get('fills',[]),
            dd_pct=r.get('max_daily_drawdown_pct',0)))
    for mode in ('L','LM'):
        for cost in (1.,1.5):
            all_rows=[r for r in results if r['mode']==mode and r['cost']==cost]
            entered=[r for r in all_rows if r['status']=='COMPLETE']
            years={year:dict(n=sum(r['entry'].startswith(year) for r in entered),
                diagnostic_sum_yuan=sum(r['increment'] for r in entered if r['entry'].startswith(year))) for year in ('2019','2020')}
            med=median(r['increment_pct'] for r in entered) if entered else None
            passed=len(entered)>=5 and med>0 and all(y['n']>0 and y['diagnostic_sum_yuan']>=0 for y in years.values()) and not any(r['status']=='BLOCKED' for r in all_rows)
            summaries.append(dict(mode=mode,cost=cost,total=len(all_rows),entered=len(entered),
                statuses=dict(Counter(r['status'] for r in all_rows)),wins=sum(r['increment']>0 for r in entered),
                losses=sum(r['increment']<0 for r in entered),median_increment_pct=med,
                diagnostic_sum_yuan=sum(r['increment'] for r in entered),years=years,passed=passed))
    save('summary.json',summaries)
    eligible=[m for m in ('L','LM') if all(s['passed'] for s in summaries if s['mode']==m)]
    save('decision.json',dict(eligible=eligible,adopted=False,portfolio_test_required=bool(eligible),
        scope='32 isolated cost and rule paths, not 32 independent trades',
        next='Broaden fixed-rule signal sample before tuning; separate entry quality from exit recovery'))
    names={'L':'重新站上原保护价','LM':'站上原保护价且高于10日均线'}
    lines=['# 保护退出后恢复信号研究结果','',
        '2026-09-10。两套预先登记规则均未通过完整组合适配门槛，暂不接入FH。补齐19个股票交易日、4560条分钟行情后，全部32条成本×规则路径完成，无数据阻塞。原始保护退出批次正常7、压力9，互有重叠，不能称16个独立样本。','',
        '## 固定规则与执行','',
        'L：实际退出后20个交易日内，首次收盘从原保护价以下重新站上。LM：同一穿越日还须高于当日10日均线。LM不会在价格始终高于保护价时仅因后来穿过均线补发信号。每笔只尝试一次，次日09:31下意图、09:32按真实分钟撮合。', '',
        '重新入场股数不超过原股数，资金限原案例卖出所得，100股整手、4%前收盘价格上限、25%分钟成交量、手续费滑点、T+1及涨跌停均保留。收盘再次跌回保护价或跌破10日均线安排次日退出，最多持有20日；市场防守继续退出并禁止当天新买。共同终点为原买入日第60个交易日。','',
        '## 扣费后的逐笔增量','',
        '对照为原FH退出后留在现金。表中中位数分母是原案例投入资金，不是FH完整账户收益；没有把逐笔重入收益加进原FH净值。', '',
        '|规则|成本|原案例|实际重入|增加收益|减少收益|增量收益率中位数|',
        '|---|---:|---:|---:|---:|---:|---:|']
    for r in summaries:
        lines.append(f"|{names[r['mode']]}|{r['cost']}|{r['total']}|{r['entered']}|{r['wins']}|{r['losses']}|{r['median_increment_pct']:+.2f}%|")
    lines+=['','32路径合计18条完成重入、8条没有符合条件的信号、6条信号出现但没有买入。这些包含两规则及两成本对同一股票的重复比较。','',
        '## 未买入原因','', '|成本|规则|股票|原因|','|---|---|---|---|']
    for r in details:
        if r['status']=='NO_FILL':lines.append(f"|{r['cost']}|{r['mode']}|{r['symbol']}|{', '.join(d['reason'] for d in r['decisions'])}|")
    lines+=['', '中国平安原案例仅100股，按照本轮卖出资金独立使用和4%委托预留条件，不足以重新委托100股。这不能推论完整账户没有可用资金；完整组合资金共享可能改变结果。本轮没有为了制造成交借用其他案例资金。','',
        '## 年份与实例','',
        '四组2019年实际重入的逐笔增量之和均为负，2020年均为正。这个相加仅作年度方向诊断，不能当作组合收益；说明改善依赖少数行情与股票。', '',
        '|成本|规则|股票|重新入场净增量|卖出触发记录|','|---|---|---|---:|---|']
    for r in details:
        if r['status']=='COMPLETE':
            lines.append(f"|{r['cost']}|{r['mode']}|{r['symbol']}|{r['increment']:+.2f}元|{', '.join(d['reason'] for d in r['decisions'])}|")
    lines+=['','## 决定与后续','',
        'L在两档成本的实际重入增量中位数均为负；LM正常仅4笔重入、压力档中位数为负。两方案均不满足每档至少5笔、中位增量为正且两个年份方向不负的事前门槛。当前不进行完整组合接入，不推出新策略收益率。', '',
        '下一步应扩大同一固定定义的保护退出与恢复案例，检查恢复后是否有持续趋势优势；不要继续围绕这7/9笔调整均线天数、等待天数和价格阈值。既有2018—2020反复使用，后续时间段须标注历史研究暴露，不能伪称全项目盲测。进一步同时用同日起同期宽基比较入场质量，判断究竟是股票恢复信号有优势，还是恰逢市场反弹。', '',
        '## 验证边界','',
        '4项定向测试覆盖未来价格不改变历史首信号、未穿越不重复发信号、除息价与均线桥接、次分钟成交及T+1。逐笔现金独立核账，平台原代码保存后重新加载逐字符核对通过。原FH与实盘规则未改变。本轮为固定卖出资金的独立案例回放，并未验证组合资金竞争、完整账户回撤或实盘收益。']
    (OUT/'RESULT.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(summaries)

if __name__=='__main__':main()
