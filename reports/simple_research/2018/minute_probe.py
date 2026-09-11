"""TECH1.0只读全池日线筛选；固定2019Q2，运行回调2026-09-04，不下单。"""
import base64,hashlib,json,zlib,math
import numpy as np

def emit_packet(key,value):
    raw=json.dumps(value,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('utf8')
    encoded=base64.b64encode(zlib.compress(raw)).decode('ascii')
    parts=[encoded[i:i+3000] for i in range(0,len(encoded),3000)]
    for i,part in enumerate(parts):log.info('MINBUNDLE {} {} {} {} {} {}'.format(key,i,len(parts),len(raw),hashlib.sha256(raw).hexdigest(),part))

REQUESTS = [('000060.SZ', '2018-01-26'), ('000157.SZ', '2018-01-26'), ('000541.SZ', '2018-01-29'), ('000581.SZ', '2018-01-29'), ('000825.SZ', '2018-01-26'), ('000876.SZ', '2018-01-29'), ('000960.SZ', '2018-01-29'), ('000975.SZ', '2018-01-26'), ('002210.SZ', '2018-01-26'), ('002237.SZ', '2018-01-26'), ('002385.SZ', '2018-01-26'), ('002563.SZ', '2018-01-29'), ('002742.SZ', '2018-01-26'), ('600000.SH', '2018-01-26'), ('600023.SH', '2018-01-29'), ('600104.SH', '2018-01-26'), ('600129.SH', '2018-01-26'), ('600153.SH', '2018-01-26'), ('600153.SH', '2018-01-29'), ('600177.SH', '2018-01-29'), ('600251.SH', '2018-01-29'), ('600308.SH', '2018-01-29'), ('600320.SH', '2018-01-26'), ('600398.SH', '2018-01-26'), ('600489.SH', '2018-01-26'), ('600547.SH', '2018-01-26'), ('600583.SH', '2018-01-26'), ('600707.SH', '2018-01-29'), ('600757.SH', '2018-01-26'), ('600771.SH', '2018-01-26'), ('601000.SH', '2018-01-26'), ('601009.SH', '2018-01-26'), ('601009.SH', '2018-01-29'), ('601117.SH', '2018-01-29'), ('601166.SH', '2018-01-29'), ('601168.SH', '2018-01-26'), ('601668.SH', '2018-01-29'), ('601898.SH', '2018-01-26'), ('601997.SH', '2018-01-26'), ('601997.SH', '2018-01-29'), ('603167.SH', '2018-01-29')]

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
