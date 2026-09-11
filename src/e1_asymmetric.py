"""Asymmetric profit/loss management and authorized drawdown recovery research."""
import json,time,argparse
from dataclasses import replace
from math import floor,nextafter
from pathlib import Path
from exit_research import ExitRules
from recovery_research import prepare,check_supplement
from exit_extension_research import read_export
from simple_history_replay import merge_cache
from simple_minute_cache import MissingMinutes
from research_portfolio import run_bundle
from s2_strategy_rules import Policy,planned_loss
import simple_strategy_rules as base

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/e1_asymmetric'
def save(name,value):(OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')

class AsymmetricRules(ExitRules):
    def __init__(self,modes):
        super().__init__('E1');self.modes=set(modes);assert self.modes<=set('RWL')
        self.trend_days=0;self.day_index=0;self.events=[];self.last_recovery_event=None
    def research_regime(self,*args):
        route=base.research_regime(*args);self.day_index+=1
        self.trend_days=self.trend_days+1 if route=='trend_breakout' else 0
        return route
    def size_entry(self,price,stop,equity,cash,exposure,route,drawdown,count,policy=Policy()):
        if 'R' not in self.modes or drawdown<policy.reduce_drawdown:return base.size_entry(price,stop,equity,cash,exposure,route,drawdown,count,policy)
        if drawdown>=policy.hard_drawdown or self.trend_days<5 or route!='trend_breakout' or count:return 0
        p=replace(policy,risk_fraction=policy.risk_fraction/2,max_positions=1,reduce_drawdown=nextafter(policy.hard_drawdown,0.))
        qty=base.size_entry(price,stop,equity,cash,exposure,route,drawdown,count,p)
        qty=min(qty,max(0,floor((equity*.2-exposure)/price/100)*100))
        room=equity*(policy.hard_drawdown-drawdown)/(1-drawdown)*.5
        while qty and planned_loss(price,stop,qty,policy)>room:qty-=100
        if qty*price<4000:return 0
        if self.last_recovery_event!=self.day_index:
            self.events.append(dict(event='recovery_size_allowed',day_index=self.day_index,drawdown=drawdown,quantity=qty,risk=planned_loss(price,stop,qty,policy),room=room));self.last_recovery_event=self.day_index
        return qty
    def close_protection(self,position,close,ma10,atr20,policy=Policy()):
        p=super().close_protection(position,close,ma10,atr20,policy);p['known_ma10']=ma10
        p['known_ma10_stop_reference']=p['stop']
        return p
    def exit_reason(self,position,minute,route,drawdown,holding_days,close_signal=False,industry_weak=False):
        reason=super().exit_reason(position,minute,route,drawdown,holding_days,close_signal,industry_weak)
        # Before today's close update, stop changes only by gross cash dividends.
        # Apply the same bridge to yesterday's raw-price MA10 on an ex-date.
        known_ma10=position.get('known_ma10',float('inf'))+position['stop']-position.get('known_ma10_stop_reference',position['stop'])
        if 'W' in self.modes and reason=='time_exit' and close_signal and holding_days<40 and minute['close']>=position['entry_price']+2*position['initial_r'] and minute['close']>known_ma10:
            self.events.append(dict(event='profitable_time_exit_extended',date=minute['datetime'],entry_date=position['entry_date'],holding_days=holding_days));reason=None
        if reason:return reason
        if 'L' in self.modes and close_signal and holding_days<=5 and not minute['is_paused'] and minute['close']<=position['entry_price']-.5*position['initial_r']:
            self.events.append(dict(event='early_half_r_loss',date=minute['datetime'],entry_date=position['entry_date'],holding_days=holding_days));return 'early_half_r_loss'
        return None

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--extra',choices=['RW']);args=parser.parse_args()
    OUT.mkdir(exist_ok=True);cache,bundle=prepare()
    for folder in ('e1_rank_research','e1_conditions','e1_loss_signals'):
        for p in sorted((ROOT/'reports'/folder).glob('minute_export_*.txt')):cache=merge_cache([cache,read_export(p)])
    loaded=set();statuses=json.loads((OUT/'run_status.json').read_text(encoding='utf8')) if args.extra else []
    def extra():
        nonlocal cache
        for p in sorted(set(OUT.glob('minute_export_*.txt'))-loaded):
            c=read_export(p);check_supplement(c,cache);cache=merge_cache([cache,c]);loaded.add(p)
    extra();print('ASYMMETRIC_READY',flush=True)
    def run(mode):
        for cost in (1.,1.5):
            while True:
                rules=AsymmetricRules(mode)
                try:
                    result=run_bundle(bundle,Policy(cost_multiplier=cost),rules=rules,minute_loader=cache.load)
                    save(f'{mode}_cost{cost}.json',result)
                    save(f'{mode}_cost{cost}_events.json',[dict(e,date=bundle['calendar'][e['day_index']]) if 'day_index' in e else e for e in rules.events])
                    row=dict(mode=mode,cost=cost,status='COMPLETED',metrics=result['metrics'],final=result['final'],fills=len(result['fills']))
                    statuses.append(row);save('run_status.json',statuses);print(json.dumps(row),flush=True);break
                except MissingMinutes as e:
                    save('missing_minutes.json',e.requests);print('AWAIT_ASYMMETRIC_MINUTES '+json.dumps(e.requests),flush=True)
                    while not set(OUT.glob('minute_export_*.txt'))-loaded:time.sleep(1)
                    extra()
    if args.extra:
        assert not any(s['mode']==args.extra for s in statuses),'extra already completed'
        run(args.extra);save('missing_minutes.json',[]);return
    for mode in ('R','W','L'):run(mode)
    supported=[]
    for mode in ('R','W','L'):
        if all(next(s for s in statuses if s['mode']==mode and s['cost']==cost)['final']['equity']>json.loads((ROOT/f'reports/exit_research/extension_2020/E1_cost{cost}.json').read_text(encoding='utf8'))['final']['equity'] for cost in (1.,1.5)):supported.append(mode)
    save('combination_decision.json',dict(positive_single_modes=supported,rule='combine only modes exceeding E1 in both cost paths',unseen_validation=False))
    if len(supported)>1:run(''.join(supported))
    save('missing_minutes.json',[])

if __name__=='__main__':main()
