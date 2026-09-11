"""只读公司行动窗口导出；不生成信号、不下单，运行日固定2019-04-22。"""
import base64, hashlib, json, zlib

def emit_packet(key,value):
    raw=json.dumps(value,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('utf8')
    encoded=base64.b64encode(zlib.compress(raw)).decode('ascii')
    parts=[encoded[i:i+3000] for i in range(0,len(encoded),3000)]
    for i,part in enumerate(parts):
        log.info('MINBUNDLE {} {} {} {} {} {}'.format(key,i,len(parts),len(raw),hashlib.sha256(raw).hexdigest(),part))

def init(context):
    set_benchmark('000905.SH')
    log.info('CORPORATE_ACTION_READ_ONLY_V1')

def before_trading(context):
    if get_datetime().strftime('%Y%m%d')!='20190422': return
    fields=['open','high','low','close','volume','turnover','factor','is_st','is_paused','high_limit','low_limit']
    for symbol,start,end in [('000001.SZ','20170720','20170724'),('000001.SZ','20180711','20180713'),('600036.SH','20170613','20170615'),('600036.SH','20180711','20180713')]:
        for freq in ['1m','1d']:
            key=symbol+'_'+start+'_'+freq
            try:
                requested=fields if freq=='1d' else ['open','high','low','close','volume','turnover']
                finish=end if freq=='1d' else end[:4]+'-'+end[4:6]+'-'+end[6:]+' 15:00:00'
                frame=get_price([symbol],start,finish,freq,requested,skip_paused=False,fq=None,is_panel=False)[symbol]
                emit_packet(key,{'status':'RETURNED','symbol':symbol,'frequency':freq,'start':start,'end':end,'columns':list(frame.columns),'data':json.loads(frame.to_json(date_format='iso'))})
            except Exception as exc:
                emit_packet(key,{'status':'ERROR','error':str(exc)})
    log.info('CORPORATE_ACTION_EXPORT_DONE')

def handle_bar(context,bar_dict): pass


