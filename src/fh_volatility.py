"""Research-only entry risk adaptation of inverse-variance sizing."""
import json,hashlib,time
from pathlib import Path
from dataclasses import replace
import numpy as np
import pandas as pd
from e1_reentry_pair import ReentryRules
from s2_strategy_rules import Policy

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/fh_volatility'
def save(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')

def schedule_from_prices(prices):
    s=pd.Series(prices,dtype=float).sort_index();ret=s.pct_change().dropna()
    groups=ret.groupby(ret.index.str[:7])
    rv=groups.apply(lambda x:float(((x-x.mean())**2).sum()))
    monthly=s.groupby(s.index.str[:7]).last().pct_change()
    calibration=pd.period_range('2018-02','2019-12',freq='M').astype(str)
    lag=np.array([rv.loc[str(pd.Period(m)-1)] for m in calibration])
    r=monthly.loc[calibration].to_numpy()
    assert len(r)==23 and np.isfinite(r).all() and (lag>0).all()
    c=float(np.std(r,ddof=1)/np.std(r/lag,ddof=1))
    constant=float(np.minimum(1,c/lag).mean())
    future={m:float(min(1,c/rv.loc[str(pd.Period(m)-1)])) for m in pd.period_range('2020-01','2020-12',freq='M').astype(str)}
    return dict(c=c,constant=constant,monthly=future,calibration_months=list(calibration))

class VolatilityRules(ReentryRules):
    def __init__(self,mode,dates,schedule):
        assert mode in ('BASE','DYNAMIC','CONSTANT')
        super().__init__('FH');self.vol_mode=mode;self.dates=dates;self.schedule=schedule;self.weight=1.;self.sizing=[]
    def research_regime(self,*args):
        route=super().research_regime(*args)
        self.date=self.dates[self.day_index-1]
        self.weight=1. if self.date<'2020-01-01' or self.vol_mode=='BASE' else self.schedule['constant'] if self.vol_mode=='CONSTANT' else self.schedule['monthly'][self.date[:7]]
        return route
    def size_entry(self,price,stop,equity,cash,exposure,route,drawdown,count,policy=Policy()):
        assert 0<self.weight<=1
        p=replace(policy,risk_fraction=policy.risk_fraction*self.weight)
        q=super().size_entry(price,stop,equity,cash,exposure,route,drawdown,count,p)
        self.sizing.append(dict(date=self.date,weight=self.weight,quantity=q,drawdown=drawdown,recovery=self.reentry_latched,equity=equity))
        return q

def main():
    lock=json.loads((OUT/'protocol_lock.json').read_text())
    assert hashlib.sha256((OUT/'PROTOCOL.md').read_bytes()).hexdigest()==lock['sha256']
    prices={}
    for year in (2018,2019,2020):
        data=json.loads((ROOT/f'reports/simple_research/{year}/screen.json').read_text(encoding='utf8'))
        for d in data['days']:
            date=d['date'];close=d['benchmark']['close']
            if date in prices:assert prices[date]==close
            prices[date]=close
    schedule=schedule_from_prices(prices);save('schedule.json',schedule)
    from recovery_research import prepare,check_supplement
    from simple_history_replay import merge_cache
    from exit_extension_research import read_export
    from e1_confirmation import ConfirmationLoader
    from research_portfolio import run_bundle
    from simple_minute_cache import MissingMinutes
    import e1_turning_research as prev
    cache,bundle=prepare();prev.OUT=OUT;bundle=prev.resolve_known_rights_event(bundle)
    for folder in ('e1_rank_research','e1_conditions','e1_loss_signals','e1_asymmetric','e1_turning','e1_confirmation','e1_reentry_pair','capital_utilization'):
        for p in sorted((ROOT/'reports'/folder).glob('minute_export_*.txt')):cache=merge_cache([cache,read_export(p)])
    loader=ConfirmationLoader(cache,bundle);dates=[d['date'] for d in bundle['days']]
    statuses=[];loaded=set()
    if (OUT/'status.json').exists():statuses=json.loads((OUT/'status.json').read_text())
    while len(statuses)<6:
        for p in sorted(set(OUT.glob('minute_export_*.txt'))-loaded):
            c=read_export(p);check_supplement(c,cache);cache=merge_cache([cache,c]);loaded.add(p)
        loader.cache=cache;missing=set()
        for mode in ('BASE','DYNAMIC','CONSTANT'):
            for cost in (1.,1.5):
                if any(x['mode']==mode and x['cost']==cost for x in statuses):continue
                rules=VolatilityRules(mode,dates,schedule)
                try:r=run_bundle(bundle,Policy(cost_multiplier=cost),rules=rules,minute_loader=loader.load)
                except MissingMinutes as e:
                    missing.update((x['symbol'],x['date']) for x in e.requests);continue
                old=json.loads((ROOT/f'reports/e1_reentry_pair/FH_cost{cost}.json').read_text(encoding='utf8'))
                if mode=='BASE':assert r==old,'baseline parity'
                # Every real daily and minute equity before adaptation must be unchanged.
                for key,datekey in [('daily','date'),('minute_curve','datetime'),('fills','fill_time')]:
                    assert [x for x in r[key] if x[datekey]<'2020-01-01']==[x for x in old[key] if x[datekey]<'2020-01-01'],key
                cash=30000+sum((-1 if f['buy'] else 1)*f['price']*f['quantity']-f['fees'] for f in r['fills'])+r['final']['dividend_income']-r['final']['dividend_tax']
                assert abs(cash-r['final']['cash'])<1e-6 and len(r['daily'])==730 and len(r['minute_curve'])==175200
                save(f'{mode}_cost{cost}.json',r);save(f'{mode}_cost{cost}_sizing.json',rules.sizing);save(f'{mode}_cost{cost}_events.json',rules.events)
                row=dict(mode=mode,cost=cost,return_pct=r['metrics']['marked_return']*100,dd_pct=r['metrics']['max_minute_close_drawdown']*100,buys=sum(f['buy'] for f in r['fills']))
                statuses.append(row);save('status.json',statuses);print(json.dumps(row),flush=True)
        save('missing_minutes.json',[dict(symbol=s,date=d) for s,d in sorted(missing)])
        if missing:
            print('AWAIT_MINUTES '+json.dumps(sorted(missing)),flush=True)
            while not set(OUT.glob('minute_export_*.txt'))-loaded:time.sleep(1)
    print('COMPLETE',flush=True)

if __name__=='__main__':main()
