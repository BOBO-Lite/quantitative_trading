"""RECOVERY1: 独立研究包装，不修改原执行引擎或冻结风险文件。"""
import argparse
import json
from dataclasses import replace
from math import nextafter, floor
from pathlib import Path
import simple_strategy_rules as base
from exit_research import ExitRules
from exit_extension_research import prepare as prior_prepare, read_export, ROOT, OUT as PRIOR
from simple_history_replay import merge_cache
from simple_minute_cache import MissingMinutes
from research_portfolio import run_bundle
from s2_strategy_rules import Policy, planned_loss

OUT=ROOT/'reports/recovery_research'

def check_supplement(supplement,cache):
    if not set(supplement.daily)<=set(cache.daily):raise ValueError('新增股票超出已核验范围')
    covered={s for s,d in json.loads((PRIOR/'requests.json').read_text(encoding='utf8'))['requests']}
    missing=sorted({s for s,d in supplement.minutes if d.startswith('2020') and s not in covered})
    if missing:raise ValueError('2020公司行动范围缺口：'+','.join(missing))

class RecoveryRules(ExitRules):
    def __init__(self,variant):
        super().__init__('E1')
        if variant not in ('R0','R1','R2'):raise ValueError('未登记研究版本')
        self.mode=variant
        self.day_index=0
        self.trend_days=0
        self.pause_day=None
        self.events=[]
        self.recovery_reported=False

    def research_regime(self,*args):
        route=base.research_regime(*args)
        self.day_index+=1
        self.trend_days=self.trend_days+1 if route=='trend_breakout' else 0
        return route

    def exit_reason(self,position,minute,route,drawdown,holding_days,close_signal=False,industry_weak=False):
        if self.mode=='R2' and route=='defensive_cash':route='trend_breakout'
        return super().exit_reason(position,minute,route,drawdown,holding_days,close_signal,industry_weak)

    def size_entry(self,price,stop,equity,cash,exposure,route,drawdown,count,policy=Policy()):
        if self.mode!='R1':return base.size_entry(price,stop,equity,cash,exposure,route,drawdown,count,policy)
        if drawdown < policy.reduce_drawdown:
            if self.pause_day is not None:self.events.append(dict(day_index=self.day_index,event='normal_risk_restored',drawdown=drawdown))
            self.pause_day=None;self.recovery_reported=False
            return base.size_entry(price,stop,equity,cash,exposure,route,drawdown,count,policy)
        if drawdown>=policy.hard_drawdown:return 0
        if self.pause_day is None:
            self.pause_day=self.day_index
            self.events.append(dict(day_index=self.day_index,event='entry_pause',drawdown=drawdown))
        if self.day_index-self.pause_day<20 or self.trend_days<5 or route!='trend_breakout' or count:
            return 0
        recovery_policy=replace(policy,risk_fraction=policy.risk_fraction/2,max_positions=1,
                                reduce_drawdown=nextafter(policy.hard_drawdown,0.))
        qty=base.size_entry(price,stop,equity,cash,exposure,route,drawdown,count,recovery_policy)
        qty=min(qty,max(0,floor((equity*.2-exposure)/price/100)*100))
        room=equity*(policy.hard_drawdown-drawdown)/(1-drawdown)*.5
        while qty and planned_loss(price,stop,qty,policy)>room:qty-=100
        if qty*price<4000:return 0
        if not self.recovery_reported:
            self.events.append(dict(day_index=self.day_index,event='recovery_order_size_allowed',drawdown=drawdown,quantity=qty,planned_loss=planned_loss(price,stop,qty,policy),remaining_risk_budget=room))
            self.recovery_reported=True
        return qty

def prepare():
    cache,bundle=prior_prepare()
    for folder in (ROOT/'reports/entry_research',OUT):
        for path in sorted(folder.glob('minute_export_*.txt')):
            supplement=read_export(path)
            check_supplement(supplement,cache)
            cache=merge_cache([cache,supplement])
    return cache,bundle

def main():
    p=argparse.ArgumentParser();p.add_argument('--interactive',action='store_true');p.add_argument('--variants',nargs='+',default=['R0','R1','R2'],choices=['R0','R1','R2']);a=p.parse_args()
    cache,bundle=prepare();loaded=set(OUT.glob('minute_export_*.txt'));statuses=[];missing=[]
    print('INPUTS_VERIFIED',flush=True)
    for variant in a.variants:
        for cost in (1.,1.5):
            while True:
                rules=RecoveryRules(variant)
                try:
                    result=run_bundle(bundle,Policy(cost_multiplier=cost),rules=rules,minute_loader=cache.load)
                    if variant=='R0' and result!=json.loads((PRIOR/f'E1_cost{cost}.json').read_text(encoding='utf8')):
                        raise ValueError('R0与已验收E1完整结果不一致')
                    (OUT/f'{variant}_cost{cost}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
                    events=[dict(e,date=bundle['calendar'][e['day_index']]) for e in rules.events]
                    (OUT/f'{variant}_cost{cost}_events.json').write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf8')
                    row=dict(variant=variant,cost=cost,status='COMPLETED',metrics=result['metrics'],final=result['final'],fills=len(result['fills']))
                except MissingMinutes as exc:
                    if a.interactive:
                        (OUT/'missing_minutes.json').write_text(json.dumps(exc.requests,ensure_ascii=False,indent=2),encoding='utf8')
                        print('AWAIT_MINUTES '+json.dumps(exc.requests,ensure_ascii=False),flush=True)
                        if input().strip()!='continue':raise ValueError('未完成路径已停止')
                        new=set(OUT.glob('minute_export_*.txt'))-loaded
                        if not new:raise ValueError('没有新增真实行情')
                        for path in sorted(new):
                            supplement=read_export(path)
                            check_supplement(supplement,cache)
                            cache=merge_cache([cache,supplement])
                        loaded |= new
                        continue
                    missing.extend(exc.requests);row=dict(variant=variant,cost=cost,status='MISSING_MINUTES',requests=exc.requests)
                except ValueError as exc:row=dict(variant=variant,cost=cost,status='BLOCKED_REPLAY',error=str(exc))
                statuses.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
                (OUT/'run_status.json').write_text(json.dumps(statuses,ensure_ascii=False,indent=2),encoding='utf8')
                break
    (OUT/'missing_minutes.json').write_text(json.dumps(missing,ensure_ascii=False,indent=2),encoding='utf8')

if __name__=='__main__':main()
