"""重建固定历史探针日志；不执行日志内容，不使用包名构造文件路径。"""
import argparse
import base64
import hashlib
import json
import math
from pathlib import Path
import re
import zlib

from research_portfolio import session_minutes

LINE = re.compile(r'^MINBUNDLE ([A-Za-z0-9_.-]+) (\d+) (\d+) (\d+) ([a-f0-9]{64}) ([A-Za-z0-9+/=]+)$', re.M)
MAX_BYTES = 5_000_000


def decode_packets(text):
    groups = {}
    for match in LINE.finditer(text):
        key, index, count, length, digest, piece = match.groups()
        index, count, length = int(index), int(count), int(length)
        if not 0 <= index < count <= 10000 or not 0 < length <= MAX_BYTES:
            raise ValueError('包长度或分片范围非法')
        group = groups.setdefault(key, dict(count=count, length=length, digest=digest, parts={}))
        if (count, length, digest) != (group['count'], group['length'], group['digest']):
            raise ValueError('同包元数据冲突')
        if index in group['parts']:
            raise ValueError('重复分片')
        group['parts'][index] = piece
    if not groups:
        raise ValueError('没有有效数据包')
    result = {}
    for key, group in groups.items():
        if set(group['parts']) != set(range(group['count'])):
            raise ValueError('缺少分片')
        compressed = base64.b64decode(''.join(group['parts'][i] for i in range(group['count'])), validate=True)
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, group['length'] + 1)
        if len(raw) != group['length'] or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError('解压长度或数据边界错误')
        if hashlib.sha256(raw).hexdigest() != group['digest']:
            raise ValueError('SHA256不匹配')
        result[key] = json.loads(raw)
    return result


def build_dataset(packets):
    symbols = ['000001.SZ', '600036.SH']
    dates = ['2019-04-17', '2019-04-18', '2019-04-19']
    daily = {}
    for key, frame in packets.items():
        if not key.endswith('_previous_daily'):
            continue
        symbol = key.split('_')[1]
        for stamp in frame['close']:
            row = {field: values[stamp] for field, values in frame.items()}
            marker = (stamp[:10], symbol)
            if marker in daily and row != daily[marker]:
                raise ValueError('同日元数据冲突')
            daily[marker] = row
    checks, output, fills_from_daily = [], [], 0
    for date in dates:
        rows = packets[date + '_minutes']
        if len(rows) != 480:
            raise ValueError('单日必须两只股票各240分钟')
        for symbol in symbols:
            selected = sorted((dict(r) for r in rows if r['symbol'] == symbol), key=lambda r: r['datetime'])
            if [r['datetime'] for r in selected] != session_minutes(date):
                raise ValueError('分钟日期、覆盖或唯一性错误')
            reference = daily[(date, symbol)]
            for row in selected:
                # 同一历史交易日的日线状态可以核补日内不变元数据，禁止用当前状态。
                supplemented = []
                for field in ('factor', 'is_st', 'is_paused', 'high_limit', 'low_limit'):
                    if row.get(field) is None:
                        row[field] = reference.get(field)
                        supplemented.append(field)
                if supplemented:
                    fills_from_daily += 1
                    row['metadata_from_same_day_daily'] = supplemented
                for field in ('open', 'high', 'low', 'close', 'factor', 'high_limit', 'low_limit'):
                    value = row.get(field)
                    if value is None or not math.isfinite(value) or value <= 0:
                        raise ValueError('历史字段缺失：' + field)
                for field in ('volume', 'turnover'):
                    if row.get(field) is None or not math.isfinite(row[field]) or row[field] < 0:
                        raise ValueError('量额字段非法')
                for field in ('is_st', 'is_paused'):
                    if row[field] not in (False, True, 0, 1):
                        raise ValueError('历史状态缺失')
                    row[field] = bool(row[field])
                if row['low'] > min(row['open'], row['close']) + 1e-6 or row['high'] < max(row['open'], row['close']) - 1e-6:
                    raise ValueError('OHLC关系错误')
                if row['factor'] != reference['factor']:
                    raise ValueError('分钟/同日日线因子冲突')
            volume_delta = sum(r['volume'] for r in selected) - reference['volume']
            amount_delta = sum(r['turnover'] for r in selected) - reference['turnover']
            check = dict(date=date, symbol=symbol, minutes=240,
                volume_delta=volume_delta, turnover_delta=amount_delta,
                volume_matches=abs(volume_delta) < 1e-6,
                turnover_matches=abs(amount_delta) <= 2.,
                close_matches=abs(selected[-1]['close'] - reference['close']) <= .011,
                open_delta=selected[0]['open'] - reference['open'])
            if not all(check[k] for k in ('volume_matches', 'turnover_matches', 'close_matches')):
                raise ValueError('日线核账未通过：' + json.dumps(check))
            checks.append(check)
            output.extend(selected)
    return dict(status='PASS_FIXED_SAMPLE_MINUTE_DATA', formal_strategy_validated=False,
                source='SuperMind visible historical report packets', dates=dates, symbols=symbols,
                row_count=len(output), rows_supplemented_from_same_day_daily=fills_from_daily,
                checks=checks, rows=sorted(output, key=lambda r: (r['datetime'], r['symbol'])),
                limitations=['Fixed two-symbol sample; no strategy feature or event gate validation',
                             'Metadata supplemented from same historical day when minute object omits it'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--log', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    raw = Path(args.log).read_bytes()
    result = build_dataset(decode_packets(raw.decode('utf-8')))
    result['log_sha256'] = hashlib.sha256(raw).hexdigest()
    dest = Path(args.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
