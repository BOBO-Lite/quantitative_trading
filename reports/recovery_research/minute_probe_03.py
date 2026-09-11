"""TECH1.0只读全池日线筛选；固定2019Q2，运行回调2026-09-04，不下单。"""
import base64,hashlib,json,zlib,math
import numpy as np

def emit_packet(key,value):
    raw=json.dumps(value,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('utf8')
    encoded=base64.b64encode(zlib.compress(raw)).decode('ascii')
    parts=[encoded[i:i+3000] for i in range(0,len(encoded),3000)]
    for i,part in enumerate(parts):log.info('MINBUNDLE {} {} {} {} {} {}'.format(key,i,len(parts),len(raw),hashlib.sha256(raw).hexdigest(),part))

REQUESTS = [('002242.SZ', '2019-04-01'), ('002242.SZ', '2019-04-02'), ('002242.SZ', '2019-04-03'), ('002242.SZ', '2019-04-04'), ('002242.SZ', '2019-04-08'), ('002242.SZ', '2019-04-09'), ('002242.SZ', '2019-04-10'), ('002242.SZ', '2019-04-11'), ('002242.SZ', '2019-04-12'), ('002242.SZ', '2019-04-15'), ('002242.SZ', '2019-04-16'), ('002242.SZ', '2019-04-17'), ('002242.SZ', '2019-04-18'), ('002242.SZ', '2019-04-19'), ('002242.SZ', '2019-04-22'), ('002242.SZ', '2019-04-23'), ('002242.SZ', '2019-04-24'), ('002242.SZ', '2019-04-25'), ('002242.SZ', '2019-04-26'), ('002242.SZ', '2019-04-29'), ('002242.SZ', '2019-04-30'), ('002242.SZ', '2019-05-06'), ('002242.SZ', '2019-05-07'), ('002242.SZ', '2019-05-08'), ('002242.SZ', '2019-05-09'), ('002242.SZ', '2019-05-10'), ('002242.SZ', '2019-05-13'), ('600160.SH', '2019-04-01'), ('600160.SH', '2019-04-02'), ('600160.SH', '2019-04-03'), ('600160.SH', '2019-04-04'), ('600160.SH', '2019-04-08'), ('600160.SH', '2019-04-09'), ('600160.SH', '2019-04-10'), ('600160.SH', '2019-04-11'), ('600160.SH', '2019-04-12'), ('600160.SH', '2019-04-15'), ('600160.SH', '2019-04-16'), ('600160.SH', '2019-04-17'), ('600160.SH', '2019-04-18'), ('600160.SH', '2019-04-19'), ('600160.SH', '2019-04-22'), ('600160.SH', '2019-04-23'), ('600160.SH', '2019-04-24'), ('600160.SH', '2019-04-25'), ('600160.SH', '2019-04-26'), ('600160.SH', '2019-04-29'), ('600160.SH', '2019-04-30'), ('600160.SH', '2019-05-06'), ('600160.SH', '2019-05-07'), ('600160.SH', '2019-05-08'), ('600160.SH', '2019-05-09'), ('600160.SH', '2019-05-10'), ('600160.SH', '2019-05-13'), ('601021.SH', '2019-04-01'), ('601021.SH', '2019-04-02'), ('601021.SH', '2019-04-03'), ('601021.SH', '2019-04-04'), ('601021.SH', '2019-04-08'), ('601021.SH', '2019-04-09'), ('601021.SH', '2019-04-10'), ('601021.SH', '2019-04-11'), ('601021.SH', '2019-04-12'), ('601021.SH', '2019-04-15'), ('601021.SH', '2019-04-16'), ('601021.SH', '2019-04-17'), ('601021.SH', '2019-04-18'), ('601021.SH', '2019-04-19'), ('601021.SH', '2019-04-22'), ('601021.SH', '2019-04-23'), ('601021.SH', '2019-04-24'), ('601021.SH', '2019-04-25'), ('601021.SH', '2019-04-26'), ('601021.SH', '2019-04-29'), ('601021.SH', '2019-04-30'), ('601021.SH', '2019-05-06'), ('601021.SH', '2019-05-07'), ('601021.SH', '2019-05-08'), ('601021.SH', '2019-05-09'), ('601021.SH', '2019-05-10'), ('601021.SH', '2019-05-13')]

def init(context):set_benchmark('000905.SH')

def packed(frame):
    return dict(dates=[t.strftime('%Y-%m-%dT%H:%M:%S') for t in frame.index],data={k:[None if not math.isfinite(float(v)) else float(v) for v in frame[k].values] for k in frame.columns})

def before_trading(context):
    if get_datetime().strftime('%Y%m%d')!='20260904':raise ValueError('FIXED_CALLBACK')
    symbols=sorted(set(s for s,d in REQUESTS))
    fields=['open','high','low','close','volume','turnover','factor','is_st','is_paused','high_limit','low_limit']
    for offset in range(0,len(symbols),50):
        frames=get_price(symbols[offset:offset+50],'20180701','20191231','1d',fields,skip_paused=False,fq=None,is_panel=False)
        for s in symbols[offset:offset+50]:emit_packet('daily_'+s,dict(symbol=s,**packed(frames[s])))
    for day in sorted(set(d for s,d in REQUESTS)):
        ss=sorted(s for s,d in REQUESTS if d==day)
        frames=get_price(ss,day.replace('-',''),day+' 15:00:00','1m',['open','high','low','close','volume','turnover'],skip_paused=False,fq=None,is_panel=False)
        for s in ss:emit_packet('minute_'+day+'_'+s,dict(symbol=s,date=day,**packed(frames[s])))
    log.info('TECH1_ENTRY_MINUTE_EXPORT_DONE')

def handle_bar(context,bar_dict):pass
