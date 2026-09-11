"""Date-balanced forward-outcome diagnostics for every E1 eligible signal."""
import json,math
import numpy as np
from pathlib import Path
from collections import defaultdict,Counter
from recovery_research import prepare
from exit_extension_research import read_export
from simple_history_replay import merge_cache
import simple_strategy_rules as base

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/e1_conditions'

def save(name,value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')

def groups(row,benchmark):
    distance=row['close']/row['ma20']-1
    return dict(ma20='near5' if distance<=.05+1e-12 else 'mid5to10' if distance<=.10+1e-12 else 'far10',
       volume='moderate' if row['volume_ratio']<=2 else 'high',
       volatility='low2' if row['atr20_raw']/row['raw_close']<=.02 else 'high2',
       breakout='near2' if row['close']/row['prior_breakout_close']-1<=.02+1e-12 else 'far2',
       market='moderate5' if benchmark['ret20']<=.05 else 'hot5')

def forward(history,calendar,index,horizon):
    if index+horizon>=len(calendar):return None,'sample_end'
    dates=calendar[index+1:index+horizon+1]
    rows=[history.get(d) for d in dates]
    if any(r is None for r in rows):return None,'missing_interval'
    if any(any(not isinstance(r.get(k),(int,float)) or not math.isfinite(r[k]) or r[k]<=0 for k in ('open','close','factor')) for r in rows):return None,'invalid_price'
    return (rows[-1]['close']*rows[-1]['factor']/(rows[0]['open']*rows[0]['factor'])-1)*100,None

def aggregate(observations,start,end,horizon,field=None,value=None):
    dates=defaultdict(list)
    for r in observations:
        if start<=r['asof']<=end and r['exit_days'][str(horizon)] is not None and r['exit_days'][str(horizon)]<=end and r['outcomes'][str(horizon)] is not None:dates[r['asof']].append(r)
    outcomes=[];deltas=[];count=0;win=0
    for day,rows in sorted(dates.items()):
        selected=[r for r in rows if field is None or r['groups'][field]==value]
        if not selected:continue
        a=[r['outcomes'][str(horizon)] for r in selected];allmean=sum(r['outcomes'][str(horizon)] for r in rows)/len(rows)
        m=sum(a)/len(a);outcomes.append(m);deltas.append(m-allmean);count+=len(a);win+=sum(v>0 for v in a)
    return dict(days=len(outcomes),signals=count,mean_date_balanced_pct=sum(outcomes)/len(outcomes) if outcomes else None,
                excess_same_date_all_candidates_pp=sum(deltas)/len(deltas) if deltas else None,
                raw_signal_win_pct=win/count*100 if count else None)

def study(cache,bundle):
    calendar=bundle['calendar'];observations=[];missing=Counter()
    for i,day in enumerate(bundle['days']):
        prev=day['previous_close'];b=prev['benchmark'];route=base.research_regime(b['close'],b['ma20'],b['ma60'])
        for row in prev['stocks']:
            if not base.select_signal(row,route) or not base.needs_minutes(row,route):continue
            outcomes={};gaps={}
            for h in (5,10,20):
                ret,error=forward(cache.daily.get(row['symbol'],{}),calendar,i,h)
                outcomes[str(h)]=ret
                if error:gaps[str(h)]=error;missing[str(h)+'_'+error]+=1
            observations.append(dict(symbol=row['symbol'],asof=prev['date'],entry_day=day['date'],exit_days={str(h):calendar[i+h] if i+h<len(calendar) else None for h in (5,10,20)},groups=groups(row,b),outcomes=outcomes,gaps=gaps))
    save('signals.json',dict(count=len(observations),missing=dict(missing),signals=observations))
    return summarize(observations)

def summarize(observations):
    summaries=[]
    for field in ('ma20','volume','volatility','breakout','market'):
        for value in sorted({r['groups'][field] for r in observations}):
            periods={}
            for label,start,end in [('discovery','2017-12-29','2019-12-31'),('review2020','2020-01-01','2020-12-31')]:
                periods[label]={str(h):aggregate(observations,start,end,h,field,value) for h in (5,10,20)}
            # Market-only groups have zero same-day difference by construction.
            supported=field!='market' and all(periods[p][str(h)]['days']>=n and periods[p][str(h)]['excess_same_date_all_candidates_pp']>0 for p,n in [('discovery',30),('review2020',15)] for h in (5,10,20))
            summaries.append(dict(field=field,value=value,periods=periods,supported_for_account_test=supported))
    save('group_comparison.json',dict(groups=summaries,market_group_warning='Market groups have no same-date cross-sectional control and cannot be selected by the same excess test.',
         overall={label:{str(h):aggregate(observations,start,end,h) for h in (5,10,20)} for label,start,end in [('discovery','2017-12-29','2019-12-31'),('review2020','2020-01-01','2020-12-31')]}))
    for r in summaries:print(r['field'],r['value'],'supported',r['supported_for_account_test'],[(p,[(h,round(v['excess_same_date_all_candidates_pp'],3) if v['days'] else None,v['days']) for h,v in vals.items()]) for p,vals in r['periods'].items()],flush=True)
    return summaries

def uncertainty(observations):
    rng=np.random.default_rng(20260909);result={}
    for label,start,end in [('discovery','2017-12-29','2019-12-31'),('review2020','2020-01-01','2020-12-31')]:
        result[label]={}
        for h in ('5','10','20'):
            byday=defaultdict(list)
            for r in observations:
                if start<=r['asof']<=end and r['exit_days'][h] and r['exit_days'][h]<=end and r['outcomes'][h] is not None:byday[r['asof']].append(r)
            months=defaultdict(list)
            for day,rows in byday.items():
                selected=[r['outcomes'][h] for r in rows if r['groups']['ma20']=='far10']
                if selected:months[day[:7]].append(float(np.mean(selected)-np.mean([r['outcomes'][h] for r in rows])))
            blocks=list(months.values());means=[]
            for _ in range(2000):
                sampled=[blocks[i] for i in rng.integers(0,len(blocks),len(blocks))]
                means.append(sum(sum(b) for b in sampled)/sum(len(b) for b in sampled))
            result[label][h]=dict(month_blocks=len(blocks),date_count=sum(map(len,blocks)),excess_pp=float(np.mean([v for b in blocks for v in b])),descriptive_month_block_bootstrap_95pct=list(map(float,np.percentile(means,[2.5,97.5]))))
    save('uncertainty.json',dict(seed=20260909,replications=2000,warning='Descriptive block-bootstrap after searching multiple groups; not a confirmatory significance test.',results=result))

def main():
    cache,bundle=prepare()
    for p in sorted((ROOT/'reports/e1_rank_research').glob('minute_export_*.txt')):cache=merge_cache([cache,read_export(p)])
    print('CONDITION_INPUTS_LOADED',flush=True)
    study(cache,bundle)
    uncertainty(json.loads((OUT/'signals.json').read_text(encoding='utf8'))['signals'])

if __name__=='__main__':main()
