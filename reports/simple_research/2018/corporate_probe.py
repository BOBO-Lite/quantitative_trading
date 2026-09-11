"""TECH1.0只读全池日线筛选；固定2019Q2，运行回调2026-09-04，不下单。"""
import base64,hashlib,json,zlib,math
import numpy as np

def emit_packet(key,value):
    raw=json.dumps(value,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('utf8')
    encoded=base64.b64encode(zlib.compress(raw)).decode('ascii')
    parts=[encoded[i:i+3000] for i in range(0,len(encoded),3000)]
    for i,part in enumerate(parts):log.info('MINBUNDLE {} {} {} {} {} {}'.format(key,i,len(parts),len(raw),hashlib.sha256(raw).hexdigest(),part))

SYMBOLS = ['000060.SZ', '000157.SZ', '000541.SZ', '000581.SZ', '000825.SZ', '000876.SZ', '000960.SZ', '000975.SZ', '002210.SZ', '002237.SZ', '002385.SZ', '002563.SZ', '002742.SZ', '600000.SH', '600023.SH', '600104.SH', '600129.SH', '600153.SH', '600177.SH', '600251.SH', '600308.SH', '600320.SH', '600398.SH', '600489.SH', '600547.SH', '600583.SH', '600707.SH', '600757.SH', '600771.SH', '601000.SH', '601009.SH', '601117.SH', '601166.SH', '601168.SH', '601668.SH', '601898.SH', '601997.SH', '603167.SH']

def init(context):set_benchmark('000905.SH')
def before_trading(context):
    if get_datetime().strftime('%Y%m%d')!='20260904':raise ValueError('FIXED_CALLBACK')
    for s in SYMBOLS:
        for kind in ['dividend','details']:
            try:
                if kind=='dividend':f=get_dividend_information(s,start_date='20180101',end_date='20181228')
                else:f=run_query(query(bonus).filter(bonus.symbol==s,bonus.ex_dividend_date>='2018-01-01',bonus.ex_dividend_date<='2018-12-28'))
                emit_packet(kind+'_'+s,dict(status='RETURNED',symbol=s,data=json.loads(f.to_json(date_format='iso'))))
            except Exception as exc:emit_packet(kind+'_'+s,dict(status='ERROR',symbol=s,error=str(exc)))
    log.info('TECH1_CORPORATE_EXPORT_DONE')
def handle_bar(context,bar_dict):pass
