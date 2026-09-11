"""Selected conditional early-failure exit, isolated from production strategy."""
import json,time
from e1_loss_signal_study import OUT,ROOT,save
from e1_condition_replay import ConditionRules
from recovery_research import prepare,check_supplement
from exit_extension_research import read_export
from simple_history_replay import merge_cache
from simple_minute_cache import MissingMinutes
from research_portfolio import run_bundle
from s2_strategy_rules import Policy

class EarlyFailureRules(ConditionRules):
    def exit_reason(self,position,minute,route,drawdown,holding_days,close_signal=False,industry_weak=False):
        reason=super().exit_reason(position,minute,route,drawdown,holding_days,close_signal,industry_weak)
        if reason:return reason
        if close_signal and holding_days==3 and minute['close']<position['entry_price'] and not minute['is_paused']:
            return 'third_close_failed_followthrough'
        return None

def main():
    cache,bundle=prepare()
    for folder in ('e1_rank_research','e1_conditions'):
        for p in sorted((ROOT/'reports'/folder).glob('minute_export_*.txt')):cache=merge_cache([cache,read_export(p)])
    loaded=set()
    def extra():
        nonlocal cache
        for p in sorted(set(OUT.glob('minute_export_*.txt'))-loaded):
            c=read_export(p);check_supplement(c,cache);cache=merge_cache([cache,c]);loaded.add(p)
    extra();print('ACCOUNT_READY',flush=True);statuses=[]
    for cost in (1.,1.5):
        while True:
            try:
                result=run_bundle(bundle,Policy(cost_multiplier=cost),rules=EarlyFailureRules(),minute_loader=cache.load)
                save(f'filtered_F3_cost{cost}.json',result)
                row=dict(cost=cost,status='COMPLETED',metrics=result['metrics'],final=result['final'],fills=len(result['fills']))
                statuses.append(row);save('run_status.json',statuses);print(json.dumps(row),flush=True);break
            except MissingMinutes as e:
                save('missing_minutes.json',e.requests);print('AWAIT_LOSS_SIGNAL_MINUTES '+json.dumps(e.requests),flush=True)
                while not set(OUT.glob('minute_export_*.txt'))-loaded:time.sleep(1)
                extra()
    save('missing_minutes.json',[])

if __name__=='__main__':main()
