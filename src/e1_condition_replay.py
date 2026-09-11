"""Account test of one diagnostic-selected E1 condition; no live entrypoint."""
import json,time
from exit_research import ExitRules
from recovery_research import prepare,check_supplement
from exit_extension_research import read_export,OUT as PRIOR
from simple_history_replay import merge_cache
from research_portfolio import run_bundle
from simple_minute_cache import MissingMinutes
from s2_strategy_rules import Policy
from e1_condition_study import OUT,ROOT,save,groups
import simple_strategy_rules as base

class ConditionRules(ExitRules):
    def __init__(self):super().__init__('E1')
    def select_signal(self,row,route,policy=Policy()):
        return base.select_signal(row,route,policy) and row['close']/row['ma20']-1>.10+1e-12

def main():
    selected=json.loads((OUT/'group_comparison.json').read_text(encoding='utf8'))
    qualifying=[(r['field'],r['value']) for r in selected['groups'] if r['supported_for_account_test']]
    if qualifying!=[('ma20','far10')]:raise ValueError('diagnostic decision changed; review protocol')
    cache,bundle=prepare()
    for p in sorted((ROOT/'reports/e1_rank_research').glob('minute_export_*.txt')):cache=merge_cache([cache,read_export(p)])
    loaded=set()
    def supplements():
        nonlocal cache,loaded
        new=set(OUT.glob('minute_export_*.txt'))-loaded
        for p in sorted(new):
            extra=read_export(p);check_supplement(extra,cache);cache=merge_cache([cache,extra])
        loaded|=new
    supplements();print('CONDITION_REPLAY_READY',flush=True)
    statuses=[]
    for cost in (1.,1.5):
        while True:
            try:
                result=run_bundle(bundle,Policy(cost_multiplier=cost),rules=ConditionRules(),minute_loader=cache.load)
                save(f'ma20_far10_cost{cost}.json',result)
                row=dict(cost=cost,status='COMPLETED',metrics=result['metrics'],final=result['final'],fills=len(result['fills']))
            except MissingMinutes as e:
                save('missing_minutes.json',e.requests);print('AWAIT_CONDITION_MINUTES '+json.dumps(e.requests),flush=True)
                while not set(OUT.glob('minute_export_*.txt'))-loaded:time.sleep(1)
                supplements();continue
            except ValueError as e:row=dict(cost=cost,status='BLOCKED',error=str(e))
            statuses.append(row);save('run_status.json',statuses);print(json.dumps(row,ensure_ascii=False),flush=True);break
    save('missing_minutes.json',[])

if __name__=='__main__':main()
