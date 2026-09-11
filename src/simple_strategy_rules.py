"""TECH1.0：单一价量突破，无财报/行业/横截面排名依赖。"""
from math import isfinite
from s2_strategy_rules import Policy, planned_loss, fee
from s2_strategy_rules import entry_confirmed as base_confirm
from s2_strategy_rules import size_entry as base_size

VERSION = 'TECH1.0'
uses_industry = False

def research_regime(close, ma20, ma60, slope5=None, ret20=None):
    if not all(isfinite(v) and v > 0 for v in (close, ma20, ma60)):
        return 'defensive_cash'
    return 'trend_breakout' if close > ma20 > ma60 else 'defensive_cash'

def select_signal(row, route, policy=Policy()):
    s = str(row.get('symbol',''))
    if route != 'trend_breakout' or len(s)!=9 or not s[:6].isdigit(): return False
    if not (s.startswith(('000','001','002','003')) and s.endswith('.SZ') or
            s.startswith(('600','601','603','605')) and s.endswith('.SH')): return False
    if row.get('market_state_verified') is not True or row.get('is_st') is not False or row.get('is_paused') is not False:
        return False
    fields = ('listing_bars','amount20','close','ma20','ma60','prior_breakout_close','volume_ratio','atr20_raw')
    if any(not isinstance(row.get(k),(int,float)) or not isfinite(row[k]) for k in fields): return False
    return (row['listing_bars']>=120 and row['amount20']>=50_000_000
            and row['close']>row['ma20']>row['ma60']>0
            and row['close']>row['prior_breakout_close']>0
            and 1.3<=row['volume_ratio']<=3 and row['atr20_raw']>0)

def sort_key(row): return (-row['amount20'],row['symbol'])
def entry_cap(row, route): return int((row['raw_close']*1.04+1e-10)*100)/100
def stop_distance(row, price): return max(2*row['atr20_raw']/price,.03)
def needs_minutes(row,route): return stop_distance(row,entry_cap(row,route))<=.06
def entry_confirmed(signal,minute,route,day_open,day_vwap):
    return minute.get('is_st') is False and base_confirm(signal,minute,route,day_open,day_vwap)

def size_entry(price, stop, equity, cash, exposure, route, drawdown, count, policy=Policy()):
    # 基础定仓函数保留单股跳空压力和含费风险；额外收紧总仓位到70%。
    quantity=base_size(price,stop,equity,cash,exposure,route,drawdown,count,policy)
    while quantity and exposure+quantity*price>equity*.7+1e-8: quantity-=100
    return quantity if quantity*price>=4000 else 0

def exit_reason(position, minute, route, drawdown, holding_days, close_signal=False, industry_weak=False):
    day=str(minute['datetime'])[:10]
    if day<position['entry_date'] or (day==position['entry_date'] and not close_signal) or minute.get('is_paused') is not False:
        return None
    if drawdown>=.15: return 'drawdown_hard_stop'
    if route=='defensive_cash': return 'cash_defense'
    if minute['low']<=position['stop']: return 'protective_stop'
    if close_signal and holding_days>=20: return 'time_exit'
    return None

def close_protection(position, close, ma10, atr20, policy=Policy()):
    if not all(isfinite(v) and v>0 for v in (close,atr20)): raise ValueError('收盘/ATR无效')
    result=dict(position)
    result['highest_close']=max(position.get('highest_close',position['entry_price']),close)
    result['stop']=max(position['stop'],result['highest_close']-2*atr20)
    return result
