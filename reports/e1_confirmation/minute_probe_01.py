"""TECH1.0只读全池日线筛选；固定2019Q2，运行回调2026-09-04，不下单。"""
import base64,hashlib,json,zlib,math
import numpy as np

def emit_packet(key,value):
    raw=json.dumps(value,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('utf8')
    encoded=base64.b64encode(zlib.compress(raw)).decode('ascii')
    parts=[encoded[i:i+3000] for i in range(0,len(encoded),3000)]
    for i,part in enumerate(parts):log.info('MINBUNDLE {} {} {} {} {} {}'.format(key,i,len(parts),len(raw),hashlib.sha256(raw).hexdigest(),part))

REQUESTS = [('000555.SZ', '2020-01-02'), ('000555.SZ', '2020-01-03'), ('000555.SZ', '2020-01-06'), ('000555.SZ', '2020-01-07'), ('000555.SZ', '2020-01-08'), ('000555.SZ', '2020-01-09'), ('000555.SZ', '2020-01-10'), ('000555.SZ', '2020-01-13'), ('000555.SZ', '2020-01-14'), ('000555.SZ', '2020-01-15'), ('000555.SZ', '2020-01-16'), ('000555.SZ', '2020-01-17'), ('000555.SZ', '2020-01-20'), ('000555.SZ', '2020-01-21'), ('000555.SZ', '2020-01-22'), ('000555.SZ', '2020-01-23'), ('000555.SZ', '2020-02-03'), ('000555.SZ', '2020-02-04'), ('000555.SZ', '2020-02-05'), ('000555.SZ', '2020-02-06'), ('000555.SZ', '2020-02-07'), ('000555.SZ', '2020-02-10'), ('000555.SZ', '2020-02-11'), ('000555.SZ', '2020-02-12'), ('000555.SZ', '2020-02-13'), ('000555.SZ', '2020-02-14'), ('000555.SZ', '2020-02-17'), ('600118.SH', '2020-01-10'), ('600118.SH', '2020-01-13'), ('600118.SH', '2020-01-14'), ('600118.SH', '2020-01-15'), ('600118.SH', '2020-01-16'), ('600118.SH', '2020-01-17'), ('600118.SH', '2020-01-20'), ('600118.SH', '2020-01-21'), ('600118.SH', '2020-01-22'), ('600118.SH', '2020-01-23'), ('600118.SH', '2020-02-03'), ('600118.SH', '2020-02-04'), ('600118.SH', '2020-02-05'), ('600118.SH', '2020-02-06'), ('600118.SH', '2020-02-07'), ('600118.SH', '2020-02-10'), ('600118.SH', '2020-02-11'), ('600118.SH', '2020-02-12'), ('600118.SH', '2020-02-13'), ('600118.SH', '2020-02-14'), ('600118.SH', '2020-02-17'), ('600118.SH', '2020-02-18'), ('600118.SH', '2020-02-19'), ('600118.SH', '2020-02-20'), ('600118.SH', '2020-02-21'), ('600118.SH', '2020-02-24'), ('600118.SH', '2020-02-25'), ('600309.SH', '2020-01-02'), ('600309.SH', '2020-01-03'), ('600309.SH', '2020-01-06'), ('600309.SH', '2020-01-07'), ('600309.SH', '2020-01-08'), ('600309.SH', '2020-01-09'), ('600309.SH', '2020-01-10'), ('600309.SH', '2020-01-13'), ('600309.SH', '2020-01-14'), ('600309.SH', '2020-01-15'), ('600309.SH', '2020-01-16'), ('600309.SH', '2020-01-17'), ('600309.SH', '2020-01-20'), ('600309.SH', '2020-01-21'), ('600309.SH', '2020-01-22'), ('600309.SH', '2020-01-23'), ('600309.SH', '2020-02-03'), ('600309.SH', '2020-02-04'), ('600309.SH', '2020-02-05'), ('600309.SH', '2020-02-06'), ('600309.SH', '2020-02-07'), ('600309.SH', '2020-02-10'), ('600309.SH', '2020-02-11'), ('600309.SH', '2020-02-12'), ('600309.SH', '2020-02-13'), ('600309.SH', '2020-02-14'), ('600309.SH', '2020-02-17')]

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
