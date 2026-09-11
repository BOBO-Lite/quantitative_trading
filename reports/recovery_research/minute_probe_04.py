"""TECH1.0只读全池日线筛选；固定2019Q2，运行回调2026-09-04，不下单。"""
import base64,hashlib,json,zlib,math
import numpy as np

def emit_packet(key,value):
    raw=json.dumps(value,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('utf8')
    encoded=base64.b64encode(zlib.compress(raw)).decode('ascii')
    parts=[encoded[i:i+3000] for i in range(0,len(encoded),3000)]
    for i,part in enumerate(parts):log.info('MINBUNDLE {} {} {} {} {} {}'.format(key,i,len(parts),len(raw),hashlib.sha256(raw).hexdigest(),part))

REQUESTS = [('000423.SZ', '2019-04-25'), ('000423.SZ', '2019-04-26'), ('000423.SZ', '2019-04-29'), ('000423.SZ', '2019-04-30'), ('000423.SZ', '2019-05-06'), ('000423.SZ', '2019-05-07'), ('000423.SZ', '2019-05-08'), ('000423.SZ', '2019-05-09'), ('000423.SZ', '2019-05-10'), ('000423.SZ', '2019-05-13'), ('000423.SZ', '2019-05-14'), ('000423.SZ', '2019-05-15'), ('000423.SZ', '2019-05-16'), ('000423.SZ', '2019-05-17'), ('000423.SZ', '2019-05-20'), ('000423.SZ', '2019-05-21'), ('000423.SZ', '2019-05-22'), ('000423.SZ', '2019-05-23'), ('000423.SZ', '2019-05-24'), ('000423.SZ', '2019-05-27'), ('000423.SZ', '2019-05-28'), ('000423.SZ', '2019-05-29'), ('000423.SZ', '2019-05-30'), ('000423.SZ', '2019-05-31'), ('000423.SZ', '2019-06-03'), ('000423.SZ', '2019-06-04'), ('000423.SZ', '2019-06-05'), ('600000.SH', '2019-04-25'), ('600000.SH', '2019-04-26'), ('600000.SH', '2019-04-29'), ('600000.SH', '2019-04-30'), ('600000.SH', '2019-05-06'), ('600000.SH', '2019-05-07'), ('600000.SH', '2019-05-08'), ('600000.SH', '2019-05-09'), ('600000.SH', '2019-05-10'), ('600000.SH', '2019-05-13'), ('600000.SH', '2019-05-14'), ('600000.SH', '2019-05-15'), ('600000.SH', '2019-05-16'), ('600000.SH', '2019-05-17'), ('600000.SH', '2019-05-20'), ('600000.SH', '2019-05-21'), ('600000.SH', '2019-05-22'), ('600000.SH', '2019-05-23'), ('600000.SH', '2019-05-24'), ('600000.SH', '2019-05-27'), ('600000.SH', '2019-05-28'), ('600000.SH', '2019-05-29'), ('600000.SH', '2019-05-30'), ('600000.SH', '2019-05-31'), ('600000.SH', '2019-06-03'), ('600000.SH', '2019-06-04'), ('600000.SH', '2019-06-05'), ('600704.SH', '2019-04-25'), ('600704.SH', '2019-04-26'), ('600704.SH', '2019-04-29'), ('600704.SH', '2019-04-30'), ('600704.SH', '2019-05-06'), ('600704.SH', '2019-05-07'), ('600704.SH', '2019-05-08'), ('600704.SH', '2019-05-09'), ('600704.SH', '2019-05-10'), ('600704.SH', '2019-05-13'), ('600704.SH', '2019-05-14'), ('600704.SH', '2019-05-15'), ('600704.SH', '2019-05-16'), ('600704.SH', '2019-05-17'), ('600704.SH', '2019-05-20'), ('600704.SH', '2019-05-21'), ('600704.SH', '2019-05-22'), ('600704.SH', '2019-05-23'), ('600704.SH', '2019-05-24'), ('600704.SH', '2019-05-27'), ('600704.SH', '2019-05-28'), ('600704.SH', '2019-05-29'), ('600704.SH', '2019-05-30'), ('600704.SH', '2019-05-31'), ('600704.SH', '2019-06-03'), ('600704.SH', '2019-06-04'), ('600704.SH', '2019-06-05')]

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
