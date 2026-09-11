"""固定全部E0买入时点/数量的隔离交易对照，不是组合收益。"""
import json,copy
from statistics import mean,median
from exit_research import prepare,OUT,ExitRules
from report_exit_research import roundtrips
from research_portfolio import run_bundle
from simple_minute_cache import MissingMinutes
from s2_strategy_rules import Policy

class OneEntryRules(ExitRules):
    def __init__(self,variant,entry):super().__init__(variant);self.entry=entry
    def entry_confirmed(self,signal,minute,route,day_open,day_vwap):
        return minute['datetime']==self.entry['intent_time'] and signal['symbol']==self.entry['symbol']
    def size_entry(self,*args,**kwargs):return self.entry['quantity']

def signature(fills):
    return [{k:f[k] for k in ('symbol','buy','fill_time','price','quantity','fees')} for f in fills]

def main():
    cache,bundle=prepare();calendar=bundle['calendar'];indices={d:i for i,d in enumerate(calendar)};rows=[];missing=[]
    for cost in (1.,1.5):
        baseline=json.loads((OUT/f'E0_cost{cost}.json').read_text(encoding='utf8'))
        trades,_=roundtrips(baseline);equities={r['datetime']:r['equity'] for r in baseline['minute_curve']}
        entries={(f['symbol'],f['fill_time']):f for f in baseline['fills'] if f['buy']}
        for t in trades:
            entry=entries[t['symbol'],t['entry_time']];start=indices[entry['fill_time'][:10]];stop=min(len(calendar),start+50)
            one=copy.deepcopy({k:v for k,v in bundle.items() if k not in ('days','calendar')})
            one['initial_cash']=equities[entry['intent_time']];one['record_minute_curve']=False;one['calendar']=calendar[start-1:stop]
            # 隔离账户在入场日现金起步，之前已除息事件没有任何资格或应收。
            # 仍保留入场日除息事件，由原引擎以登记日前无持仓初始化零权利。
            one['corporate_events']=[e for e in one['corporate_events'] if e['symbol']==entry['symbol'] and e['ex_date']>=calendar[start]]
            one['days']=copy.deepcopy(bundle['days'][start-1:stop-1])
            for i,day in enumerate(one['days']):
                day['previous_close']['stocks']=[r for r in day['previous_close']['stocks'] if i==0 and r['symbol']==entry['symbol']]
            row=dict(cost=cost,symbol=t['symbol'],entry_time=t['entry_time'],quantity=entry['quantity'],variants={})
            for variant in ('E0','E1','E2'):
                try:
                    r=run_bundle(one,Policy(cost_multiplier=cost),rules=OneEntryRules(variant,entry),minute_loader=cache.load)
                    if not r['fills'] or signature(r['fills'][:1])!=signature([entry]):raise ValueError('固定入场未复现')
                    if variant=='E0' and signature(r['fills'])!=signature([entry]+t['exit_fills']):raise ValueError('E0隔离交易未复现原退出')
                    row['variants'][variant]=dict(status='CENSORED_OPEN' if r['positions'] else 'CLOSED',net_pnl=r['final']['equity']-one['initial_cash'],fills=r['fills'],final=r['final'])
                except MissingMinutes as e:
                    missing+=e.requests;row['variants'][variant]=dict(status='MISSING_MINUTES',requests=e.requests)
                except ValueError as e:row['variants'][variant]=dict(status='INVALID_COMPARISON',error=str(e))
            rows.append(row)
    summary=[]
    for cost in (1.,1.5):
        for variant in ('E1','E2'):
            subset=[r for r in rows if r['cost']==cost]
            valid=[r for r in subset if r['variants']['E0']['status']=='CLOSED' and r['variants'][variant]['status']=='CLOSED']
            diffs=[r['variants'][variant]['net_pnl']-r['variants']['E0']['net_pnl'] for r in valid]
            summary.append(dict(cost=cost,variant=variant,total=len(subset),paired_closed=len(valid),improved=sum(x>1e-6 for x in diffs),worse=sum(x< -1e-6 for x in diffs),same=sum(abs(x)<=1e-6 for x in diffs),mean_pnl_difference=mean(diffs) if diffs else None,median_pnl_difference=median(diffs) if diffs else None))
    (OUT/'paired_trades.json').write_text(json.dumps(dict(summary=summary,trades=rows,note='固定E0入场时点数量，隔离账户配对；不可把重叠样本损益相加当作组合收益'),ensure_ascii=False,indent=2),encoding='utf8')
    unique=[dict(symbol=s,date=d) for s,d in sorted({(r['symbol'],r['date']) for r in missing})]
    (OUT/'paired_missing_minutes.json').write_text(json.dumps(unique,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(summary=summary,missing=unique),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
