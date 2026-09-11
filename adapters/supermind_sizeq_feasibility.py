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
        'valuation': query(valuation.symbol, valuation.date, valuation.current_market_cap,
                           valuation.pe_ttm, valuation.circulating_cap).filter(valuation.symbol.in_(SYMBOLS)),
        'balance': query(balance.symbol, balance.date, balance.report_date, balance.stat_date,
                         balance.reporttypecode, balance.is_report_publish, balance.change_id,
                         balance.total_assets, balance.total_liabilities,
                         balance.total_quity_atsopc).filter(balance.symbol.in_(SYMBOLS)),
        'profit': query(profit.symbol, profit.date, profit.report_date, profit.stat_date,
                        profit.roe_ths, profit.weighted_roe,
                        profit.annualized_rate_of_return_on_net_assets).filter(profit.symbol.in_(SYMBOLS)),
        'cashflow': query(cashflow.symbol, cashflow.date, cashflow.report_date, cashflow.stat_date,
                          cashflow.reporttypecode, cashflow.is_report_publish, cashflow.change_id,
                          cashflow.net_cash_flows_from_opt_act).filter(cashflow.symbol.in_(SYMBOLS))
    }
    emit('config', dict(symbols=SYMBOLS, dates=DATES, latest=False, purpose='feasibility_only'))
    for day in DATES:
        for name, q in sorted(queries.items()):
            try:
                frame = get_fundamentals(q, date=day, latest=False)
                emit(name+'_'+day, dict(status='RETURNED', date=day, data=packet(frame)))
            except Exception as exc:
                emit(name+'_'+day, dict(status='ERROR', date=day, error=str(exc)))
    for day in ['20171229', '20191231', '20201231']:
        for code in ['000300.SH', '000905.SH', '000852.SH', '000001.SH', '399001.SZ',
                     '399006.SZ', '000016.SH', '000688.SH', '399330.SZ']:
            try:
                emit('index_'+code+'_'+day, dict(status='RETURNED', code=code, date=day,
                                                members=sorted(get_index_stocks(code, day))))
            except Exception as exc:
                emit('index_'+code+'_'+day, dict(status='ERROR', code=code, date=day, error=str(exc)))
    log.info('SIZEQ_FEASIBILITY_DONE')

def handle_bar(context, bar_dict):
    pass
