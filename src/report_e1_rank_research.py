"""All preregistered E1 ablations, including unfinished/negative paths."""
import json,hashlib,subprocess,sys,os
from e1_rank_research import OUT,ROOT,PRIOR,write

def main():
    statuses=json.loads((OUT/'run_status.json').read_text(encoding='utf8'))
    rows=[]
    for item in statuses:
        mode,cost=item['mode'],item['cost']
        if item['status']!='COMPLETED':rows.append(item);continue
        r=json.loads((OUT/f'{mode}_cost{cost}.json').read_text(encoding='utf8'))
        base=json.loads((PRIOR/f'E1_cost{cost}.json').read_text(encoding='utf8'))
        if len(r['daily'])!=730 or len(r['minute_curve'])!=175200:raise ValueError('incomplete calendar')
        if mode=='baseline' and r!=base:raise ValueError('baseline differs')
        cash=30000+sum((-1 if f['buy'] else 1)*f['price']*f['quantity']-f['fees'] for f in r['fills'])+r['final']['dividend_income']-r['final']['dividend_tax']
        if abs(cash-r['final']['cash'])>1e-5:raise ValueError('independent final cash mismatch')
        buys={(f['symbol'],f['fill_time']) for f in r['fills'] if f['buy']}
        oldbuys={(f['symbol'],f['fill_time']) for f in base['fills'] if f['buy']}
        prev=30000;years={}
        for y in ('2018','2019','2020'):
            last=[d for d in r['daily'] if d['date'].startswith(y)][-1]['equity'];years[y]=(last/prev-1)*100;prev=last
        rows.append(dict(mode=mode,cost=cost,status='COMPLETED',return_pct=r['metrics']['marked_return']*100,
             max_drawdown_pct=r['metrics']['max_minute_close_drawdown']*100,final_equity=r['final']['equity'],
             delta_yuan=r['final']['equity']-base['final']['equity'],delta_return_pp=(r['metrics']['marked_return']-base['metrics']['marked_return'])*100,
             delta_drawdown_pp=(r['metrics']['max_minute_close_drawdown']-base['metrics']['max_minute_close_drawdown'])*100,
             yearly=years,fills=len(r['fills']),buys=len(buys),common_buy_times=len(buys&oldbuys),
             last_fill=r['fills'][-1]['fill_time'] if r['fills'] else None,fees=r['metrics']['fees_paid']))
    decisions={}
    for mode in ('rs20','stable60','cap2'):
        group=[r for r in rows if r['mode']==mode]
        if len(group)!=2 or any(r['status']!='COMPLETED' for r in group):decisions[mode]='未完成，不能判断全期收益';continue
        if all(r['delta_yuan']>0 for r in group):
            decisions[mode]='样本内正向候选' if all(r['delta_drawdown_pp']<=0 for r in group) else '收益正向但回撤有代价'
        elif all(r['delta_yuan']<=0 for r in group):decisions[mode]='本组收益负向或无改善'
        else:decisions[mode]='成本档方向不一致，效果不稳定'
    write('comparison.json',dict(rows=rows,decisions=decisions))
    names={'baseline':'原E1','rs20':'20日相对强度排序','stable60':'60日趋势稳定性排序','cap2':'追价上限2%'}
    lines=['# E1 排序与追价独立验证','',
           '2018-01-02—2020-12-31，730交易日，3万元连续账户；每组仅改一项，保留E1收盘确认退出、市场防守、持有期限、仓位、暂停和原费用。先完整复现两档原E1。','',
           '|方案|成本|累计收益|最大分钟收盘回撤|期末权益|比同档E1多赚|状态|',
           '|---|---:|---:|---:|---:|---:|---|']
    for r in rows:
        if r['status']=='COMPLETED':lines.append(f"|{names[r['mode']]}|{r['cost']}|{r['return_pct']:.2f}%|{r['max_drawdown_pct']:.2f}%|{r['final_equity']:.2f}|{r['delta_yuan']:+.2f}|完成|")
        else:lines.append(f"|{names[r['mode']]}|{r['cost']}|—|—|—|—|{r['status']}|")
    lines+=['','## 判断','']+[f'- {names[k]}：{v}。' for k,v in decisions.items()]
    lines+=['','## 分年收益与路径','', '|方案|成本|2018|2019|2020|买入次数|与基线相同买入时点|','|---|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        if r['status']=='COMPLETED':lines.append(f"|{names[r['mode']]}|{r['cost']}|{r['yearly']['2018']:.2f}%|{r['yearly']['2019']:.2f}%|{r['yearly']['2020']:.2f}%|{r['buys']}|{r['common_buy_times']}|")
    lines+=['','## 解释和边界','',
           '排序仅决定同一时刻已满足入场条件股票的处理优先级，不提前买尚未确认的高排名股票。候选集合不变，但买入、现金、后续持仓与暂停路径可能改变，所以净值差不是完全相同交易的纯选股收益。',
           'rs20同一天减相同基准收益，不改变20日涨幅排序；stable60使用对数价格回归斜率×R²，不是完整Clenow规则。2%追价同时影响按委托限价计算的初始保护及定仓，公式没有改变，实际风险金额与数量可能不同。',
           '6419个实际候选股票日的排名特征全部可计算，无缺排名回退。真实分钟缺口按实际请求补充，初始失败保留。未完成路径不填造三年收益。',
           '沿用原E1费率假设以隔离改动，尚非历史法定税费修订版。日线特征只截至前一交易日，分钟按下一分钟撮合；有原模型成交量、涨跌停及T+1约束，但不是订单簿队列重放。',
           '4项定向测试验证历史特征不受未来价格影响、原排序保持、排序不删候选、E1退出保护保持；所有完成路径独立买卖现金流+现金分红/红利税与期末现金核对。未另跑新路径RQAlpha，不声称独立预测或框架复验。',
           '2018—2020已经多次用于研究，是样本内比较。正向候选需要未用于选择的区间验证后再考虑使用；本轮不将任何研究规则接入实盘。']
    (OUT/'RESULT.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps(dict(decisions=decisions,rows=rows),ensure_ascii=False))

if __name__=='__main__':main()
