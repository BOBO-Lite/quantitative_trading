"""TECH1.0只读全池日线筛选；固定2019Q2，运行回调2026-09-04，不下单。"""
import base64,hashlib,json,zlib,math
import numpy as np

def emit_packet(key,value):
    raw=json.dumps(value,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('utf8')
    encoded=base64.b64encode(zlib.compress(raw)).decode('ascii')
    parts=[encoded[i:i+3000] for i in range(0,len(encoded),3000)]
    for i,part in enumerate(parts):log.info('MINBUNDLE {} {} {} {} {} {}'.format(key,i,len(parts),len(raw),hashlib.sha256(raw).hexdigest(),part))

REQUESTS = [('600337.SH', '2019-10-31'), ('600337.SH', '2019-11-01'), ('600337.SH', '2019-11-04'), ('600337.SH', '2019-11-05'), ('600337.SH', '2019-11-06'), ('600337.SH', '2019-11-07'), ('600337.SH', '2019-11-08'), ('600337.SH', '2019-11-11'), ('600337.SH', '2019-11-12'), ('600337.SH', '2019-11-13'), ('600337.SH', '2019-11-14'), ('600337.SH', '2019-11-15'), ('600337.SH', '2019-11-18'), ('600337.SH', '2019-11-19'), ('600337.SH', '2019-11-20'), ('600337.SH', '2019-11-21'), ('600337.SH', '2019-11-22'), ('600337.SH', '2019-11-25'), ('600337.SH', '2019-11-26'), ('600337.SH', '2019-11-27'), ('600337.SH', '2019-11-28'), ('600337.SH', '2019-11-29'), ('600337.SH', '2019-12-02'), ('600337.SH', '2019-12-03'), ('600337.SH', '2019-12-04'), ('600337.SH', '2019-12-05'), ('600337.SH', '2019-12-06'), ('601333.SH', '2019-10-31'), ('601333.SH', '2019-11-01'), ('601333.SH', '2019-11-04'), ('601333.SH', '2019-11-05'), ('601333.SH', '2019-11-06'), ('601333.SH', '2019-11-07'), ('601333.SH', '2019-11-08'), ('601333.SH', '2019-11-11'), ('601333.SH', '2019-11-12'), ('601333.SH', '2019-11-13'), ('601333.SH', '2019-11-14'), ('601333.SH', '2019-11-15'), ('601333.SH', '2019-11-18'), ('601333.SH', '2019-11-19'), ('601333.SH', '2019-11-20'), ('601333.SH', '2019-11-21'), ('601333.SH', '2019-11-22'), ('601333.SH', '2019-11-25'), ('601333.SH', '2019-11-26'), ('601333.SH', '2019-11-27'), ('601333.SH', '2019-11-28'), ('601333.SH', '2019-11-29'), ('601333.SH', '2019-12-02'), ('601333.SH', '2019-12-03'), ('601333.SH', '2019-12-04'), ('601333.SH', '2019-12-05'), ('601333.SH', '2019-12-06')]

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
