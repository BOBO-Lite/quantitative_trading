"""只读数据能力探针：不生成策略信号，不下单；固定2019-04-22运行。"""
import base64
import hashlib
import json
import zlib


def emit_packet(key, value):
    raw = json.dumps(value, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode('utf8')
    encoded = base64.b64encode(zlib.compress(raw)).decode('ascii')
    parts = [encoded[i:i + 3000] for i in range(0, len(encoded), 3000)]
    for index, part in enumerate(parts):
        log.info('MINBUNDLE {} {} {} {} {} {}'.format(
            key, index, len(parts), len(raw), hashlib.sha256(raw).hexdigest(), part))


def init(context):
    set_benchmark('000905.SH')
    log.info('DATA_FEASIBILITY_READ_ONLY_V2')


def before_trading(context):
    today = get_datetime().strftime('%Y%m%d')
    if today == '20190423':
        return
    if today != '20190422':
        raise ValueError('DATA_FEASIBILITY_ONLY_20190422')
    for symbol in ['000001.SZ', '600036.SH']:
        try:
            frame = get_dividend_information(symbol, start_date='20170101', end_date='20190419')
            emit_packet(symbol + '_dividend', {'status': 'RETURNED', 'columns': list(frame.columns),
                        'data': json.loads(frame.to_json(date_format='iso')),
                        'purpose': 'CAPABILITY_ONLY_NOT_PIT_SIGNAL'})
        except Exception as exc:
            emit_packet(symbol + '_dividend', {'status': 'ERROR', 'error': str(exc)})
        try:
            details = run_query(query(bonus).filter(
                bonus.symbol == symbol, bonus.ex_dividend_date >= '2017-01-01',
                bonus.ex_dividend_date <= '2019-04-19'))
            emit_packet(symbol + '_dividend_details', {'status': 'RETURNED',
                        'columns': list(details.columns),
                        'data': json.loads(details.to_json(date_format='iso')),
                        'purpose': 'CAPABILITY_ONLY_NOT_PIT_SIGNAL'})
        except Exception as exc:
            emit_packet(symbol + '_dividend_details', {'status': 'ERROR', 'error': str(exc)})
    fields = ['open', 'high', 'low', 'close', 'volume', 'turnover',
              'factor', 'is_st', 'is_paused', 'high_limit', 'low_limit']
    try:
        prices = get_price(['000939.SZ'], '20180101', '20181231', '1d', fields,
                           skip_paused=False, fq=None, is_panel=False)
        frame = prices['000939.SZ']
        emit_packet('000939.SZ_historical_daily', {'status': 'RETURNED', 'columns': list(frame.columns),
                    'data': json.loads(frame.to_json(date_format='iso'))})
    except Exception as exc:
        emit_packet('000939.SZ_historical_daily', {'status': 'ERROR', 'error': str(exc)})
    log.info('DATA_FEASIBILITY_EXPORT_DONE')


def handle_bar(context, bar_dict):
    pass
