"""Causal pullback entry, earned-profit protection and failed-rebound exit."""
from e1_asymmetric import AsymmetricRules
import simple_strategy_rules as base
from s2_strategy_rules import Policy

class TurningRules(AsymmetricRules):
    def __init__(self,mode):
        assert mode in ('B','P','Q','PQ','BPQ')
        super().__init__('W' if 'P' in mode else '')
        self.turning_modes=set(mode);self.entry_states={}
    def entry_confirmed(self,signal,minute,route,day_open,day_vwap):
        original=base.entry_confirmed(signal,minute,route,day_open,day_vwap)
        if 'B' not in self.turning_modes:return original
        key=(signal['symbol'],minute['datetime'][:10]);state=self.entry_states.get(key)
        if state is None:
            if original:self.entry_states[key]=dict(first_stamp=minute['datetime'],first_vwap=day_vwap,pulled_back=False)
            return False
        if minute['datetime']<=state['first_stamp']:return False
        if minute['low']<=state['first_vwap']:state['pulled_back']=True
        return original and state['pulled_back']
    def close_protection(self,position,close,ma10,atr20,policy=Policy()):
        p=super().close_protection(position,close,ma10,atr20,policy);p['turning_atr']=atr20
        return p
    def exit_reason(self,position,minute,route,drawdown,holding_days,close_signal=False,industry_weak=False):
        reason=super().exit_reason(position,minute,route,drawdown,holding_days,close_signal,industry_weak)
        if reason:return reason
        if minute['is_paused']:return None
        p=position;price=minute['close'];entry=p['entry_price'];stamp=minute['datetime']
        # The engine changes entry reference by 80% of gross cash dividends.
        shift=(entry-p.get('turning_entry_reference',entry))/.8
        p['turning_peak']=max(p.get('turning_peak',p['highest_close'])+shift,price)
        p['turning_trough']=min(p.get('turning_trough',entry)+shift,price)
        p['turning_entry_reference']=entry
        atr=p.get('turning_atr')
        if 'P' in self.turning_modes and atr is not None and p['turning_peak']-entry>=3*p['initial_r'] and price<=p['turning_peak']-atr:
            self.events.append(dict(event='earned_profit_reversal',date=stamp,entry_date=p['entry_date'],observed_peak=p['turning_peak'],price=price,known_atr=atr));return 'earned_profit_reversal'
        if 'Q' in self.turning_modes:
            if price>=entry:p.pop('rebound_armed_at',None);p['turning_trough']=price
            if price<=entry-.5*p['initial_r'] and 'rebound_armed_at' not in p:
                p['rebound_armed_at']=stamp;p['turning_trough']=price
            if atr is None:return None
            ma=p.get('known_ma10',0)+p['stop']-p.get('known_ma10_stop_reference',p['stop'])
            if p.get('rebound_armed_at',stamp)<stamp and price>=p['turning_trough']+atr and price<min(entry,ma):
                self.events.append(dict(event='weak_rebound_exit',date=stamp,entry_date=p['entry_date'],observed_trough=p['turning_trough'],price=price,known_atr=atr,known_ma10=ma));return 'weak_rebound_exit'
        return None
