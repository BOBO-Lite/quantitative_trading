"""Cross exit signals with the same drawdown reentry policy."""
from dataclasses import replace
from math import nextafter,floor
from e1_confirmation import ConfirmationRules
from e1_asymmetric import AsymmetricRules
from exit_research import ExitRules
import simple_strategy_rules as base
from s2_strategy_rules import Policy,planned_loss

MODES=('E1R','FR','E1U','FU','E1H','FH')
class ReentryRules(ConfirmationRules):
    def __init__(self,mode):
        assert mode in MODES;super().__init__('F');self.pair_mode=mode;self.with_f=mode.startswith('F')
        self.reentry_latched=False
        if mode.endswith(('R','H')):self.modes.add('R')
    def exit_reason(self,*args,**kwargs):
        if self.with_f:return super().exit_reason(*args,**kwargs)
        return ExitRules.exit_reason(self,*args,**kwargs)
    def size_entry(self,price,stop,equity,cash,exposure,route,drawdown,count,policy=Policy()):
        if self.pair_mode.endswith('H'):
            if drawdown>=policy.reduce_drawdown:self.reentry_latched=True
            if self.reentry_latched and drawdown<=.10 and self.trend_days>=5:
                self.reentry_latched=False
                self.events.append(dict(event='full_risk_restored_below_10',day_index=self.day_index,drawdown=drawdown))
            if not self.reentry_latched:return base.size_entry(price,stop,equity,cash,exposure,route,drawdown,count,policy)
            if drawdown>=policy.hard_drawdown or self.trend_days<5 or route!='trend_breakout' or count:return 0
            p=replace(policy,risk_fraction=policy.risk_fraction/2,max_positions=1,reduce_drawdown=nextafter(policy.hard_drawdown,0.))
            qty=base.size_entry(price,stop,equity,cash,exposure,route,drawdown,count,p)
            qty=min(qty,max(0,floor((equity*.2-exposure)/price/100)*100))
            room=equity*(policy.hard_drawdown-drawdown)/(1-drawdown)*.5
            while qty and planned_loss(price,stop,qty,policy)>room:qty-=100
            if qty*price<4000:return 0
            if self.last_recovery_event!=self.day_index:
                self.events.append(dict(event='latched_recovery_allowed',day_index=self.day_index,drawdown=drawdown,quantity=qty,risk=planned_loss(price,stop,qty,policy),room=room));self.last_recovery_event=self.day_index
            return qty
        if self.pair_mode.endswith('R'):
            return AsymmetricRules.size_entry(self,price,stop,equity,cash,exposure,route,drawdown,count,policy)
        # U isolates the 12% entry veto. The original 15% permanent hard halt remains.
        p=replace(policy,reduce_drawdown=nextafter(policy.hard_drawdown,0.))
        qty=base.size_entry(price,stop,equity,cash,exposure,route,drawdown,count,p)
        if qty and drawdown>=policy.reduce_drawdown:
            self.events.append(dict(event='unrestricted_soft_drawdown_entry',day_index=self.day_index,drawdown=drawdown,quantity=qty))
        return qty
