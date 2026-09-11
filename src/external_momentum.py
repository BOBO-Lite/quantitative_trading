"""Independently calculate and audit EXT-MOM1 source signals; no trading entrypoint."""
from pathlib import Path
import hashlib,json,math
import numpy as np
from import_supermind_minute_probe import decode_packets

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/external_momentum'

def features(window):
    dates=window['dates'];d=window['data']
    if len(dates)!=100 or dates!=sorted(set(dates)) or any(len(v)!=100 for v in d.values()):
        raise ValueError('invalid 100-day window')
    a={k:np.asarray(v,dtype=float) for k,v in d.items()}
    if any(not np.isfinite(v).all() for v in a.values()):raise ValueError('nonfinite source')
    if any((a[k]<=0).any() for k in ('open','high','low','close','factor')):raise ValueError('nonpositive price')
    if (a['low']>np.minimum(a['open'],a['close'])+1e-8).any() or (a['high']<np.maximum(a['open'],a['close'])-1e-8).any():raise ValueError('OHLC order')
    if (a['volume']<0).any() or (a['turnover']<0).any():raise ValueError('negative volume')
    if any(not np.isin(a[k],[0,1]).all() for k in ('is_st','is_paused')):raise ValueError('invalid state')
    ratio=a['factor']/a['factor'][-1];c=a['close']*ratio;h=a['high']*ratio;l=a['low']*ratio
    x=np.arange(90,dtype=float);y=np.log(c[-90:])
    slope,intercept=np.polyfit(x,y,1)
    variance=float(np.sum((y-y.mean())**2))
    r2=max(0.,min(1.,1-float(np.sum((y-(slope*x+intercept))**2))/variance)) if variance>1e-20 else 0.
    atr=np.maximum.reduce([h[-20:]-l[-20:],abs(h[-20:]-c[-21:-1]),abs(l[-20:]-c[-21:-1])]).mean()
    return dict(score=float(np.expm1(252*slope)*r2),slope=float(slope),r2=r2,close=float(c[-1]),ma100=float(c.mean()),atr20=float(atr),gap90=float(np.max(np.abs(c[-89:]/c[-90:-1]-1))),factor=float(a['factor'][-1]))

def buy_eligible(row):
    return row['score']>0 and row['close']>row['ma100'] and row['gap90']<=.15 and row['atr20']>0

def weights(rows,gross=.95,cap=.25):
    if not rows:return {}
    values={r['symbol']:r['close']/r['atr20'] for r in rows}
    if len(values)!=len(rows) or any(not math.isfinite(v) or v<=0 for v in values.values()):raise ValueError('invalid volatility weights')
    left=min(gross,cap*len(values));result={};active=dict(values)
    while active:
        total=sum(active.values());clipped=[s for s,v in active.items() if left*v/total>cap+1e-12]
        if not clipped:
            result.update({s:left*v/total for s,v in active.items()});break
        for s in clipped:result[s]=cap;left-=cap;del active[s]
    return result

def audit(paths):
    if isinstance(paths,Path):paths=[paths]
    packets={};bm={};hashes={}
    for path in paths:
        raw=path.read_text(encoding='utf8')
        if 'EXTMOM_SCREEN_DONE' not in raw or '日志条数超过限制' in raw:raise ValueError('export incomplete')
        batch=decode_packets(raw);b=batch.pop('benchmark')['data']['close']
        if any(bm[k]!=b[k] for k in set(bm)&set(b)):raise ValueError('benchmark conflict')
        bm.update(b)
        if set(batch)&set(packets):raise ValueError('duplicated monthly packet')
        packets.update(batch);hashes[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    bm={k[:10]:v for k,v in bm.items()};calendar=sorted(bm)
    expected=[(calendar[i-1],d) for i,d in enumerate(calendar) if i and '2018-01-01'<=d<='2020-12-31' and d[:7]!=calendar[i-1][:7]]
    if set(packets)!={'extmom_'+s for s,t in expected}:raise ValueError('monthly schedule coverage')
    summaries=[];rankings={};windows=0;resolved=[]
    for signal,trade in expected:
        p=packets['extmom_'+signal]
        errors=list(p['errors']);resolution=[]
        if signal=='2018-12-28' and ['600270.SH','MISSING_HISTORY'] in errors:
            evidence=json.loads((OUT/'universe_resolution.json').read_text(encoding='utf8'))
            if evidence['signal']!=signal or evidence['symbol']!='600270.SH' or evidence['publication_date']>signal or evidence['delisting_effective']>signal or hashlib.sha256((OUT/'600270_delisting_source.txt').read_bytes()).hexdigest()!=evidence['source_sha256']:raise ValueError('invalid delisting resolution')
            errors.remove(['600270.SH','MISSING_HISTORY']);resolution=['600270.SH'];resolved.append(evidence)
        if (p['signal'],p['trade'])!=(signal,trade) or errors:raise ValueError('source errors '+str(errors[:5]))
        full=p['all_members']
        if len(full)!=500 or len(set(full))!=500:raise ValueError('index membership not 500 unique')
        members=[s for s in full if (s.startswith(('000','001','002','003')) and s.endswith('.SZ')) or (s.startswith(('600','601','603','605')) and s.endswith('.SH'))]
        if p['members']!=members:raise ValueError('mainboard filter mismatch')
        covered=[r['symbol'] for r in p['rows']]+sum(p['excluded'].values(),[])+resolution
        if sorted(covered)!=sorted(members):raise ValueError('missing/duplicated universe classification')
        index=calendar.index(signal);ma=float(np.mean([bm[d] for d in calendar[index-199:index+1]]))
        if not math.isclose(ma,p['benchmark']['ma200'],rel_tol=1e-10) or bm[signal]!=p['benchmark']['close']:raise ValueError('benchmark mismatch')
        rows=[]
        for row in p['rows']:
            w=row['window']
            if w['dates']!=calendar[index-99:index+1]:raise ValueError('source window calendar mismatch')
            f=features(w);windows+=1
            for k,v in f.items():
                if not math.isclose(v,row[k],rel_tol=1e-7,abs_tol=1e-9):raise ValueError('feature mismatch '+row['symbol']+' '+k)
            if w['data']['is_st'][-1] or w['data']['is_paused'][-1]:raise ValueError('ineligible row')
            rows.append(dict(symbol=row['symbol'],**f))
        rows.sort(key=lambda r:(-r['score'],r['symbol']))
        if [r['symbol'] for r in rows]!=[r['symbol'] for r in p['rows']]:raise ValueError('ranking mismatch')
        rankings[trade]=dict(signal=signal,market_on=bm[signal]>ma,rows=rows,members=members,excluded=p['excluded'])
        targets=[r for r in rows if buy_eligible(r)][:5] if bm[signal]>ma else []
        summaries.append(dict(trade=trade,signal=signal,index_members=len(full),mainboard=len(members),ranked=len(rows),market_on=bm[signal]>ma,new_entry_candidates=[r['symbol'] for r in targets],weights=weights(targets)))
    result=dict(status='PASS_EXTMOM_MONTHLY_SCREEN',source_sha256=hashes,resolved_source_errors=resolved,months=len(expected),independently_recomputed_windows=windows,days=sum('2018-01-01'<=d<='2020-12-31' for d in calendar),summaries=summaries,rankings=rankings,calendar=calendar,benchmark=bm,scope='source signal audit, not portfolio performance')
    (OUT/'screen.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    return result

if __name__=='__main__':
    result=audit(sorted(OUT.glob('screen_export_*.txt')))
    print(json.dumps({k:v for k,v in result.items() if k not in ('rankings','calendar','benchmark','summaries')},ensure_ascii=False))
