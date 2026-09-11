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
    queries = {
        'profit_sq': query(profit_sq).filter(profit_sq.symbol.in_(SYMBOLS)),
        'cashflow_sq': query(cashflow_sq).filter(cashflow_sq.symbol.in_(SYMBOLS))
    }
    emit('config', dict(symbols=SYMBOLS, dates=DATES, latest=False, purpose='quarter_semantics_only'))
    for day in DATES:
        for name, q in sorted(queries.items()):
            try:
                frame = get_fundamentals(q, date=day, latest=False)
                emit(name+'_'+day, dict(status='RETURNED', date=day, data=packet(frame)))
            except Exception as exc:
                emit(name+'_'+day, dict(status='ERROR', date=day, error=str(exc)))
    log.info('SIZEQ_QUARTER_DONE')

def handle_bar(context, bar_dict):
    pass
