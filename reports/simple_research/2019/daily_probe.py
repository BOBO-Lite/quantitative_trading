"""TECH1.0历史扩展只读导出。仅优化数据访问，不改选股条件。"""
import base64, hashlib, json, zlib
import numpy as np
from statistics import mean

WARMUP = '20180101'
START = '2018-12-28'
END = '20191231'

def emit_packet(key,value):
    raw=json.dumps(value,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('utf8')
    encoded=base64.b64encode(zlib.compress(raw)).decode('ascii')
    parts=[encoded[i:i+3000] for i in range(0,len(encoded),3000)]
    for i,part in enumerate(parts):log.info('MINBUNDLE {} {} {} {} {} {}'.format(key,i,len(parts),len(raw),hashlib.sha256(raw).hexdigest(),part))

def init(context):set_benchmark('000905.SH')

def before_trading(context):
    if get_datetime().strftime('%Y%m%d')!='20260904':raise ValueError('FIXED_EXPORT_CALLBACK')
    bm=get_price(['000905.SH'],WARMUP,END,'1d',['close'],skip_paused=False,fq=None,is_panel=False)['000905.SH']
    bd=[t.strftime('%Y-%m-%d') for t in bm.index]
    dates=[d for d in bd if d>=START]
    snapshots={};members={};symbols=set();bc=bm['close'].values.astype(float)
    for day in dates:
        u=get_all_securities('stock',day.replace('-',''))
        ss=sorted(str(s) for s in u.index if (str(s).startswith(('000','001','002','003')) and str(s).endswith('.SZ')) or (str(s).startswith(('600','601','603','605')) and str(s).endswith('.SH')))
        c=bc[:bd.index(day)+1]
        snapshots[day]=dict(date=day,expected_symbols=ss,benchmark=dict(close=float(c[-1]),ma20=float(c[-20:].mean()),ma60=float(c[-60:].mean()),slope5=0.,ret20=float(c[-1]/c[-21]-1)),candidates=[],excluded={},errors=[])
        members[day]=set(ss);symbols.update(ss)
    ordered=sorted(symbols);fields=['high','low','close','volume','turnover','factor','is_st','is_paused']
    for offset in range(0,len(ordered),100):
        frames=get_price(ordered[offset:offset+100],WARMUP,END,'1d',fields,skip_paused=False,fq=None,is_panel=False)
        for symbol in ordered[offset:offset+100]:
            f=frames.get(symbol)
            if f is not None and not f.empty:
                fd=[t.strftime('%Y-%m-%d') for t in f.index];indices={d:i for i,d in enumerate(fd)}
                data=f[fields].values.astype(float);counts=np.cumsum(np.isfinite(data[:,2]) & (data[:,2]>0))
            for day in dates:
                if symbol not in members[day]:continue
                out=snapshots[day];reason=None
                if f is None or f.empty:out['errors'].append([symbol,'MISSING_HISTORY']);continue
                if day not in indices:out['errors'].append([symbol,'DATE_GAP']);continue
                idx=indices[day];count=int(counts[idx])
                if count<120:reason='SHORT_HISTORY'
                elif idx<60:out['errors'].append([symbol,'DATE_GAP']);continue
                else:
                    a=data[idx-60:idx+1]
                    if not np.isfinite(a).all() or min(a[:,5])<=0 or min(a[:,2])<=0:out['errors'].append([symbol,'INVALID_DATA']);continue
                    if a[-1,6] not in (0,1) or a[-1,7] not in (0,1):out['errors'].append([symbol,'INVALID_STATE']);continue
                    factors=a[:,5];base=float(factors[-1]);c=a[:,2]*factors/base;h=a[:,0]*factors/base;l=a[:,1]*factors/base
                    avg=mean(a[-21:-1,4].tolist());pv=mean(a[-21:-1,3].tolist());vr=float(a[-1,3]/pv) if pv>0 else 0.
                    tr=np.maximum(h[-20:]-l[-20:],np.maximum(abs(h[-20:]-c[-21:-1]),abs(l[-20:]-c[-21:-1])))
                    ma20=mean(c[-20:].tolist());ma60=mean(c[-60:].tolist())
                    r=dict(symbol=symbol,date=day,market_state_verified=True,is_st=bool(a[-1,6]),is_paused=bool(a[-1,7]),listing_bars=count,amount20=avg,close=float(c[-1]),ma20=ma20,ma60=ma60,prior_breakout_close=float(c[-21:-1].max()),volume_ratio=vr,atr20_raw=mean(tr.tolist()),raw_close=float(c[-1]),raw_high=float(h[-1]),factor=base,target_ma20_raw=ma20)
                    reason=('ST' if r['is_st'] else 'PAUSED' if r['is_paused'] else 'LOW_LIQUIDITY' if avg<50000000 else 'NO_TECH_SIGNAL' if not (r['close']>r['ma20']>r['ma60'] and r['close']>r['prior_breakout_close'] and 1.3<=vr<=3 and r['atr20_raw']>0) else None)
                    if reason is None:
                        r['audit_window']=dict(dates=fd[idx-60:idx+1],data={k:[float(x) for x in a[:,j]] for j,k in enumerate(fields)})
                        out['candidates'].append(r)
                if reason:out['excluded'].setdefault(reason,[]).append(symbol)
        log.info('TECH1_HISTORY_PROGRESS {}'.format(offset))
    emit_packet('benchmark',dict(data=json.loads(bm.to_json(date_format='iso'))))
    for day,out in sorted(snapshots.items()):emit_packet('tech1_'+day,out)
    log.info('TECH1_HISTORY_DAILY_EXPORT_DONE')

def handle_bar(context,bar_dict):pass
