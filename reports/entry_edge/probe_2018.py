"""Read-only fixed forward-price diagnostics, no trading functions."""
import json,hashlib,base64,zlib,math
import numpy as np

SIGNALS = {'2018-01-25': ['000060.SZ', '000157.SZ', '000825.SZ', '000975.SZ', '002210.SZ', '002237.SZ', '002385.SZ', '002742.SZ', '600000.SH', '600104.SH', '600129.SH', '600153.SH', '600320.SH', '600398.SH', '600489.SH', '600547.SH', '600583.SH', '600757.SH', '600771.SH', '601000.SH', '601009.SH', '601168.SH', '601898.SH', '601997.SH'], '2018-01-26': ['000541.SZ', '000581.SZ', '000876.SZ', '000960.SZ', '002563.SZ', '600023.SH', '600153.SH', '600177.SH', '600251.SH', '600308.SH', '600707.SH', '601009.SH', '601117.SH', '601166.SH', '601668.SH', '601997.SH', '603167.SH']}
YEAR = 2018

def emit(key,value):
    raw=json.dumps(value,separators=(',',':'),allow_nan=False).encode()
    encoded=base64.b64encode(zlib.compress(raw)).decode()
    parts=[encoded[i:i+3000] for i in range(0,len(encoded),3000)]
    for i,p in enumerate(parts):log.info('MINBUNDLE {} {} {} {} {} {}'.format(key,i,len(parts),len(raw),hashlib.sha256(raw).hexdigest(),p))
def init(context):set_benchmark('000905.SH')
def before_trading(context):
    if get_datetime().strftime('%Y%m%d')!='20260904':raise ValueError('FIXED_CALLBACK')
    start=str(YEAR-2)+'0101';end=min(str(YEAR+1)+'0430','20201231')
    fields=['open','close','factor','volume','turnover','is_st','is_paused','high_limit']
    bm=get_price(['000905.SH'],start,end,'1d',['open','close'],skip_paused=False,fq=None,is_panel=False)['000905.SH']
    calendar=[t.strftime('%Y-%m-%d') for t in bm.index];bindex={d:i for i,d in enumerate(calendar)}
    snapshots={};members={};universe=set()
    for day in sorted(SIGNALS):
        securities=get_all_securities('stock',day.replace('-',''))
        ss=sorted(str(s) for s in securities.index if (str(s).startswith(('000','001','002','003')) and str(s).endswith('.SZ')) or (str(s).startswith(('600','601','603','605')) and str(s).endswith('.SH')))
        members[day]=set(ss);universe.update(ss)
        bi=bindex[day];windows={}
        for h in (5,20,60):
            if bi+h>=len(calendar) or calendar[bi+h]>'2020-12-31':windows[str(h)]=None
            else:windows[str(h)]=dict(entry=calendar[bi+1],end=calendar[bi+h],open=float(bm.iloc[bi+1]['open']),close=float(bm.iloc[bi+h]['close']))
        snapshots[day]=dict(date=day,members=ss,pool=[],fh=[],momentum=[],errors=[],windows=windows)
    ordered=sorted(universe)
    for offset in range(0,len(ordered),100):
        frames=get_price(ordered[offset:offset+100],start,end,'1d',fields,skip_paused=False,fq=None,is_panel=False)
        for symbol in ordered[offset:offset+100]:
            f=frames.get(symbol)
            if f is None or f.empty:
                for day in SIGNALS:
                    if symbol in members[day]:snapshots[day]['errors'].append([symbol,'MISSING_HISTORY'])
                continue
            dates=[t.strftime('%Y-%m-%d') for t in f.index];indices={d:i for i,d in enumerate(dates)}
            a=f[fields].values.astype(float);counts=np.cumsum(np.isfinite(a[:,1]) & (a[:,1]>0))
            for day in SIGNALS:
                if symbol not in members[day]:continue
                out=snapshots[day];idx=indices.get(day)
                if idx is None:out['errors'].append([symbol,'DATE_GAP']);continue
                if counts[idx]<120 or idx<60:continue
                w=a[idx-60:idx+1]
                if not np.isfinite(w).all() or min(w[:,1])<=0 or min(w[:,2])<=0:
                    out['errors'].append([symbol,'INVALID_FEATURES']);continue
                amount=float(np.mean(w[-21:-1,4]));c=w[:,1]*w[:,2]
                basic=w[-1,5]==0 and w[-1,6]==0 and amount>=50000000
                is_fh=symbol in SIGNALS[day]
                if not basic and not is_fh:continue
                outcomes={}
                for h in (5,20,60):
                    window=out['windows'][str(h)]
                    if window is None:outcomes[str(h)]=dict(status='CENSORED');continue
                    ei=indices.get(window['entry']);ti=indices.get(window['end'])
                    if ei is None or ti is None:outcomes[str(h)]=dict(status='MISSING_ENDPOINT');continue
                    e=a[ei];t=a[ti]
                    if not np.isfinite(e).all() or not np.isfinite(t).all() or min(e[0],e[2],t[1],t[2])<=0:
                        outcomes[str(h)]=dict(status='INVALID_ENDPOINT');continue
                    outcomes[str(h)]=dict(status='OK',open=float(e[0]),entry_factor=float(e[2]),close=float(t[1]),end_factor=float(t[2]),
                        entry_paused=bool(e[6]),entry_st=bool(e[5]),entry_at_limit=bool(e[0]>=e[7]),end_paused=bool(t[6]),
                        ret=float(t[1]*t[2]/(e[0]*e[2])-1))
                row=dict(symbol=symbol,signal_close=float(w[-1,1]),signal_factor=float(w[-1,2]),amount20=amount,
                    mom60=float(c[-1]/c[0]-1),above_ma60=bool(c[-1]>np.mean(c[-60:])),outcomes=outcomes)
                if is_fh:out['fh'].append(row)
                if basic:
                    out['pool'].append([symbol,{h:v for h,v in outcomes.items()}])
                    if row['mom60']>0 and row['above_ma60']:
                        out['momentum'].append(row)
                        out['momentum']=sorted(out['momentum'],key=lambda r:(-r['mom60'],r['symbol']))[:5]
        log.info('EDGE_PROGRESS {}'.format(offset))
    for day,out in sorted(snapshots.items()):
        # Aggregate the unselected pool but retain every missing/blocked name.
        stats={}
        for h in ('5','20','60'):
            valid=[v[h]['ret'] for s,v in out['pool'] if v[h]['status']=='OK']
            stats[h]=dict(n=len(out['pool']),valid=len(valid),sum=float(sum(valid)),median=float(np.median(valid)) if valid else None,
                missing=[[s,v[h]['status']] for s,v in out['pool'] if v[h]['status']!='OK'],
                entry_untradable=[s for s,v in out['pool'] if v[h]['status']=='OK' and (v[h]['entry_paused'] or v[h]['entry_st'] or v[h]['entry_at_limit'])])
        out['pool_stats']=stats;out.pop('pool')
        emit('edge_'+day,out)
    emit('edge_meta',dict(year=YEAR,signal_dates=sorted(SIGNALS),count=sum(len(v) for v in SIGNALS.values())))
    log.info('ENTRY_EDGE_EXPORT_DONE')
def handle_bar(context,bar_dict):pass
