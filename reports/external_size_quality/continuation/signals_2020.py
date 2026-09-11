# SQ1 point-in-time signal export only. No order functions.
import base64,hashlib,json,zlib
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

YEAR=2020
PILOT=False
INDEXES=['000300.SH','000905.SH','000852.SH','000001.SH','399001.SZ','399006.SZ','000016.SH','000688.SH','399330.SZ']

def emit(key,value):
    raw=json.dumps(value,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('utf8')
    encoded=base64.b64encode(zlib.compress(raw)).decode('ascii')
    parts=[encoded[i:i+3000] for i in range(0,len(encoded),3000)]
    for i,part in enumerate(parts):log.info('MINBUNDLE {} {} {} {} {} {}'.format(key,i,len(parts),len(raw),hashlib.sha256(raw).hexdigest(),part))

def frame_rows(frame,prefix):
    f=json.loads(frame.to_json(orient='split',date_format='iso'))
    if len(set(f['columns']))!=len(f['columns']):raise SignalGap('duplicate frame fields')
    if any(not c.startswith(prefix) for c in f['columns']):raise SignalGap('unexpected table fields')
    return [dict(zip([c[len(prefix):] for c in f['columns']],row)) for row in f['data']]

def quarters(asof):
    y=int(asof[:4]);ends=[str(y)+'-'+q for q in ['03-31','06-30','09-30','12-31']]
    ends=[e for e in ends if e<=asof]
    q=max(ends) if ends else str(y-1)+'-12-31'
    out=[q]
    for i in range(7):out.append(prev(out[-1]))
    return out

def get_financial(symbols,asof):
    aliases={s:('001914.SZ' if s=='000043.SZ' and asof<'2019-12-16' else s) for s in symbols}
    if len(set(aliases.values()))!=len(aliases):raise SignalGap('duplicate mapped issuer')
    inverse={v:k for k,v in aliases.items()};batch=list(inverse);out=[]
    queries={
    'income':query(income.symbol,income.report_date,income.stat_date,income.np_atsopc,income.reporttypecode,income.change_id).filter(income.symbol.in_(batch),income.report_date<=asof),
    'balance':query(balance.symbol,balance.report_date,balance.stat_date,balance.total_assets,balance.total_liabilities,balance.total_quity_atsopc,balance.other_equity_instrument,balance.reporttypecode,balance.change_id).filter(balance.symbol.in_(batch),balance.report_date<=asof),
    'cashflow':query(cashflow.symbol,cashflow.report_date,cashflow.stat_date,cashflow.net_cash_flows_from_opt_act,cashflow.reporttypecode,cashflow.change_id).filter(cashflow.symbol.in_(batch),cashflow.report_date<=asof)}
    for j,period in enumerate(quarters(asof)):
        quarter=period[:4]+'q'+str(['03-31','06-30','09-30','12-31'].index(period[5:])+1)
        for table in ['income','balance','cashflow']:
            if table!='income' and j>=4:continue
            frame=get_fundamentals(queries[table],statDate=quarter,latest=True)
            for r in frame_rows(frame,table+'_stat_'):
                source=r['symbol'];s=inverse[source]
                row=dict(symbol=s,source_symbol=source,table=table,period=d(r['stat_date']),published=d(r['report_date']),report_type=r['reporttypecode'],change_id=r['change_id'])
                if row['period']!=period:raise SignalGap('wrong report period')
                if table=='income':row['income']=r['np_atsopc']
                elif table=='balance':row.update(assets=r['total_assets'],liabilities=r['total_liabilities'],equity=r['total_quity_atsopc'],other_equity_instrument=r['other_equity_instrument'])
                else:row['cash']=r['net_cash_flows_from_opt_act']
                out.append(row)
    return out

def snapshot(asof,trade):
    indexes={c:sorted(get_index_stocks(c,asof)) for c in INDEXES}
    universe=sorted(set(s for values in indexes.values() for s in values if (s.endswith('.SZ') and s.startswith(('000','001','002','003'))) or (s.endswith('.SH') and s.startswith(('600','601','603','605')))))
    meta=get_all_securities('stock',asof)
    pool=[];fin=[]
    for offset in range(0,len(universe),200):
        batch=universe[offset:offset+200]
        frames=get_price(batch,asof.replace('-',''),asof.replace('-',''),'1d',['close','is_st','is_paused'],skip_paused=False,fq=None,is_panel=False)
        q=query(valuation.symbol,valuation.date,valuation.pe_ttm,valuation.circulating_cap).filter(valuation.symbol.in_(batch))
        val={r['symbol']:r for r in frame_rows(get_fundamentals(q,date=asof.replace('-','')),'valuation_')}
        for s in batch:
            frame=frames[s]
            if len(frame)!=1 or frame.index[0].strftime('%Y-%m-%d')!=asof:raise SignalGap('price coverage '+s)
            r=frame.iloc[0];v=val.get(s)
            if v is not None and d(v['date'])!=asof:raise SignalGap('valuation date '+s)
            pool.append(dict(symbol=s,asof=asof,listed=d(meta.loc[s,'listed_date']),close=float(r['close']),st=float(r['is_st']),paused=float(r['is_paused']),float_shares=v['circulating_cap'] if v else None,provider_pe=v['pe_ttm'] if v else None))
    ranked,excluded,missing=prepare_pool(pool,asof)
    if missing:fin+=get_financial(missing,asof)
    fetched=[]
    for offset in range(0,len(ranked),100):
        batch=[s for cap,s in ranked[offset:offset+100]]
        fin+=get_financial(batch,asof);fetched+=batch
        decision=select(pool,fin,asof)
        if decision['qualifying_before_stop']>=5:break
    if not ranked:decision=select(pool,fin,asof)
    return dict(asof=asof,trade=trade,indexes=indexes,pool=pool,financial=fin,fetched=fetched,decision=decision)

def init(context):set_benchmark('000905.SH')

def before_trading(context):
    if get_datetime().strftime('%Y%m%d')!='20260904':raise ValueError('FIXED_READONLY_CALLBACK')
    frame=get_price(['000905.SH'],'20171229','20201231','1d',['close'],skip_paused=False,fq=None,is_panel=False)['000905.SH']
    days=[t.strftime('%Y-%m-%d') for t in frame.index]
    trades=[(days[i-1],days[i]) for i in range(1,len(days)) if (i-1)%5==0]
    schedule=trades[:1] if PILOT else [(s,t) for s,t in trades if t.startswith(str(YEAR))]
    emit('schedule',dict(year=YEAR,pilot=PILOT,all_days=days,schedule=schedule,interval=5,execution_not_simulated=True))
    for asof,trade in schedule:
        try:emit('signal_'+asof,snapshot(asof,trade))
        except Exception as exc:emit('signal_'+asof,dict(asof=asof,trade=trade,error=str(exc)))
    log.info('SIZEQ_SIGNALS_DONE')

def handle_bar(context,bar_dict):pass
