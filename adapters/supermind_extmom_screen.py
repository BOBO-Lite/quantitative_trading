"""EXT-MOM1 read-only monthly source export; no orders, 2018-2020."""
import base64, hashlib, json, zlib
import numpy as np

START='2018-01-01'
END='2020-12-31'
WARMUP='20170101'

def emit(key,value):
    raw=json.dumps(value,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('utf8')
    encoded=base64.b64encode(zlib.compress(raw)).decode('ascii')
    parts=[encoded[i:i+3000] for i in range(0,len(encoded),3000)]
    for i,part in enumerate(parts):log.info('MINBUNDLE {} {} {} {} {} {}'.format(key,i,len(parts),len(raw),hashlib.sha256(raw).hexdigest(),part))

def init(context):set_benchmark('000905.SH')

def before_trading(context):
    if get_datetime().strftime('%Y%m%d')!='20260904':raise ValueError('FIXED_EXPORT_CALLBACK')
    bm=get_price(['000905.SH'],WARMUP,END.replace('-',''),'1d',['close'],skip_paused=False,fq=None,is_panel=False)['000905.SH']
    bd=[t.strftime('%Y-%m-%d') for t in bm.index]
    schedule=[(bd[i-1],d) for i,d in enumerate(bd) if i and START<=d<=END and d[:7]!=bd[i-1][:7]]
    snapshots={};symbols=set()
    for signal,trade in schedule:
        all_members=sorted(get_index_stocks('000905.SH',signal.replace('-','')))
        members=[s for s in all_members if (s.startswith(('000','001','002','003')) and s.endswith('.SZ')) or (s.startswith(('600','601','603','605')) and s.endswith('.SH'))]
        b=bm['close'].values[:bd.index(signal)+1].astype(float)
        if len(b)<200 or not np.isfinite(b[-200:]).all():raise ValueError('BENCHMARK_WARMUP')
        snapshots[signal]=dict(signal=signal,trade=trade,all_members=all_members,members=members,benchmark=dict(close=float(b[-1]),ma200=float(b[-200:].mean())),rows=[],excluded={},errors=[])
        symbols.update(members)
    fields=['open','high','low','close','volume','turnover','factor','is_st','is_paused']
    ordered=sorted(symbols)
    for offset in range(0,len(ordered),50):
        batch=ordered[offset:offset+50]
        frames=get_price(batch,WARMUP,END.replace('-',''),'1d',fields,skip_paused=False,fq=None,is_panel=False)
        for s in batch:
            frame=frames.get(s)
            if frame is not None and not frame.empty:
                dates=[t.strftime('%Y-%m-%d') for t in frame.index];indices={d:i for i,d in enumerate(dates)}
                a=frame[fields].values.astype(float)
            for signal,trade in schedule:
                out=snapshots[signal]
                if s not in out['members']:continue
                if frame is None or frame.empty or signal not in indices:out['errors'].append([s,'MISSING_HISTORY']);continue
                i=indices[signal];w=a[max(0,i-99):i+1]
                valid=np.isfinite(w[:,3]) & (w[:,3]>0)
                if len(w)<100 or not valid.all():out['excluded'].setdefault('SHORT_HISTORY',[]).append(s);continue
                if not np.isfinite(w).all() or (w[:,6]<=0).any():out['errors'].append([s,'INVALID_DATA']);continue
                if w[-1,7] not in (0,1) or w[-1,8] not in (0,1):out['errors'].append([s,'INVALID_STATE']);continue
                if w[-1,7] or w[-1,8]:out['excluded'].setdefault('ST_OR_PAUSED',[]).append(s);continue
                c=w[:,3]*w[:,6]/w[-1,6];h=w[:,1]*w[:,6]/w[-1,6];l=w[:,2]*w[:,6]/w[-1,6]
                y=np.log(c[-90:]);x=np.arange(90,dtype=float);xc=x-x.mean();yc=y-y.mean()
                slope=float(np.dot(xc,yc)/np.dot(xc,xc));den=float(np.dot(yc,yc));r2=float(np.dot(xc,yc)**2/(np.dot(xc,xc)*den)) if den>0 else 0.
                score=float(np.expm1(slope*252)*r2)
                atr=float(np.maximum(h[-20:]-l[-20:],np.maximum(abs(h[-20:]-c[-21:-1]),abs(l[-20:]-c[-21:-1]))).mean())
                gap=float(np.max(np.abs(c[-89:]/c[-90:-1]-1)))
                out['rows'].append(dict(symbol=s,score=score,slope=slope,r2=r2,close=float(c[-1]),ma100=float(c.mean()),atr20=atr,gap90=gap,factor=float(w[-1,6]),window=dict(dates=dates[i-99:i+1],data={f:[float(v) for v in w[:,j]] for j,f in enumerate(fields)})))
        log.info('EXTMOM_PROGRESS {}'.format(offset))
    emit('benchmark',dict(data=json.loads(bm.to_json(date_format='iso'))))
    for signal,out in sorted(snapshots.items()):
        out['rows'].sort(key=lambda r:(-r['score'],r['symbol']))
        emit('extmom_'+signal,out)
    log.info('EXTMOM_SCREEN_DONE')

def handle_bar(context,bar_dict):pass
