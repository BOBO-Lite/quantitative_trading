"""将真实技术特征和分钟样本连接；缺少事件/全池证据时仅验证失败关闭流程。"""
import argparse
import hashlib
import json
from pathlib import Path

from research_portfolio import run_bundle


def build_bundle(features, minutes):
    if minutes['status'] != 'PASS_FIXED_SAMPLE_MINUTE_DATA':
        raise ValueError('分钟样本未通过核验')
    rows_by_day = {d['date']: d for d in features['days']}
    calendar = ['2019-04-16'] + minutes['dates']
    if len(rows_by_day) != len(features['days']) or set(calendar) != set(rows_by_day):
        raise ValueError('特征交易日覆盖不完整或重复')
    if any(d['errors'] for d in features['days']):
        raise ValueError('技术特征计算存在错误，不能构造回放包')
    grouped = {}
    for row in minutes['rows']:
        batch = grouped.setdefault(row['datetime'], {})
        if row['symbol'] in batch:
            raise ValueError('重复分钟股票记录')
        batch[row['symbol']] = dict(row)
    days, gates = [], []
    for i, day in enumerate(calendar[1:], 1):
        previous = rows_by_day[calendar[i-1]]
        closing = rows_by_day[day]
        if {r['symbol'] for r in previous['stocks']} != set(minutes['symbols']):
            raise ValueError('特征股票覆盖不一致')
        for r in previous['stocks']:
            # 当前桥接器仅用于证据缺失的真实样本；不能意外转换为正式开仓运行。
            if r['event_clear'] or r['pit_verified'] or not r['blockers']:
                raise ValueError('本桥接器只接受未通过证据门禁的样本')
            gates.append(dict(date=previous['date'], symbol=r['symbol'], reasons=r['blockers']))
        minute_batches = [dict(datetime=stamp, bars=bars) for stamp, bars in sorted(grouped.items()) if stamp[:10] == day]
        for row in closing['stocks']:
            last = grouped[day + 'T15:00:00'][row['symbol']]
            if abs(last['close'] - row['raw_close']) > .011 or last['factor'] != row['factor']:
                raise ValueError('日线技术特征和分钟样本口径不一致')
        days.append(dict(date=day, previous_close=previous, minutes=minute_batches,
            close_features=dict(date=day, stocks={r['symbol']: dict(factor=r['factor'],
                ma10_raw=r['ma10_raw'], atr20_raw=r['atr20_raw'], industry_weak=None) for r in closing['stocks']})))
    return dict(source_kind='REAL_HISTORY_INPUT_GATES_ONLY', initial_cash=30000.,
                calendar=calendar, days=days, missing_evidence=gates,
                formal_strategy_validated=False)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--features', required=True)
    p.add_argument('--minutes', required=True)
    p.add_argument('--output-dir', required=True)
    args = p.parse_args()
    feature_bytes, minute_bytes = Path(args.features).read_bytes(), Path(args.minutes).read_bytes()
    bundle = build_bundle(json.loads(feature_bytes), json.loads(minute_bytes))
    result = run_bundle(bundle)
    if result['fills'] or result['orders']:
        raise AssertionError('缺少证据的真实数据样本不应产生订单')
    result.update(status='INPUT_GATES_BLOCKED_NO_STRATEGY_TRADES', performance_interpretation_allowed=False,
                  missing_evidence=bundle['missing_evidence'],
                  input_sha256=dict(features=hashlib.sha256(feature_bytes).hexdigest(),
                                    minutes=hashlib.sha256(minute_bytes).hexdigest()))
    dest = Path(args.output_dir)
    dest.mkdir(parents=True, exist_ok=True)
    for name, obj in [('real_gated_bundle.json', bundle), ('real_gated_replay.json', result)]:
        (dest / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    print(json.dumps(dict(status=result['status'], days=len(result['daily']), orders=0,
                         blocked_rows=len(bundle['missing_evidence']))))


if __name__ == '__main__':
    main()
