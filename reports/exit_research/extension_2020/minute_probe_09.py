"""TECH1.0只读全池日线筛选；固定2019Q2，运行回调2026-09-04，不下单。"""
import base64,hashlib,json,zlib,math
import numpy as np

def emit_packet(key,value):
    raw=json.dumps(value,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('utf8')
    encoded=base64.b64encode(zlib.compress(raw)).decode('ascii')
    parts=[encoded[i:i+3000] for i in range(0,len(encoded),3000)]
    for i,part in enumerate(parts):log.info('MINBUNDLE {} {} {} {} {} {}'.format(key,i,len(parts),len(raw),hashlib.sha256(raw).hexdigest(),part))

REQUESTS = [('000726.SZ', '2020-03-10'), ('000726.SZ', '2020-03-11'), ('000726.SZ', '2020-03-12'), ('000726.SZ', '2020-03-13'), ('000726.SZ', '2020-03-16'), ('000726.SZ', '2020-03-17'), ('000726.SZ', '2020-03-18'), ('000726.SZ', '2020-03-19'), ('000726.SZ', '2020-03-20'), ('000726.SZ', '2020-03-23'), ('000726.SZ', '2020-03-24'), ('000726.SZ', '2020-03-25'), ('000726.SZ', '2020-03-26'), ('000726.SZ', '2020-03-27'), ('000726.SZ', '2020-03-30'), ('000726.SZ', '2020-03-31'), ('000726.SZ', '2020-04-01'), ('000726.SZ', '2020-04-02'), ('000726.SZ', '2020-04-03'), ('000726.SZ', '2020-04-07'), ('000726.SZ', '2020-04-08'), ('000726.SZ', '2020-04-09'), ('000726.SZ', '2020-04-10'), ('000726.SZ', '2020-04-13'), ('000726.SZ', '2020-04-14'), ('000726.SZ', '2020-04-15'), ('000726.SZ', '2020-04-16'), ('002262.SZ', '2020-03-10'), ('002262.SZ', '2020-03-11'), ('002262.SZ', '2020-03-12'), ('002262.SZ', '2020-03-13'), ('002262.SZ', '2020-03-16'), ('002262.SZ', '2020-03-17'), ('002262.SZ', '2020-03-18'), ('002262.SZ', '2020-03-19'), ('002262.SZ', '2020-03-20'), ('002262.SZ', '2020-03-23'), ('002262.SZ', '2020-03-24'), ('002262.SZ', '2020-03-25'), ('002262.SZ', '2020-03-26'), ('002262.SZ', '2020-03-27'), ('002262.SZ', '2020-03-30'), ('002262.SZ', '2020-03-31'), ('002262.SZ', '2020-04-01'), ('002262.SZ', '2020-04-02'), ('002262.SZ', '2020-04-03'), ('002262.SZ', '2020-04-07'), ('002262.SZ', '2020-04-08'), ('002262.SZ', '2020-04-09'), ('002262.SZ', '2020-04-10'), ('002262.SZ', '2020-04-13'), ('002262.SZ', '2020-04-14'), ('002262.SZ', '2020-04-15'), ('002262.SZ', '2020-04-16'), ('600873.SH', '2020-03-10'), ('600873.SH', '2020-03-11'), ('600873.SH', '2020-03-12'), ('600873.SH', '2020-03-13'), ('600873.SH', '2020-03-16'), ('600873.SH', '2020-03-17'), ('600873.SH', '2020-03-18'), ('600873.SH', '2020-03-19'), ('600873.SH', '2020-03-20'), ('600873.SH', '2020-03-23'), ('600873.SH', '2020-03-24'), ('600873.SH', '2020-03-25'), ('600873.SH', '2020-03-26'), ('600873.SH', '2020-03-27'), ('600873.SH', '2020-03-30'), ('600873.SH', '2020-03-31'), ('600873.SH', '2020-04-01'), ('600873.SH', '2020-04-02'), ('600873.SH', '2020-04-03'), ('600873.SH', '2020-04-07'), ('600873.SH', '2020-04-08'), ('600873.SH', '2020-04-09'), ('600873.SH', '2020-04-10'), ('600873.SH', '2020-04-13'), ('600873.SH', '2020-04-14'), ('600873.SH', '2020-04-15'), ('600873.SH', '2020-04-16')]

def init(context):set_benchmark('000905.SH')

def packed(frame):
    return dict(dates=[t.strftime('%Y-%m-%dT%H:%M:%S') for t in frame.index],data={k:[None if not math.isfinite(float(v)) else float(v) for v in frame[k].values] for k in frame.columns})

def before_trading(context):
    if get_datetime().strftime('%Y%m%d')!='20260904':raise ValueError('FIXED_CALLBACK')
    symbols=sorted(set(s for s,d in REQUESTS))
    fields=['open','high','low','close','volume','turnover','factor','is_st','is_paused','high_limit','low_limit']
    for offset in range(0,len(symbols),50):
        frames=get_price(symbols[offset:offset+50],'20190701','20201231','1d',fields,skip_paused=False,fq=None,is_panel=False)
        for s in symbols[offset:offset+50]:emit_packet('daily_'+s,dict(symbol=s,**packed(frames[s])))
    for day in sorted(set(d for s,d in REQUESTS)):
        ss=sorted(s for s,d in REQUESTS if d==day)
        frames=get_price(ss,day.replace('-',''),day+' 15:00:00','1m',['open','high','low','close','volume','turnover'],skip_paused=False,fq=None,is_panel=False)
        for s in ss:emit_packet('minute_'+day+'_'+s,dict(symbol=s,date=day,**packed(frames[s])))
    log.info('TECH1_ENTRY_MINUTE_EXPORT_DONE')

def handle_bar(context,bar_dict):pass
