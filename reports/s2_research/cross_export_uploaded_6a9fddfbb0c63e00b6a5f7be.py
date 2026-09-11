"""只读导出2019-04-16至18的完整历史主板横截面；运行17至19日盘前。"""
import base64
import hashlib
import json
import zlib
import numpy as np


def emit_packet(key, value):
    raw = json.dumps(value, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode('utf8')
    encoded = base64.b64encode(zlib.compress(raw)).decode('ascii')
    parts = [encoded[i:i + 3000] for i in range(0, len(encoded), 3000)]
    digest = hashlib.sha256(raw).hexdigest()
    for index, part in enumerate(parts):
        log.info('MINBUNDLE {} {} {} {} {} {}'.format(key, index, len(parts), len(raw), digest, part))


def init(context):
    set_benchmark('000905.SH')
    log.info('CROSS_SECTION_READ_ONLY_V1; NO ORDERS')


def before_trading(context):
    today = get_datetime().strftime('%Y%m%d')
    dates = {'20190417': '2019-04-16', '20190418': '2019-04-17', '20190419': '2019-04-18'}
    if today not in dates:
        raise ValueError('CROSS_SECTION_FIXED_DATES_ONLY')
    asof = dates[today]
    universe = get_all_securities('stock', asof.replace('-', ''))
    symbols = sorted(str(s) for s in universe.index if str(s).startswith(('000', '001', '002', '003', '600', '601', '603', '605'))
                     and str(s).endswith(('.SH', '.SZ')))
    benchmark = history('000905.SH', ['close'], 61, '1d', False, 'pre', True, False)
    bm = benchmark['close'].values.astype(float)
    if len(bm) != 61 or not np.isfinite(bm).all() or benchmark.index[-1].strftime('%Y-%m-%d') != asof:
        raise ValueError('BENCHMARK_DATE_OR_HISTORY_INVALID')
    benchmark_ret20 = float(bm[-1] / bm[-21] - 1)
    frames = history(symbols, ['close', 'turnover', 'is_st', 'is_paused'], 121, '1d', False, 'pre', True, False)
    rows = []
    for symbol in symbols:
        row = dict(symbol=symbol, date=asof, eligible=False, reason=None)
        frame = frames.get(symbol)
        if frame is None or frame.empty:
            row['reason'] = 'MISSING_HISTORY'
        else:
            frame = frame.sort_index()
            close = frame['close'].values.astype(float)
            amount = frame['turnover'].values.astype(float)
            row['observed_bars'] = int(np.isfinite(close).sum())
            if row['observed_bars'] < 120:
                row['reason'] = 'SHORT_LISTING_HISTORY'
            elif frame.index[-1].strftime('%Y-%m-%d') != asof or not np.isfinite(close[-61:]).all() or min(close[-61:]) <= 0:
                row['reason'] = 'INVALID_HISTORY'
            elif not np.isfinite(amount[-21:-1]).all():
                row['reason'] = 'INVALID_TURNOVER'
            elif not np.isfinite(float(frame['is_st'].iloc[-1])) or not np.isfinite(float(frame['is_paused'].iloc[-1])):
                row['reason'] = 'MISSING_STATE'
            else:
                row.update(is_st=bool(frame['is_st'].iloc[-1]), is_paused=bool(frame['is_paused'].iloc[-1]),
                           amount20=float(amount[-21:-1].mean()), ret20=float(close[-1] / close[-21] - 1),
                           ret60=float(close[-1] / close[-61] - 1))
                row['reason'] = ('ST' if row['is_st'] else 'PAUSED' if row['is_paused'] else
                                 'LOW_LIQUIDITY' if row['amount20'] < 50000000 else 'ELIGIBLE')
                row['eligible'] = row['reason'] == 'ELIGIBLE'
        rows.append(row)
    emit_packet(asof + '_cross_section', dict(date=asof, universe_asof=asof,
        source='get_all_securities(stock, historical_date)', benchmark_ret20=benchmark_ret20,
        expected_symbols=symbols, rows=rows, price_basis='pre_adjusted_history_asof_callback'))
    log.info('CROSS_SECTION_DONE {} universe={}'.format(asof, len(symbols)))


def handle_bar(context, bar_dict):
    pass
