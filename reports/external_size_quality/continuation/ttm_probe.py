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
    symbols=['000063.SZ','600519.SH','000651.SZ','000001.SZ','002346.SZ','603060.SH']
    for asof in ['2017-12-29','2018-05-02','2018-07-27','2018-07-30']:
        q=query(valuation.symbol,valuation.date,valuation.pe_ttm,valuation.market_cap,valuation.capitalization,valuation.circulating_cap).filter(valuation.symbol.in_(symbols))
        emit('valuation_'+asof,packet(get_fundamentals(q,date=asof.replace('-',''))))
        for quarter in ['2016q3','2016q4','2017q1','2017q2','2017q3','2017q4','2018q1','2018q2']:
            q=query(income.symbol,income.report_date,income.stat_date,income.np_atsopc).filter(income.symbol.in_(symbols),income.report_date<=asof)
            emit('income_'+asof+'_'+quarter,packet(get_fundamentals(q,statDate=quarter,latest=True)))
    log.info('SIZEQ_TTM_DONE')

def handle_bar(context, bar_dict):
    pass
