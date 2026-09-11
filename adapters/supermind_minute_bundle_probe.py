"""固定历史数据导出探针，无订单函数。只允许2019-04-17至22。

22日仅用于取得19日已完成日线核账。日志分块含长度及SHA256，缺字段保留null。
"""
import base64
import hashlib
import json
import zlib

SYMBOLS = ['600036.SH', '000001.SZ']
FIELDS = ['open', 'high', 'low', 'close', 'volume', 'turnover',
          'factor', 'is_st', 'is_paused', 'high_limit', 'low_limit']


def emit_packet(key, value):
    raw = json.dumps(value, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode('utf8')
    encoded = base64.b64encode(zlib.compress(raw)).decode('ascii')
    pieces = [encoded[i:i + 3000] for i in range(0, len(encoded), 3000)]
    digest = hashlib.sha256(raw).hexdigest()
    for index, piece in enumerate(pieces):
        log.info('MINBUNDLE {} {} {} {} {} {}'.format(key, index, len(pieces), len(raw), digest, piece))


def init(context):
    set_benchmark('000905.SH')
    subscribe(SYMBOLS)
    enable_open_bar()
    log.info('MINUTE_BUNDLE_READ_ONLY_V1')


def before_trading(context):
    day = get_datetime().strftime('%Y-%m-%d')
    if day not in ('2019-04-17', '2019-04-18', '2019-04-19', '2019-04-22'):
        raise ValueError('FIXED_HISTORICAL_EXPORT_ONLY')
    g.minute_rows = []
    for symbol in SYMBOLS:
        frame = history(symbol, FIELDS, 1, '1d', False, None, True, False)
        emit_packet(day + '_' + symbol + '_previous_daily', json.loads(frame.to_json(date_format='iso')))


def handle_bar(context, bar_dict):
    now = get_datetime()
    if now.strftime('%H:%M') < '09:31' or now.strftime('%Y-%m-%d') == '2019-04-22':
        return
    bars = get_current(SYMBOLS)
    for symbol in SYMBOLS:
        bar = bars[symbol]
        row = dict(symbol=symbol, datetime=now.strftime('%Y-%m-%dT%H:%M:%S'))
        # 平台静态沙箱禁止 getattr；日内不变字段由同日原始日线核补。
        row.update(open=float(bar.open), high=float(bar.high), low=float(bar.low),
                   close=float(bar.close), volume=float(bar.volume), turnover=float(bar.turnover),
                   high_limit=float(bar.high_limit), low_limit=float(bar.low_limit),
                   is_paused=bool(bar.is_paused), factor=None, is_st=None)
        g.minute_rows.append(row)


def after_trading(context):
    day = get_datetime().strftime('%Y-%m-%d')
    if day != '2019-04-22':
        emit_packet(day + '_minutes', g.minute_rows)
    log.info('MINBUNDLE_DAY_COMPLETE {} count={}'.format(day, len(g.minute_rows)))
