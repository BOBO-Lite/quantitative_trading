"""TECH1.0只读全池日线筛选；固定2019Q2，运行回调2026-09-04，不下单。"""
import base64,hashlib,json,zlib,math
import numpy as np

def emit_packet(key,value):
    raw=json.dumps(value,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('utf8')
    encoded=base64.b64encode(zlib.compress(raw)).decode('ascii')
    parts=[encoded[i:i+3000] for i in range(0,len(encoded),3000)]
    for i,part in enumerate(parts):log.info('MINBUNDLE {} {} {} {} {} {}'.format(key,i,len(parts),len(raw),hashlib.sha256(raw).hexdigest(),part))

REQUESTS = [('600388.SH', '2020-08-25'), ('600388.SH', '2020-08-26'), ('600388.SH', '2020-08-27'), ('600388.SH', '2020-08-28'), ('600388.SH', '2020-08-31'), ('600388.SH', '2020-09-01'), ('600388.SH', '2020-09-02'), ('600388.SH', '2020-09-03'), ('600388.SH', '2020-09-04'), ('600388.SH', '2020-09-07'), ('600388.SH', '2020-09-08'), ('600388.SH', '2020-09-09'), ('600388.SH', '2020-09-10'), ('600388.SH', '2020-09-11'), ('600388.SH', '2020-09-14'), ('600388.SH', '2020-09-15'), ('600388.SH', '2020-09-16'), ('600388.SH', '2020-09-17'), ('600388.SH', '2020-09-18'), ('600388.SH', '2020-09-21'), ('600388.SH', '2020-09-22'), ('600388.SH', '2020-09-23'), ('600388.SH', '2020-09-24'), ('600388.SH', '2020-09-25'), ('600388.SH', '2020-09-28'), ('600388.SH', '2020-09-29'), ('600388.SH', '2020-09-30')]

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
