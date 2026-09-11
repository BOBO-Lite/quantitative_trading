"""历史日线技术特征：按信号日截断，禁止跨因子窗口直接混用原始价格。

本模块不推断财报已知时间、股票池完整性或行业排名，缺失时明确封闭开仓。
RSI使用14日简单平均涨跌幅（Cutler口径），ATR20使用20日简单TR均值。
"""
import argparse
import hashlib
import json
from math import isfinite
from pathlib import Path
from statistics import mean

from import_supermind_minute_probe import decode_packets


def packet_rows(frame):
    stamps = sorted(frame['close'])
    if any(set(values) != set(stamps) for values in frame.values()):
        raise ValueError('日线字段日期集合不一致')
    rows = [dict(date=stamp[:10], **{key: values[stamp] for key, values in frame.items()}) for stamp in stamps]
    if len({r['date'] for r in rows}) != len(rows):
        raise ValueError('日线同日期重复')
    return rows


def through(rows, asof, minimum):
    # 必须先截断；调用者提供的未来记录不能参与合法性判断或过去窗口计算。
    selected = sorted((dict(r) for r in rows if r['date'] <= asof), key=lambda r: r['date'])
    if len(selected) < minimum or selected[-1]['date'] != asof:
        raise ValueError('历史长度不足或缺少信号日日线')
    if len({r['date'] for r in selected}) != len(selected):
        raise ValueError('历史日期重复')
    return selected


def benchmark_features(rows, asof):
    selected = through(rows, asof, 61)
    closes = [r['close'] for r in selected]
    if any(v is None or not isfinite(v) or v <= 0 for v in closes):
        raise ValueError('基准收盘数据非法')
    m20 = mean(closes[-20:])
    return dict(close=closes[-1], ma20=m20, ma60=mean(closes[-60:]),
                slope5=m20 / mean(closes[-25:-5]) - 1,
                ret20=closes[-1] / closes[-21] - 1, ret60=closes[-1] / closes[-61] - 1)


def stock_features(rows, benchmark_rows, asof, symbol):
    selected = through(rows, asof, 120)
    observed_bars = sum(r.get('close') is not None and isfinite(r['close']) and r['close'] > 0 for r in selected)
    if observed_bars < 120:
        raise ValueError('有效上市行情不足120根，不能计入上市前空记录')
    benchmark = through(benchmark_rows, asof, 61)
    if [r['date'] for r in selected[-61:]] != [r['date'] for r in benchmark[-61:]]:
        raise ValueError('股票日线与基准交易日不一致；不能把缺行当作停牌')
    window = selected[-61:]
    for row in window:
        for key in ('open', 'high', 'low', 'close', 'factor', 'high_limit', 'low_limit'):
            if row.get(key) is None or not isfinite(row[key]) or row[key] <= 0:
                raise ValueError('缺少有效历史字段：' + key)
        for key in ('volume', 'turnover'):
            if row.get(key) is None or not isfinite(row[key]) or row[key] < 0:
                raise ValueError('量额字段非法')
        if row.get('is_st') not in (False, True, 0, 1) or row.get('is_paused') not in (False, True, 0, 1):
            raise ValueError('历史状态缺失')
        if row['low'] > min(row['open'], row['close']) or row['high'] < max(row['open'], row['close']):
            raise ValueError('日线OHLC关系错误')
    if any(r['factor'] != window[-1]['factor'] for r in window):
        raise ValueError('CORPORATE_ACTION_WINDOW_REQUIRES_NORMALIZATION')
    closes = [r['close'] for r in window]
    last = window[-1]
    prior = window[-21:-1]
    prior_volume = mean(r['volume'] for r in prior)
    if prior_volume <= 0 or last['high'] == last['low']:
        raise ValueError('量比或收盘位置不可计算')
    changes = [closes[i] - closes[i-1] for i in range(len(closes)-14, len(closes))]
    gains, losses = mean(max(0., v) for v in changes), mean(max(0., -v) for v in changes)
    rsi = 50. if gains + losses == 0 else 100 * gains / (gains + losses)
    tr = [max(window[i]['high'] - window[i]['low'], abs(window[i]['high'] - closes[i-1]),
              abs(window[i]['low'] - closes[i-1])) for i in range(len(window)-20, len(window))]
    bm = benchmark_features(benchmark_rows, asof)
    technical = dict(symbol=symbol, date=asof, is_st=bool(last['is_st']), is_paused=bool(last['is_paused']),
        listing_bars=observed_bars, amount20=mean(r['turnover'] for r in prior),
        close=last['close'], ma20=mean(closes[-20:]), ma60=mean(closes[-60:]),
        ma20_previous=mean(closes[-25:-5]), previous_close=closes[-2],
        prior_breakout_close=max(r['close'] for r in prior), volume_ratio=last['volume'] / prior_volume,
        close_location=(last['close'] - last['low']) / (last['high'] - last['low']),
        compression10=max(r['high'] for r in window[-11:-1]) / min(r['low'] for r in window[-11:-1]) - 1,
        rsi14=rsi, ret20=closes[-1] / closes[-21] - 1, ret60=closes[-1] / closes[-61] - 1,
        excess_ret20=closes[-1] / closes[-21] - 1 - bm['ret20'],
        raw_close=last['close'], raw_high=last['high'], factor=last['factor'],
        structure_low_raw=min(r['low'] for r in window[-11:-1]), atr20_raw=mean(tr),
        ma10_raw=mean(closes[-10:]), target_ma20_raw=mean(closes[-20:]),
        event_clear=False, pit_verified=False, rs_percentile=None, industry=None,
        blockers=['HISTORICAL_EVENT_CALENDAR_MISSING', 'FULL_PIT_UNIVERSE_RANKING_MISSING',
                  'PIT_INDUSTRY_FEATURES_MISSING'],
        feature_status='TECHNICAL_FEATURES_ONLY', price_basis='raw_constant_factor_window')
    return technical


def build_feature_report(packets, dates):
    bm = packet_rows(packets['000905.SH_benchmark'])
    histories = {symbol: packet_rows(packets[symbol + '_raw_history']) for symbol in ('000001.SZ', '600036.SH')}
    days = []
    for date in dates:
        rows, errors = [], []
        for symbol, history in histories.items():
            try:
                rows.append(stock_features(history, bm, date, symbol))
            except ValueError as exc:
                errors.append(dict(symbol=symbol, error=str(exc)))
        days.append(dict(date=date, benchmark=benchmark_features(bm, date), stocks=rows, errors=errors))
    return dict(status='TECHNICAL_FEATURES_ONLY_NOT_ENTRY_READY', formal_strategy_validated=False,
                stock_history_lengths={s: len(h) for s, h in histories.items()},
                benchmark_history_length=len(bm), days=days)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--log', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    raw = Path(args.log).read_bytes()
    result = build_feature_report(decode_packets(raw.decode('utf-8')),
                                  ['2019-04-16', '2019-04-17', '2019-04-18', '2019-04-19'])
    result['source_log_sha256'] = hashlib.sha256(raw).hexdigest()
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(dict(status=result['status'], computed_rows=sum(len(d['stocks']) for d in result['days']),
                         errors=[e for d in result['days'] for e in d['errors']]), ensure_ascii=False))


if __name__ == '__main__':
    main()
