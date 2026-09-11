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
    asof='2017-12-29'
    batch=['000043.SZ','001914.SZ']
    q=query(valuation.symbol,valuation.date,valuation.pe_ttm,valuation.current_market_cap,valuation.circulating_cap).filter(valuation.symbol.in_(batch))
    emit('valuation',packet(get_fundamentals(q,date='20171229')))
    frames=get_price(batch,'20171229','20171229','1d',['close','is_st','is_paused'],skip_paused=False,fq=None,is_panel=False)
    emit('prices',{s:packet(frames[s]) for s in batch})
    queries={
      'income':query(income.symbol,income.report_date,income.stat_date,income.np_atsopc).filter(income.symbol.in_(batch),income.report_date<=asof),
      'balance':query(balance.symbol,balance.report_date,balance.stat_date,balance.total_assets,balance.total_liabilities,balance.total_quity_atsopc).filter(balance.symbol.in_(batch),balance.report_date<=asof),
      'cashflow':query(cashflow.symbol,cashflow.report_date,cashflow.stat_date,cashflow.net_cash_flows_from_opt_act).filter(cashflow.symbol.in_(batch),cashflow.report_date<=asof)
    }
    for quarter in ['2017q2','2017q3']:
        for name,q in sorted(queries.items()):
            emit(name+'_'+quarter,packet(get_fundamentals(q,statDate=quarter,latest=True)))
    log.info('SIZEQ_ALIAS_DONE')

def handle_bar(context, bar_dict):
    pass
