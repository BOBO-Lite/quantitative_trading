"""TECH1.0只读全池日线筛选；固定2019Q2，运行回调2026-09-04，不下单。"""
import base64,hashlib,json,zlib,math
import numpy as np

def emit_packet(key,value):
    raw=json.dumps(value,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('utf8')
    encoded=base64.b64encode(zlib.compress(raw)).decode('ascii')
    parts=[encoded[i:i+3000] for i in range(0,len(encoded),3000)]
    for i,part in enumerate(parts):log.info('MINBUNDLE {} {} {} {} {} {}'.format(key,i,len(parts),len(raw),hashlib.sha256(raw).hexdigest(),part))

def init(context):set_benchmark('000905.SH')

def before_trading(context):
    if get_datetime().strftime('%Y%m%d')!='20260904':raise ValueError('FIXED_EXPORT_CALLBACK')
    bm=get_price(['000905.SH'],'20180901','20190628','1d',['close'],skip_paused=False,fq=None,is_panel=False)['000905.SH']
    dates=[t.strftime('%Y-%m-%d') for t in bm.index if t.strftime('%Y-%m-%d')>='2019-03-29']
    snapshots={};symbols=set()
    for day in dates:
        u=get_all_securities('stock',day.replace('-',''))
        ss=sorted(str(s) for s in u.index if str(s).startswith(('000','001','002','003','600','601','603','605')) and str(s).endswith(('.SH','.SZ')))
        c=bm.loc[:day,'close'].values.astype(float)
        snapshots[day]=dict(date=day,expected_symbols=ss,benchmark=dict(close=float(c[-1]),ma20=float(c[-20:].mean()),ma60=float(c[-60:].mean()),slope5=0.,ret20=float(c[-1]/c[-21]-1)),candidates=[],excluded={},errors=[])
        symbols.update(ss)
    ordered=sorted(symbols)
    fields=['high','low','close','volume','turnover','factor','is_st','is_paused']
    for offset in range(0,len(ordered),100):
        frames=get_price(ordered[offset:offset+100],'20180901','20190628','1d',fields,skip_paused=False,fq=None,is_panel=False)
        for symbol in ordered[offset:offset+100]:
            f=frames.get(symbol)
            for day in dates:
                out=snapshots[day]
                if symbol not in out['expected_symbols']:continue
                reason=None
                if f is None or f.empty:
                    out['errors'].append([symbol,'MISSING_HISTORY']);continue
                w=f.loc[:day];valid=w['close'].notnull() & (w['close']>0);count=int(valid.sum())
                if count<120:reason='SHORT_HISTORY'
                elif w.index[-1].strftime('%Y-%m-%d')!=day or len(w)<61:
                    out['errors'].append([symbol,'DATE_GAP']);continue
                else:
                    w=w.iloc[-61:]
                    a=w[fields].values.astype(float)
                    if not np.isfinite(a).all() or min(w['factor'])<=0 or min(w['close'])<=0:
                        out['errors'].append([symbol,'INVALID_DATA']);continue
                    if float(w['is_st'].iloc[-1]) not in (0,1) or float(w['is_paused'].iloc[-1]) not in (0,1):
                        out['errors'].append([symbol,'INVALID_STATE']);continue
                    factors=w['factor'].values.astype(float);base=float(factors[-1])
                    c=w['close'].values.astype(float)*factors/base
                    h=w['high'].values.astype(float)*factors/base;l=w['low'].values.astype(float)*factors/base
                    v=w['volume'].values.astype(float);amount=w['turnover'].values.astype(float)
                    avg=float(amount[-21:-1].mean());pv=float(v[-21:-1].mean())
                    vr=float(v[-1]/pv) if pv>0 else 0.
                    tr=np.maximum(h[-20:]-l[-20:],np.maximum(abs(h[-20:]-c[-21:-1]),abs(l[-20:]-c[-21:-1])))
                    r=dict(symbol=symbol,date=day,market_state_verified=True,is_st=bool(w['is_st'].iloc[-1]),is_paused=bool(w['is_paused'].iloc[-1]),listing_bars=count,amount20=avg,close=float(c[-1]),ma20=float(c[-20:].mean()),ma60=float(c[-60:].mean()),prior_breakout_close=float(c[-21:-1].max()),volume_ratio=vr,atr20_raw=float(tr.mean()),raw_close=float(c[-1]),raw_high=float(h[-1]),factor=base,target_ma20_raw=float(c[-20:].mean()))
                    reason=('ST' if r['is_st'] else 'PAUSED' if r['is_paused'] else 'LOW_LIQUIDITY' if avg<50000000 else 'NO_TECH_SIGNAL' if not (r['close']>r['ma20']>r['ma60'] and r['close']>r['prior_breakout_close'] and 1.3<=vr<=3 and r['atr20_raw']>0) else None)
                    if reason is None:
                        r['audit_window']=dict(dates=[t.strftime('%Y-%m-%d') for t in w.index],data={k:[float(x) for x in w[k].values] for k in fields})
                        out['candidates'].append(r)
                if reason:out['excluded'].setdefault(reason,[]).append(symbol)
        log.info('TECH1_DAILY_PROGRESS {}'.format(offset))
    emit_packet('benchmark',dict(data=json.loads(bm.to_json(date_format='iso'))))
    for day,out in sorted(snapshots.items()):emit_packet('tech1_'+day,out)
    log.info('TECH1_Q2_DAILY_EXPORT_DONE')

def handle_bar(context,bar_dict):pass
