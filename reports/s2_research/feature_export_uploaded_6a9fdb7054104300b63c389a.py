"""只读特征历史导出；2019-04-22取此前160日日线，23日不导出。"""
import base64
import hashlib
import json
import zlib


def emit_packet(key, value):
    raw = json.dumps(value, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode('utf8')
    encoded = base64.b64encode(zlib.compress(raw)).decode('ascii')
    parts = [encoded[i:i + 3000] for i in range(0, len(encoded), 3000)]
    digest = hashlib.sha256(raw).hexdigest()
    for index, part in enumerate(parts):
        log.info('MINBUNDLE {} {} {} {} {} {}'.format(key, index, len(parts), len(raw), digest, part))


def init(context):
    set_benchmark('000905.SH')
    log.info('FEATURE_HISTORY_READ_ONLY_V1')


def before_trading(context):
    if get_datetime().strftime('%Y%m%d') == '20190423':
        return
    if get_datetime().strftime('%Y%m%d') != '20190422':
        raise ValueError('FEATURE_HISTORY_ONLY_20190422')
    fields = ['open', 'high', 'low', 'close', 'volume', 'turnover',
              'factor', 'is_st', 'is_paused', 'high_limit', 'low_limit']
    for symbol in ['600036.SH', '000001.SZ']:
        frame = history(symbol, fields, 160, '1d', False, None, True, False)
        emit_packet(symbol + '_raw_history', json.loads(frame.to_json(date_format='iso')))
    benchmark = history('000905.SH', ['close'], 160, '1d', False, None, True, False)
    emit_packet('000905.SH_benchmark', json.loads(benchmark.to_json(date_format='iso')))
    log.info('FEATURE_HISTORY_EXPORT_DONE')


def handle_bar(context, bar_dict):
    pass
