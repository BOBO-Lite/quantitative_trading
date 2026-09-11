"""Known prior-session context confirms profit reversals; no future labels."""
from bisect import bisect_right
from statistics import mean
from e1_turning_rules import TurningRules

MODES=('V','S','H','C','F','CF')

def prior_features(history,prior,benchmark_return):
    dates=sorted(history);i=bisect_right(dates,prior)
    if i<21 or dates[i-1]!=prior:raise ValueError('confirmation warmup missing')
    w=[history[d] for d in dates[i-21:i]]
    c=[r['close']*r['factor'] for r in w]
    volume_mean=mean(r['volume'] for r in w[:-1])
    if volume_mean<=0:raise ValueError('zero volume reference')
    return dict(asof=prior,volume_ratio=w[-1]['volume']/volume_mean,
                down=c[-1]<c[-2],relative5=c[-1]/c[-6]-1-benchmark_return,
                two_below_ma10=c[-1]<mean(c[-10:]) and c[-2]<mean(c[-11:-1]))

class ConfirmationLoader:
    def __init__(self,cache,bundle):
        self.cache=cache;self.calendar=bundle['calendar'];self.features={}
        self.bench={d['previous_close']['date']:d['previous_close']['benchmark']['close'] for d in bundle['days']}
    def load(self,day,symbols):
        batches=self.cache.load(day,symbols);i=self.calendar.index(day);prior=self.calendar[i-1]
        # First days of 2018 use pre-existing screen benchmark history below.
        for s in symbols:
            key=s,prior
            if key not in self.features:
                ds=sorted(d for d in self.bench if d<=prior)
                if len(ds)<6:raise ValueError('benchmark warmup missing')
                br=self.bench[ds[-1]]/self.bench[ds[-6]]-1
                self.features[key]=prior_features(self.cache.daily[s],prior,br)
            for batch in batches:batch['bars'][s]['confirmation']=self.features[key];batch['bars'][s]['symbol']=s
        return batches

class ConfirmationRules(TurningRules):
    def __init__(self,mode):
        assert mode in MODES;super().__init__('P');self.confirmation_mode=mode;self.logged=set()
        if mode=='F':self.modes=set();self.turning_modes=set()
    def exit_reason(self,p,bar,route,drawdown,holding_days,close_signal=False,industry_weak=False):
        stamp=bar['datetime'];day=stamp[:10];f=bar.get('confirmation')
        if f is None or f['asof']>=day:raise ValueError('missing or future confirmation context')
        ma=p.get('known_ma10',float('-inf'))+p['stop']-p.get('known_ma10_stop_reference',p['stop'])
        if p.get('confirmation_day')!=day:p['below_count']=0;p['confirmation_day']=day;p.pop('confirmation_stamp',None)
        if not bar['is_paused'] and p.get('confirmation_stamp')!=stamp:
            p['below_count']=p.get('below_count',0)+1 if bar['close']<ma else 0
            p['confirmation_stamp']=stamp
        gates=dict(V=f['down'] and f['volume_ratio']>=1,S=f['relative5']<=0,H=p['below_count']>=30)
        reason=super().exit_reason(p,bar,route,drawdown,holding_days,close_signal,industry_weak)
        if reason and reason!='earned_profit_reversal':return reason
        if reason:
            self.events.pop() # Remove unconfirmed parent event; record causal decision explicitly.
            mode=self.confirmation_mode;accept=sum(gates.values())>=2 if mode in ('C','CF') else gates[mode]
            key=(bar['symbol'],p['entry_date'],day,accept)
            if key not in self.logged:
                self.events.append(dict(event='confirmed_profit_exit' if accept else 'profit_exit_veto',symbol=bar['symbol'],date=stamp,entry_date=p['entry_date'],price=bar['close'],peak=p['turning_peak'],atr=p.get('turning_atr'),known_ma10=ma,below_minutes=p['below_count'],features=f,gates=gates));self.logged.add(key)
            if accept:return 'confirmed_profit_exit'
        if self.confirmation_mode in ('F','CF') and not bar['is_paused'] and f['two_below_ma10'] and f['relative5']<=0 and bar['close']<=p['entry_price']-.5*p['initial_r']:
            self.events.append(dict(event='persistent_weak_loss',symbol=bar['symbol'],date=stamp,entry_date=p['entry_date'],price=bar['close'],features=f));return 'persistent_weak_loss'
        return None
