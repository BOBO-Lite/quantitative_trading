"""TECH1.0只读全池日线筛选；固定2019Q2，运行回调2026-09-04，不下单。"""
import base64,hashlib,json,zlib,math
import numpy as np

def emit_packet(key,value):
    raw=json.dumps(value,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('utf8')
    encoded=base64.b64encode(zlib.compress(raw)).decode('ascii')
    parts=[encoded[i:i+3000] for i in range(0,len(encoded),3000)]
    for i,part in enumerate(parts):log.info('MINBUNDLE {} {} {} {} {} {}'.format(key,i,len(parts),len(raw),hashlib.sha256(raw).hexdigest(),part))

REQUESTS = [('600741.SH', '2020-07-03'), ('600741.SH', '2020-07-06'), ('600741.SH', '2020-07-07'), ('600741.SH', '2020-07-08'), ('600741.SH', '2020-07-09'), ('600741.SH', '2020-07-10'), ('600741.SH', '2020-07-13'), ('600741.SH', '2020-07-14'), ('600741.SH', '2020-07-15'), ('600741.SH', '2020-07-16'), ('600741.SH', '2020-07-17'), ('600741.SH', '2020-07-20'), ('600741.SH', '2020-07-21'), ('600741.SH', '2020-07-22'), ('600741.SH', '2020-07-23'), ('600741.SH', '2020-07-24'), ('600741.SH', '2020-07-27'), ('600741.SH', '2020-07-28'), ('600741.SH', '2020-07-29'), ('600741.SH', '2020-07-30'), ('600741.SH', '2020-07-31'), ('600741.SH', '2020-08-03'), ('600741.SH', '2020-08-04'), ('600741.SH', '2020-08-05'), ('600741.SH', '2020-08-06'), ('600741.SH', '2020-08-07'), ('600741.SH', '2020-08-10')]

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
