"""Research-only sizing diagnosis; preserves historical execution source."""
import inspect,json,time,hashlib
from pathlib import Path
from collections import Counter
from dataclasses import replace
from math import floor,nextafter
import s2_strategy_rules as s2
import research_portfolio as engine
from e1_reentry_pair import ReentryRules
from e1_confirmation import ConfirmationLoader
from recovery_research import prepare,check_supplement
from exit_extension_research import read_export
from simple_history_replay import merge_cache

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/capital_utilization'
def save(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')

# Pure sizing counterfactual: do not mutate the original module or global settings.
raw_source=inspect.getsource(s2.size_entry).replace('def size_entry(', 'def raw_size(').replace('return qty if qty * price >= 4000 else 0','return qty')
namespace=dict(vars(s2));exec(compile(raw_source,'<research raw sizing>','exec'),namespace)
raw_size=namespace['raw_size']

class AuditRules(ReentryRules):
    def __init__(self,mode,minimum=4000):
        super().__init__(mode);self.minimum=minimum;self.sizing=[]
    def size_entry(self,price,stop,equity,cash,exposure,route,drawdown,count,policy=s2.Policy()):
        original=super().size_entry(price,stop,equity,cash,exposure,route,drawdown,count,policy)
        p=policy;reason=None
        if drawdown>=policy.hard_drawdown:reason='hard_drawdown'
        elif self.reentry_latched and self.trend_days<5:reason='recovery_trend_streak'
        elif route!='trend_breakout':reason='market_defense'
        elif count>=(1 if self.reentry_latched else policy.max_positions):reason='position_count'
        if self.reentry_latched:p=replace(policy,risk_fraction=policy.risk_fraction/2,max_positions=1,reduce_drawdown=nextafter(policy.hard_drawdown,0.))
        q=0 if reason else raw_size(price,stop,equity,cash,exposure,route,drawdown,count,p)
        while q and exposure+q*price>equity*.7+1e-8:q-=100
        if self.reentry_latched and q:
            q=min(q,max(0,floor((equity*.2-exposure)/price/100)*100))
            room=equity*(policy.hard_drawdown-drawdown)/(1-drawdown)*.5
            while q and s2.planned_loss(price,stop,q,policy)>room:q-=100
        if not reason:reason='lot_or_risk_budget_zero' if not q else ('minimum_4000_only' if q*price<4000 else 'sized')
        assert original==(q if q*price>=4000 else 0),(original,q,reason)
        minimum=self.minimum if self.reentry_latched else 4000
        actual=q if q*price>=minimum else 0
        self.sizing.append(dict(day_index=self.day_index,reason=reason,price=price,raw_quantity=q,quantity=actual,equity=equity,drawdown=drawdown,count=count,recovery=self.reentry_latched,trend_days=self.trend_days))
        return actual

def instrumented_runner(minimum=4000):
    source=inspect.getsource(engine.run_bundle)
    source=source.replace('    for index, day in enumerate(days, 1):','    daily_audit=[]\n    for index, day in enumerate(days, 1):')
    source=source.replace("        attempted.clear()","        audit=dict(date=date,route=route,screen_rows=len(rows),selected=sum(bool(select_signal(r,route,policy)) for r in rows),minute_eligible=len(candidates),confirmed=0,size_rejected=0,portfolio_rejected=0,submitted=0)\n        attempted.clear()")
    source=source.replace("                held_risk = sum(","                audit['confirmed']+=1\n                initial_qty=qty\n                if qty==0:audit['size_rejected']+=1\n                held_risk = sum(")
    source=source.replace('                if qty * cap < 4000:',f'                if qty * cap < {minimum}:\n                    if initial_qty:audit[\'portfolio_rejected\']+=1')
    source=source.replace('                oid = broker.submit(symbol, qty,',"                audit['submitted']+=1\n                oid = broker.submit(symbol, qty,")
    source=source.replace('        curves.append(dict(',"        audit['flat_close']=not bool(broker.positions)\n        daily_audit.append(audit)\n        curves.append(dict(")
    source=source.replace("    return dict(status='RESEARCH_PORTFOLIO_REPLAY_ONLY'","    return dict(utilization_audit=daily_audit,status='RESEARCH_PORTFOLIO_REPLAY_ONLY'")
    ns=dict(vars(engine));exec(compile(source,'<research portfolio observer>','exec'),ns)
    (OUT/f'engine_minimum_{minimum}.py').write_text(source,encoding='utf8')
    return ns['run_bundle']

def main():
    OUT.mkdir(exist_ok=True);cache,bundle=prepare()
    import e1_turning_research as prev
    prev.OUT=OUT;bundle=prev.resolve_known_rights_event(bundle)
    for folder in ('e1_rank_research','e1_conditions','e1_loss_signals','e1_asymmetric','e1_turning','e1_confirmation','e1_reentry_pair'):
        for p in sorted((ROOT/'reports'/folder).glob('minute_export_*.txt')):cache=merge_cache([cache,read_export(p)])
    loader=ConfirmationLoader(cache,bundle);run=instrumented_runner();summary=[]
    import sys
    if '--experiment' in sys.argv:
        from simple_minute_cache import MissingMinutes
        run=instrumented_runner(3000);loaded=set();statuses=[]
        if (OUT/'experiment_status.json').exists():statuses=json.loads((OUT/'experiment_status.json').read_text(encoding='utf8'))
        while len(statuses)<4:
            for p in sorted(set(OUT.glob('minute_export_*.txt'))-loaded):
                c=read_export(p);check_supplement(c,cache);cache=merge_cache([cache,c]);loaded.add(p)
            loader.cache=cache;missing=set()
            for mode in ('FH','E1H'):
                for cost in (1.,1.5):
                    if any(s['mode']==mode and s['cost']==cost for s in statuses):continue
                    rules=AuditRules(mode,3000)
                    try:r=run(bundle,s2.Policy(cost_multiplier=cost),rules=rules,minute_loader=loader.load)
                    except MissingMinutes as e:
                        missing.update((x['symbol'],x['date']) for x in e.requests);continue
                    save(f'{mode}_min3000_cost{cost}.json',r);save(f'{mode}_min3000_cost{cost}_sizing.json',rules.sizing)
                    cash=30000+sum((-1 if f['buy'] else 1)*f['quantity']*f['price']-f['fees'] for f in r['fills'])+r['final']['dividend_income']-r['final']['dividend_tax']
                    assert abs(cash-r['final']['cash'])<1e-6 and len(r['daily'])==730 and len(r['minute_curve'])==175200
                    row=dict(mode=mode,cost=cost,return_pct=r['metrics']['marked_return']*100,drawdown_pct=r['metrics']['max_minute_close_drawdown']*100,buys=sum(f['buy'] for f in r['fills']))
                    statuses.append(row);save('experiment_status.json',statuses);print(json.dumps(row),flush=True)
            save('missing_minutes.json',[dict(symbol=s,date=d) for s,d in sorted(missing)])
            if missing:
                print('AWAIT_MINUTES '+json.dumps(sorted(missing)),flush=True)
                while not set(OUT.glob('minute_export_*.txt'))-loaded:time.sleep(1)
        return
    for mode in ('FH','E1H'):
        for cost in (1.,1.5):
            rules=AuditRules(mode);r=run(bundle,s2.Policy(cost_multiplier=cost),rules=rules,minute_loader=loader.load)
            audit=r.pop('utilization_audit');old=json.loads((ROOT/f'reports/e1_reentry_pair/{mode}_cost{cost}.json').read_text(encoding='utf8'))
            assert r==old,'Observer changed account output'
            for a in audit:
                a['buys']=sum(f['buy'] and f['fill_time'].startswith(a['date']) for f in r['fills'])
                a['bucket']='held' if not a['flat_close'] else ('defensive_cash' if a['route']=='defensive_cash' else ('no_selected_signal' if not a['selected'] else ('stop_distance_gate' if not a['minute_eligible'] else ('no_intraday_confirmation_or_engine_block' if not a['confirmed'] else ('sizing_or_portfolio_block' if not a['submitted'] else 'orders_without_close_position')))))
            row=dict(mode=mode,cost=cost,parity=True,flat_buckets=dict(Counter(a['bucket'] for a in audit)),sizing_reasons=dict(Counter(x['reason'] for x in rules.sizing)),flat_sizing_reasons=dict(Counter(x['reason'] for x in rules.sizing if audit[x['day_index']-1]['flat_close'])),return_pct=r['metrics']['marked_return']*100)
            save(f'{mode}_cost{cost}_audit.json',dict(summary=row,days=audit,sizing=rules.sizing));summary.append(row);save('diagnosis.json',summary);print(json.dumps(row),flush=True)
    print('DIAGNOSIS_COMPLETE',flush=True)

if __name__=='__main__':main()
