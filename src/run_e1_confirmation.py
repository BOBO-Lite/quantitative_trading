"""Run all prespecified confirmation paths, batching actual data gaps."""
import json,time,hashlib
from pathlib import Path
from recovery_research import prepare,check_supplement
from exit_extension_research import read_export
from simple_history_replay import merge_cache
from simple_minute_cache import MissingMinutes
from research_portfolio import run_bundle
from s2_strategy_rules import Policy
from e1_confirmation import ConfirmationRules,ConfirmationLoader,MODES
from report_e1_asymmetric import decomposition

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/e1_confirmation'
def save(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')

def main():
    cache,bundle=prepare()
    import e1_turning_research as prev
    prev.OUT=OUT;bundle=prev.resolve_known_rights_event(bundle)
    for folder in ('e1_rank_research','e1_conditions','e1_loss_signals','e1_asymmetric','e1_turning'):
        for p in sorted((ROOT/'reports'/folder).glob('minute_export_*.txt')):cache=merge_cache([cache,read_export(p)])
    loader=ConfirmationLoader(cache,bundle);loaded=set();statuses=[]
    def extra():
        nonlocal cache
        for p in sorted(set(OUT.glob('minute_export_*.txt'))-loaded):
            c=read_export(p);check_supplement(c,cache);cache=merge_cache([cache,c]);loaded.add(p)
        loader.cache=cache
    extra();print('CONFIRMATION_READY',flush=True)
    from exit_research import ExitRules
    from e1_turning_rules import TurningRules
    parity=[]
    for name,rules,folder in [('E1',ExitRules('E1'),ROOT/'reports/exit_research/extension_2020'),('P',TurningRules('P'),ROOT/'reports/e1_turning')]:
        result=run_bundle(bundle,Policy(),rules=rules,minute_loader=loader.load)
        old=json.loads((folder/f'{name}_cost1.0.json').read_text(encoding='utf8'))
        assert result['fills']==old['fills'],name
        assert abs(result['final']['equity']-old['final']['equity'])<1e-6
        assert max(abs(a['equity']-b['equity']) for a,b in zip(result['minute_curve'],old['minute_curve']))<1e-6
        parity.append(dict(mode=name,minute_points=len(result['minute_curve']),fills_equal=True));print('PARITY '+name,flush=True)
    save('baseline_parity.json',parity)
    wanted=[(m,c) for m in MODES for c in (1.,1.5)]
    while len(statuses)<len(wanted):
        completed={(s['mode'],s['cost']) for s in statuses};missing=set()
        for mode,cost in wanted:
            if (mode,cost) in completed:continue
            rules=ConfirmationRules(mode)
            try:
                result=run_bundle(bundle,Policy(cost_multiplier=cost),rules=rules,minute_loader=loader.load)
                save(f'{mode}_cost{cost}.json',result);save(f'{mode}_cost{cost}_events.json',rules.events)
                assert len(result['daily'])==730 and len(result['minute_curve'])==175200
                cash=30000+sum((-1 if f['buy'] else 1)*f['price']*f['quantity']-f['fees'] for f in result['fills'])+result['final']['dividend_income']-result['final']['dividend_tax']
                assert abs(cash-result['final']['cash'])<1e-6
                row=dict(mode=mode,cost=cost,return_pct=result['metrics']['marked_return']*100,drawdown_pct=result['metrics']['max_minute_close_drawdown']*100,equity=result['final']['equity'],buys=sum(f['buy'] for f in result['fills']),events=len(rules.events),status='COMPLETED')
                statuses.append(row);save('run_status.json',statuses);print(json.dumps(row),flush=True)
            except MissingMinutes as e:missing.update((r['symbol'],r['date']) for r in e.requests)
        if missing:
            req=[dict(symbol=s,date=d) for s,d in sorted(missing)];save('missing_minutes.json',req);print('AWAIT_CONFIRMATION_MINUTES '+json.dumps(req),flush=True)
            while not set(OUT.glob('minute_export_*.txt'))-loaded:time.sleep(1)
            extra()
    save('missing_minutes.json',[])

if __name__=='__main__':main()
