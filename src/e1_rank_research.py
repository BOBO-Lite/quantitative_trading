"""Isolated E1 ranking/entry ablations, frozen execution and risk semantics."""
import json,math,hashlib
import sys,time
from pathlib import Path
import numpy as np
from exit_research import ExitRules
from recovery_research import prepare
from exit_extension_research import OUT as PRIOR
from research_portfolio import run_bundle
from simple_minute_cache import MissingMinutes
from exit_extension_research import read_export
from simple_history_replay import merge_cache
from s2_strategy_rules import Policy
import simple_strategy_rules as base

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/e1_rank_research'

def write(name,value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')

def trend_features(history,asof,benchmark_ret):
    rows=[v for d,v in sorted(history.items()) if d<=asof]
    if len(rows)<60 or rows[-1]['datetime'][:10]!=asof:raise ValueError('missing rank history')
    close=np.array([r['close']*r['factor'] for r in rows[-60:]],float)
    if not np.isfinite(close).all() or (close<=0).any():raise ValueError('invalid rank prices')
    x=np.arange(60,dtype=float);y=np.log(close);slope,intercept=np.polyfit(x,y,1)
    variance=np.sum((y-y.mean())**2)
    r2=max(0.,min(1.,1-float(np.sum((y-(slope*x+intercept))**2)/variance))) if variance>1e-20 else 0.
    return dict(rs20=float(close[-1]/close[-21]-1-benchmark_ret),stable60=float(slope*r2),r2=r2)

class RankRules(ExitRules):
    def __init__(self,mode,features):
        super().__init__('E1');self.mode=mode;self.features=features
    def sort_key(self,row):
        if self.mode in ('baseline','cap2'):return base.sort_key(row)
        f=self.features.get((row['symbol'],row['date']))
        # Keep identical candidate universe; unknown rank goes after known ranks.
        return (0,-f[self.mode],row['symbol']) if f else (1,*base.sort_key(row))
    def entry_cap(self,row,route):
        return int((row['raw_close']*1.02+1e-10)*100)/100 if self.mode=='cap2' else base.entry_cap(row,route)
    def entry_confirmed(self,signal,minute,route,day_open,day_vwap):
        return base.entry_confirmed(signal,minute,route,day_open,day_vwap) and (self.mode!='cap2' or minute['close']<=self.entry_cap(signal,route))

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    cache,bundle=prepare();loaded=set()
    def supplement():
        nonlocal cache,loaded
        paths=set(OUT.glob('minute_export_*.txt'))-loaded
        for path in sorted(paths):
            extra=read_export(path)
            if not set(extra.daily)<=set(cache.daily):raise ValueError('supplement outside existing symbol scope')
            cache=merge_cache([cache,extra])
        loaded|=paths
    supplement();print('E1_INPUTS_LOADED',flush=True)
    features={};gaps=[];coverage=0
    for day in bundle['days']:
        prev=day['previous_close'];asof=prev['date'];route=base.research_regime(**{k:prev['benchmark'][k] for k in ('close','ma20','ma60')})
        for row in prev['stocks']:
            if not base.select_signal(row,route) or not base.needs_minutes(row,route):continue
            coverage+=1
            try:features[row['symbol'],asof]=trend_features(cache.daily.get(row['symbol'],{}),asof,prev['benchmark']['ret20'])
            except ValueError as e:gaps.append(dict(symbol=row['symbol'],date=asof,error=str(e)))
    write('feature_audit.json',dict(candidate_days=coverage,computed=len(features),missing=gaps,missing_policy='rank after known features, unchanged eligibility',features=[dict(symbol=s,date=d,**v) for (s,d),v in sorted(features.items())]))
    statuses=[]
    for mode in ('baseline','rs20','stable60','cap2'):
        for cost in (1.,1.5):
          while True:
            try:
                r=run_bundle(bundle,Policy(cost_multiplier=cost),rules=RankRules(mode,features),minute_loader=cache.load)
                if mode=='baseline':
                    old=json.loads((PRIOR/f'E1_cost{cost}.json').read_text(encoding='utf8'))
                    if r!=old:raise ValueError('baseline differs from frozen E1')
                write(f'{mode}_cost{cost}.json',r)
                status=dict(mode=mode,cost=cost,status='COMPLETED',metrics=r['metrics'],final=r['final'],fills=len(r['fills']))
            except MissingMinutes as e:
                status=dict(mode=mode,cost=cost,status='MISSING_MINUTES',requests=e.requests)
                if '--interactive' in sys.argv:
                    write('missing_minutes.json',e.requests);print('AWAIT_RANK_MINUTES '+json.dumps(status),flush=True)
                    while not set(OUT.glob('minute_export_*.txt'))-loaded:
                        time.sleep(1)
                    supplement();continue
            except ValueError as e:status=dict(mode=mode,cost=cost,status='BLOCKED',error=str(e))
            statuses.append(status);write('run_status.json',statuses);print(json.dumps(status,ensure_ascii=False),flush=True)
            break

if __name__=='__main__':main()
