"""TECH1固定入场规则退出消融；所有输出独立，原规则及实盘不变。"""
import json,sys
from collections import Counter
from pathlib import Path
import simple_strategy_rules as base
from simple_history_replay import load_inputs,BASE
from simple_minute_cache import MissingMinutes,Cache
from import_supermind_minute_probe import decode_packets
from research_portfolio import run_bundle
from s2_strategy_rules import Policy

OUT=BASE.parent/'exit_research'

class ExitRules:
    VERSION=base.VERSION
    uses_industry=False
    def __init__(self,variant):
        if variant not in ('E0','E1','E2'):raise ValueError('未登记退出版本')
        self.variant=variant
    def __getattr__(self,key):return getattr(base,key)
    def exit_reason(self,position,minute,route,drawdown,holding_days,close_signal=False,industry_weak=False):
        if self.variant=='E0':return base.exit_reason(position,minute,route,drawdown,holding_days,close_signal,industry_weak)
        # 只替换保护触发语义，硬回撤/市场防守/最长持有仍按原规则。
        reason=base.exit_reason(position,minute,route,drawdown,holding_days,close_signal,industry_weak)
        if reason!='protective_stop':return reason
        if close_signal and minute['close']<=position['stop']:return 'close_confirmed_stop'
        if close_signal and holding_days>=20:return 'time_exit'
        return None
    def close_protection(self,position,close,ma10,atr20,policy=Policy()):
        result=base.close_protection(position,close,ma10,atr20,policy)
        if self.variant=='E2':result['stop']=max(position['stop'],result['highest_close']-3*atr20)
        return result

def prepare():
    cache,days=load_inputs(2019);folder=BASE/'continuous_2018_2019'
    # 补充数据只增加真实分钟，不改变已核验原日线。
    for path in sorted(OUT.glob('minute_export*.txt')):
        raw=path.read_text(encoding='utf8')
        if 'TECH1_ENTRY_MINUTE_EXPORT_DONE' not in raw:raise ValueError('补充日志缺结束标记')
        packets=decode_packets(raw)
        from ast import parse,Assign,Name,literal_eval
        probe=path.with_name(path.stem.replace('minute_export','minute_probe')+'.py')
        tree=parse(probe.read_text(encoding='utf8'))
        requested=set(next(literal_eval(n.value) for n in tree.body if isinstance(n,Assign) and any(isinstance(t,Name) and t.id=='REQUESTS' for t in n.targets)))
        received={(v['symbol'],v['date']) for k,v in packets.items() if k.startswith('minute_')}
        if requested!=received:raise ValueError('补充分钟包集合不一致')
        supplement=Cache(packets)
        for s,h in supplement.daily.items():
            for d,row in h.items():
                if d in cache.daily.get(s,{}) and cache.daily[s][d]!=row:raise ValueError('补充日线与基线不一致')
        for key,rows in supplement.minutes.items():
            if key in cache.minutes and cache.minutes[key]!=rows:raise ValueError('补充分钟冲突')
            cache.minutes[key]=rows
    events=json.loads((folder/'corporate_events.json').read_text(encoding='utf8'))
    calendar=[d['date'] for d in days];closes=cache.closing_many(calendar[1:],folder/'close_features_cache.json')
    bundle=dict(research_version=base.VERSION,source_kind='VERIFIED_CONTINUOUS_HISTORY',initial_cash=30000.,calendar=calendar,record_minute_curve=True,
        corporate_events=events['cash'],unresolved_corporate_symbols=sorted({r['symbol'] for r in events['unknown']}),unsupported_corporate_events=events['unsupported'],
        days=[dict(date=calendar[i],previous_close=dict(date=calendar[i-1],benchmark=days[i-1]['benchmark'],stocks=days[i-1]['candidates']),close_features=closes[i-1]) for i in range(1,len(calendar))])
    return cache,bundle

def main():
    OUT.mkdir(exist_ok=True);cache,bundle=prepare();statuses=[];missing=[]
    for variant in ('E0','E1','E2'):
        for cost in (1.,1.5):
            try:
                result=run_bundle(bundle,Policy(cost_multiplier=cost),rules=ExitRules(variant),minute_loader=cache.load)
                if variant=='E0':
                    original=json.loads((BASE/'continuous_2018_2019'/f'cost{cost}.json').read_text(encoding='utf8'))
                    if result!=original:raise ValueError('E0与原TECH1完整输出不一致')
                (OUT/f'{variant}_cost{cost}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
                statuses.append(dict(variant=variant,cost=cost,status='COMPLETED',metrics=result['metrics'],fills=len(result['fills']),final=result['final'],exit_reasons=dict(Counter(f['reason'] for f in result['fills'] if not f['buy']))))
            except MissingMinutes as e:
                missing+=e.requests;statuses.append(dict(variant=variant,cost=cost,status='MISSING_MINUTES',requests=e.requests))
            except ValueError as e:statuses.append(dict(variant=variant,cost=cost,status='BLOCKED_REPLAY',error=str(e)))
    unique=[dict(symbol=s,date=d) for s,d in sorted({(r['symbol'],r['date']) for r in missing})]
    (OUT/'missing_minutes.json').write_text(json.dumps(unique,ensure_ascii=False,indent=2),encoding='utf8')
    (OUT/'run_status.json').write_text(json.dumps(statuses,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(statuses,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
