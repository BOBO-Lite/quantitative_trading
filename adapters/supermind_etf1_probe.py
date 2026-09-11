"""ETF1固定标的历史数据能力探针；只读，不提交任何订单。"""
import base64, hashlib, json, zlib

SYMBOLS=['510300.SH','510500.SH']

def emit(key,value):
    raw=json.dumps(value,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('utf8')
    encoded=base64.b64encode(zlib.compress(raw)).decode('ascii')
    parts=[encoded[i:i+3000] for i in range(0,len(encoded),3000)]
    for i,part in enumerate(parts):log.info('MINBUNDLE {} {} {} {} {} {}'.format(key,i,len(parts),len(raw),hashlib.sha256(raw).hexdigest(),part))

def packet(frame):
    return json.loads(frame.to_json(date_format='iso'))

def init(context):set_benchmark('000300.SH')

def before_trading(context):
    if get_datetime().strftime('%Y%m%d')!='20260904':raise ValueError('FIXED_CALLBACK')
    for s in SYMBOLS:
        try:
            fields=['open','high','low','close','volume','turnover','factor','is_paused','high_limit','low_limit']
            f=get_price([s],'20170101','20221231','1d',fields,skip_paused=False,fq=None,is_panel=False)[s]
            emit('etf_daily_'+s,dict(symbol=s,status='RETURNED',data=packet(f)))
        except Exception as exc:emit('etf_daily_'+s,dict(symbol=s,status='ERROR',error=str(exc)))
        try:
            f=get_dividend_information(s,start_date='20170101',end_date='20221231')
            emit('etf_dividend_'+s,dict(symbol=s,status='RETURNED',data=packet(f)))
        except Exception as exc:emit('etf_dividend_'+s,dict(symbol=s,status='ERROR',error=str(exc)))
        try:
            f=get_price([s],'201901020935','201901020936','1m',['open','high','low','close','volume','turnover'],skip_paused=False,fq=None,is_panel=False)[s]
            emit('etf_minute_sample_'+s,dict(symbol=s,status='RETURNED',data=packet(f)))
        except Exception as exc:emit('etf_minute_sample_'+s,dict(symbol=s,status='ERROR',error=str(exc)))
    emit('etf_calendar',dict(data=packet(get_price(['000300.SH'],'20170101','20221231','1d',['close'],skip_paused=False,fq=None,is_panel=False)['000300.SH'])))
    log.info('ETF1_PROBE_DONE')

def handle_bar(context,bar_dict):pass
