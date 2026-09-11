"""SQ1 historical selector. Pure Python shared with the read-only exporter.

Provider PE is diagnostic only. Positive TTM parent profit is the PE sign gate.
Financial fields remain the registered platform-parent-equity approximation.
"""
from datetime import date
import math

class SignalGap(ValueError):pass

def d(value):
    text=str(value)[:10]
    try:return date.fromisoformat(text).isoformat()
    except ValueError:raise SignalGap('invalid date '+text)

def num(value):
    if value is None or isinstance(value,bool):raise SignalGap('missing number')
    try:x=float(value)
    except (TypeError,ValueError):raise SignalGap('invalid number')
    if not math.isfinite(x):raise SignalGap('nonfinite number')
    return x

def prev(period):
    y=int(period[:4]);q={'03-31':1,'06-30':2,'09-30':3,'12-31':4}.get(period[5:])
    if q is None:raise SignalGap('invalid quarter')
    return str(y-1)+'-12-31' if q==1 else str(y)+'-'+['03-31','06-30','09-30'][q-2]

def records_index(records,asof):
    result={}
    for r in records:
        if r['table'] not in ('income','balance','cashflow'):raise SignalGap('unknown table')
        period,published=d(r['period']),d(r['published']);prev(period)
        if not period<=published<=asof:raise SignalGap('unavailable financial row')
        k=(r['symbol'],r['table'],period)
        if k in result:raise SignalGap('duplicate financial version')
        result[k]=r
    return result

def latest_period(fin,symbol):
    periods=[p for s,t,p in fin if s==symbol and t=='income']
    if not periods:raise SignalGap('missing income history '+symbol)
    return max(periods)

def ttm_income(fin,symbol,period):
    def get(p):
        try:return num(fin[symbol,'income',p]['income'])
        except KeyError:raise SignalGap('missing TTM leg '+symbol+' '+p)
    current=get(period)
    if period.endswith('12-31'):return current
    y=int(period[:4])-1
    return current+get(str(y)+'-12-31')-get(str(y)+period[4:])

def financial_decision(fin,symbol):
    period=latest_period(fin,symbol)
    def get(t,p):
        try:return fin[symbol,t,p]
        except KeyError:raise SignalGap('missing '+t+' '+symbol+' '+p)
    b=get('balance',period);assets,liabilities=num(b['assets']),num(b['liabilities'])
    if assets<=0 or liabilities<0:raise SignalGap('invalid balance')
    debt=liabilities/assets
    if debt>=.7:return dict(eligible=False,reason='DEBT_GE_70',period=period,debt_ratio=debt)
    ttm=ttm_income(fin,symbol,period)
    if ttm<=0:return dict(eligible=False,reason='TTM_NONPOSITIVE',period=period,ttm_income=ttm)
    before=prev(period);bp=get('balance',before)
    e0,e1=num(bp['equity']),num(b['equity'])
    if min(e0,e1)<=0:raise SignalGap('nonpositive equity; classification required')
    flow=num(get('income',period)['income']);cash=num(get('cashflow',period)['cash'])
    if not period.endswith('03-31'):
        flow-=num(get('income',before)['income']);cash-=num(get('cashflow',before)['cash'])
    roe=200*flow/(e0+e1)
    reason='QUARTER_ROE_LE_5' if roe<=5 else 'QUARTER_CASH_NONPOSITIVE' if cash<=0 else 'ELIGIBLE'
    return dict(eligible=reason=='ELIGIBLE',reason=reason,period=period,ttm_income=ttm,roe_quarter_pct=roe,operating_cash_quarter=cash,debt_ratio=debt)

def prepare_pool(pool,asof):
    ranked=[];excluded={};missing=[];seen=set()
    for r in pool:
        s=r['symbol']
        if s in seen:raise SignalGap('duplicate universe identity')
        seen.add(s)
        if d(r['asof'])!=asof:raise SignalGap('pool date mismatch')
        age=(date.fromisoformat(asof)-date.fromisoformat(d(r['listed']))).days
        if age<0:raise SignalGap('future listing')
        if r['st'] not in (0,1) or r['paused'] not in (0,1):raise SignalGap('unknown trading status')
        reason='LISTED_LE_365' if age<=365 else 'ST' if r['st'] else 'PAUSED' if r['paused'] else None
        if reason:excluded[s]=reason;continue
        close=num(r['close'])
        if close<=0:raise SignalGap('nonpositive close')
        if r['float_shares'] is None:missing.append(s);continue
        shares=num(r['float_shares'])
        if shares<=0:raise SignalGap('nonpositive float shares')
        ranked.append((close*shares,s))
    return sorted(ranked),excluded,sorted(missing)

def select(pool,records,asof):
    asof=d(asof);ranked,excluded,missing=prepare_pool(pool,asof)
    fin=records_index(records,asof);errors=[];tested={};targets=[];higher=[]
    # A stock without ranking data can only be ignored with independent proof.
    for s in missing:
        try:
            r=financial_decision(fin,s);tested[s]=r
            if r['eligible']:raise SignalGap('eligible stock without ranking data')
            excluded[s]=r['reason']
        except SignalGap as exc:errors.append(dict(symbol=s,error=str(exc)))
    for cap,s in ranked:
        if len(targets)>=5:higher.append(s);continue
        try:
            r=financial_decision(fin,s);r['float_market_cap']=cap;tested[s]=r
            if r['eligible']:targets.append(s)
            else:excluded[s]=r['reason']
        except SignalGap as exc:errors.append(dict(symbol=s,error=str(exc)))
    status='BLOCKED' if errors else 'PASS'
    if len(excluded)+len(targets)+len(higher)+len(errors)!=len(pool):raise SignalGap('classification coverage')
    return dict(status=status,asof=asof,targets=targets if not errors and len(targets)==5 else None if errors else [],
                excluded=excluded,tested=tested,errors=errors,higher_cap_not_needed=higher,
                missing_float_shares=missing,coverage=len(pool),qualifying_before_stop=len(targets))
