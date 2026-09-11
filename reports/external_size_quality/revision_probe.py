"""EXT-SIZEQ read-only PIT feasibility probe. No orders or trading signals."""
import base64, hashlib, json, zlib

SYMBOLS = ['000001.SZ', '000063.SZ', '000651.SZ', '002044.SZ', '600519.SH', '600270.SH']
DATES = ['20171229', '20180330', '20180420', '20180427', '20180502',
         '20180831', '20181031', '20181228', '20190426', '20190430',
         '20190506', '20190830', '20191031', '20191231', '20200424',
         '20200430', '20200506', '20200831', '20201030', '20201231']

def emit(key, value):
    raw = json.dumps(value, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode('utf8')
    encoded = base64.b64encode(zlib.compress(raw)).decode('ascii')
    parts = [encoded[i:i+3000] for i in range(0, len(encoded), 3000)]
    for i, part in enumerate(parts):
        log.info('MINBUNDLE {} {} {} {} {} {}'.format(key, i, len(parts), len(raw), hashlib.sha256(raw).hexdigest(), part))

def packet(frame):
    return json.loads(frame.to_json(orient='split', date_format='iso'))

def init(context):
    set_benchmark('000905.SH')

def before_trading(context):
    if get_datetime().strftime('%Y%m%d') != '20260904':
        raise ValueError('FIXED_READONLY_EXPORT_CALLBACK')
    tables = [('income', income), ('balance', balance), ('profit_sq', profit_sq)]
    for name, table in tables:
        for day in ['20180427', '20180502', '20180613', '20180727', '20180730', '20180801']:
            for latest in [False, True]:
                key = name+'_'+day+'_'+str(latest)
                try:
                    f = get_fundamentals(query(table).filter(table.symbol=='000063.SZ'), date=day, latest=latest)
                    emit(key, dict(status='RETURNED', date=day, latest=latest, data=packet(f)))
                except Exception as exc:
                    emit(key, dict(status='ERROR', error=str(exc)))
        try:
            f = run_query(query(table).filter(table.symbol=='000063.SZ', table.stat_date=='2018-03-31').limit(200))
            emit('raw_'+name, dict(status='RETURNED', limit=200, data=packet(f)))
        except Exception as exc:
            emit('raw_'+name, dict(status='ERROR', error=str(exc)))
    log.info('SIZEQ_REVISION_DONE')

def handle_bar(context, bar_dict):
    pass
