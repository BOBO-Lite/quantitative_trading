"""TECH1.0只读全池日线筛选；固定2019Q2，运行回调2026-09-04，不下单。"""
import base64,hashlib,json,zlib,math
import numpy as np

def emit_packet(key,value):
    raw=json.dumps(value,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('utf8')
    encoded=base64.b64encode(zlib.compress(raw)).decode('ascii')
    parts=[encoded[i:i+3000] for i in range(0,len(encoded),3000)]
    for i,part in enumerate(parts):log.info('MINBUNDLE {} {} {} {} {} {}'.format(key,i,len(parts),len(raw),hashlib.sha256(raw).hexdigest(),part))

REQUESTS = [('000623.SZ', '2019-04-19'), ('000623.SZ', '2019-04-22'), ('000623.SZ', '2019-04-23'), ('000623.SZ', '2019-04-24'), ('000623.SZ', '2019-04-25'), ('000623.SZ', '2019-04-26'), ('000623.SZ', '2019-04-29'), ('000623.SZ', '2019-04-30'), ('000623.SZ', '2019-05-06'), ('000623.SZ', '2019-05-07'), ('000623.SZ', '2019-05-08'), ('000623.SZ', '2019-05-09'), ('000623.SZ', '2019-05-10'), ('000623.SZ', '2019-05-13'), ('000623.SZ', '2019-05-14'), ('000623.SZ', '2019-05-15'), ('000623.SZ', '2019-05-16'), ('000623.SZ', '2019-05-17'), ('000623.SZ', '2019-05-20'), ('000623.SZ', '2019-05-21'), ('000623.SZ', '2019-05-22'), ('000623.SZ', '2019-05-23'), ('000623.SZ', '2019-05-24'), ('000623.SZ', '2019-05-27'), ('000623.SZ', '2019-05-28'), ('000623.SZ', '2019-05-29'), ('000623.SZ', '2019-05-30'), ('000623.SZ', '2019-05-31'), ('000623.SZ', '2019-06-03'), ('000623.SZ', '2019-06-04'), ('000623.SZ', '2019-06-05'), ('000623.SZ', '2019-06-06'), ('000623.SZ', '2019-06-10'), ('000623.SZ', '2019-06-11'), ('000623.SZ', '2019-06-12'), ('000623.SZ', '2019-06-13'), ('000623.SZ', '2019-06-14'), ('000623.SZ', '2019-06-17'), ('000623.SZ', '2019-06-18'), ('000623.SZ', '2019-06-19'), ('000623.SZ', '2019-06-20'), ('000623.SZ', '2019-06-21'), ('000623.SZ', '2019-06-24'), ('000623.SZ', '2019-06-25'), ('000623.SZ', '2019-06-26'), ('000623.SZ', '2019-06-27'), ('000623.SZ', '2019-06-28'), ('601818.SH', '2019-04-19'), ('601818.SH', '2019-04-22'), ('601818.SH', '2019-04-23'), ('601818.SH', '2019-04-24'), ('601818.SH', '2019-04-25'), ('601818.SH', '2019-04-26'), ('601818.SH', '2019-04-29'), ('601818.SH', '2019-04-30'), ('601818.SH', '2019-05-06'), ('601818.SH', '2019-05-07'), ('601818.SH', '2019-05-08'), ('601818.SH', '2019-05-09'), ('601818.SH', '2019-05-10'), ('601818.SH', '2019-05-13'), ('601818.SH', '2019-05-14'), ('601818.SH', '2019-05-15'), ('601818.SH', '2019-05-16'), ('601818.SH', '2019-05-17'), ('601818.SH', '2019-05-20'), ('601818.SH', '2019-05-21'), ('601818.SH', '2019-05-22'), ('601818.SH', '2019-05-23'), ('601818.SH', '2019-05-24'), ('601818.SH', '2019-05-27'), ('601818.SH', '2019-05-28'), ('601818.SH', '2019-05-29'), ('601818.SH', '2019-05-30'), ('601818.SH', '2019-05-31'), ('601818.SH', '2019-06-03'), ('601818.SH', '2019-06-04'), ('601818.SH', '2019-06-05'), ('601818.SH', '2019-06-06'), ('601818.SH', '2019-06-10'), ('601818.SH', '2019-06-11'), ('601818.SH', '2019-06-12'), ('601818.SH', '2019-06-13'), ('601818.SH', '2019-06-14'), ('601818.SH', '2019-06-17'), ('601818.SH', '2019-06-18'), ('601818.SH', '2019-06-19'), ('601818.SH', '2019-06-20'), ('601818.SH', '2019-06-21'), ('601818.SH', '2019-06-24'), ('601818.SH', '2019-06-25'), ('601818.SH', '2019-06-26'), ('601818.SH', '2019-06-27'), ('601818.SH', '2019-06-28')]

def init(context):set_benchmark('000905.SH')

def packed(frame):
    return dict(dates=[t.strftime('%Y-%m-%dT%H:%M:%S') for t in frame.index],data={k:[None if not math.isfinite(float(v)) else float(v) for v in frame[k].values] for k in frame.columns})

def before_trading(context):
    if get_datetime().strftime('%Y%m%d')!='20260904':raise ValueError('FIXED_CALLBACK')
    symbols=sorted(set(s for s,d in REQUESTS))
    fields=['open','high','low','close','volume','turnover','factor','is_st','is_paused','high_limit','low_limit']
    for offset in range(0,len(symbols),50):
        frames=get_price(symbols[offset:offset+50],'20181201','20190628','1d',fields,skip_paused=False,fq=None,is_panel=False)
        for s in symbols[offset:offset+50]:emit_packet('daily_'+s,dict(symbol=s,**packed(frames[s])))
    for day in sorted(set(d for s,d in REQUESTS)):
        ss=sorted(s for s,d in REQUESTS if d==day)
        frames=get_price(ss,day.replace('-',''),day+' 15:00:00','1m',['open','high','low','close','volume','turnover'],skip_paused=False,fq=None,is_panel=False)
        for s in ss:emit_packet('minute_'+day+'_'+s,dict(symbol=s,date=day,**packed(frames[s])))
    log.info('TECH1_ENTRY_MINUTE_EXPORT_DONE')

def handle_bar(context,bar_dict):pass
