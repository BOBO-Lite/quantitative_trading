"""TECH1.0只读全池日线筛选；固定2019Q2，运行回调2026-09-04，不下单。"""
import base64,hashlib,json,zlib,math
import numpy as np

def emit_packet(key,value):
    raw=json.dumps(value,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('utf8')
    encoded=base64.b64encode(zlib.compress(raw)).decode('ascii')
    parts=[encoded[i:i+3000] for i in range(0,len(encoded),3000)]
    for i,part in enumerate(parts):log.info('MINBUNDLE {} {} {} {} {} {}'.format(key,i,len(parts),len(raw),hashlib.sha256(raw).hexdigest(),part))

REQUESTS = [('000876.SZ', '2018-01-30'), ('000876.SZ', '2018-01-31'), ('000876.SZ', '2018-02-01'), ('000876.SZ', '2018-02-02'), ('000876.SZ', '2018-02-05'), ('000876.SZ', '2018-02-06'), ('000876.SZ', '2018-02-07'), ('000876.SZ', '2018-02-08'), ('000876.SZ', '2018-02-09'), ('000876.SZ', '2018-02-12'), ('000876.SZ', '2018-02-13'), ('000876.SZ', '2018-02-14'), ('000876.SZ', '2018-02-22'), ('000876.SZ', '2018-02-23'), ('000876.SZ', '2018-02-26'), ('000876.SZ', '2018-02-27'), ('000876.SZ', '2018-02-28'), ('000876.SZ', '2018-03-01'), ('000876.SZ', '2018-03-02'), ('000876.SZ', '2018-03-05'), ('000876.SZ', '2018-03-06'), ('000876.SZ', '2018-03-07'), ('000876.SZ', '2018-03-08'), ('000876.SZ', '2018-03-09'), ('000876.SZ', '2018-03-12'), ('000876.SZ', '2018-03-13'), ('000876.SZ', '2018-03-14'), ('000876.SZ', '2018-03-15'), ('000876.SZ', '2018-03-16'), ('000876.SZ', '2018-03-19'), ('601009.SH', '2018-01-30'), ('601009.SH', '2018-01-31'), ('601009.SH', '2018-02-01'), ('601009.SH', '2018-02-02'), ('601009.SH', '2018-02-05'), ('601009.SH', '2018-02-06'), ('601009.SH', '2018-02-07'), ('601009.SH', '2018-02-08'), ('601009.SH', '2018-02-09'), ('601009.SH', '2018-02-12'), ('601009.SH', '2018-02-13'), ('601009.SH', '2018-02-14'), ('601009.SH', '2018-02-22'), ('601009.SH', '2018-02-23'), ('601009.SH', '2018-02-26'), ('601009.SH', '2018-02-27'), ('601009.SH', '2018-02-28'), ('601009.SH', '2018-03-01'), ('601009.SH', '2018-03-02'), ('601009.SH', '2018-03-05'), ('601009.SH', '2018-03-06'), ('601009.SH', '2018-03-07'), ('601009.SH', '2018-03-08'), ('601009.SH', '2018-03-09'), ('601009.SH', '2018-03-12'), ('601009.SH', '2018-03-13'), ('601009.SH', '2018-03-14'), ('601009.SH', '2018-03-15'), ('601009.SH', '2018-03-16'), ('601009.SH', '2018-03-19')]

def init(context):set_benchmark('000905.SH')

def packed(frame):
    return dict(dates=[t.strftime('%Y-%m-%dT%H:%M:%S') for t in frame.index],data={k:[None if not math.isfinite(float(v)) else float(v) for v in frame[k].values] for k in frame.columns})

def before_trading(context):
    if get_datetime().strftime('%Y%m%d')!='20260904':raise ValueError('FIXED_CALLBACK')
    symbols=sorted(set(s for s,d in REQUESTS))
    fields=['open','high','low','close','volume','turnover','factor','is_st','is_paused','high_limit','low_limit']
    for offset in range(0,len(symbols),50):
        frames=get_price(symbols[offset:offset+50],'20170901','20181228','1d',fields,skip_paused=False,fq=None,is_panel=False)
        for s in symbols[offset:offset+50]:emit_packet('daily_'+s,dict(symbol=s,**packed(frames[s])))
    for day in sorted(set(d for s,d in REQUESTS)):
        ss=sorted(s for s,d in REQUESTS if d==day)
        frames=get_price(ss,day.replace('-',''),day+' 15:00:00','1m',['open','high','low','close','volume','turnover'],skip_paused=False,fq=None,is_panel=False)
        for s in ss:emit_packet('minute_'+day+'_'+s,dict(symbol=s,date=day,**packed(frames[s])))
    log.info('TECH1_ENTRY_MINUTE_EXPORT_DONE')

def handle_bar(context,bar_dict):pass
