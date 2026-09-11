"""核验历史主板横截面，并在完整可排名集合内计算20日相对强度百分位。"""
import argparse
from collections import Counter
import copy
import hashlib
import json
from math import isfinite
from pathlib import Path

import pandas as pd
from import_supermind_minute_probe import decode_packets

ACCEPTED_REASONS = {'ELIGIBLE', 'ST', 'PAUSED', 'LOW_LIQUIDITY', 'SHORT_LISTING_HISTORY'}


def audit_section(section):
    date, expected, rows = section['date'], section['expected_symbols'], section['rows']
    if section['universe_asof'] != date or section['source'] != 'get_all_securities(stock, historical_date)':
        raise ValueError('股票池来源或日期不符合历史时点要求')
    if len(expected) != len(set(expected)) or len(rows) != len(expected) or {r['symbol'] for r in rows} != set(expected):
        raise ValueError('股票池覆盖不完整或重复')
    if any(not s.startswith(('000', '001', '002', '003', '600', '601', '603', '605'))
           or not s.endswith(('.SH', '.SZ')) for s in expected):
        raise ValueError('横截面包含主板范围以外的代码')
    if len({r['symbol'] for r in rows}) != len(rows) or any(r['date'] != date for r in rows):
        raise ValueError('股票行重复或信号日期不一致')
    if not expected or not isfinite(section['benchmark_ret20']):
        raise ValueError('空股票池或无效基准')
    invalid = [r for r in rows if r['reason'] not in ACCEPTED_REASONS]
    if invalid:
        raise ValueError('存在数据质量排除，不能把缺数据股票从排名分母删除：' + str(Counter(r['reason'] for r in invalid)))
    admitted = []
    for row in rows:
        if row['eligible'] != (row['reason'] == 'ELIGIBLE'):
            raise ValueError('纳入标志与排除理由冲突')
        if row['reason'] == 'SHORT_LISTING_HISTORY':
            if not 0 <= row['observed_bars'] < 120:
                raise ValueError('上市历史长度理由不成立')
            continue
        if row['observed_bars'] < 120 or any(not isfinite(row[k]) for k in ('ret20', 'ret60', 'amount20')):
            raise ValueError('有效股票收益或历史长度不合法')
        if row['amount20'] < 0 or min(row['ret20'], row['ret60']) <= -1:
            raise ValueError('收益或成交额超出有效范围')
        if type(row['is_st']) is not bool or type(row['is_paused']) is not bool:
            raise ValueError('状态字段必须明确')
        reason = ('ST' if row['is_st'] else 'PAUSED' if row['is_paused'] else
                  'LOW_LIQUIDITY' if row['amount20'] < 50000000 else 'ELIGIBLE')
        if reason != row['reason']:
            raise ValueError('排除理由不符合原始状态')
        if row['eligible']:
            admitted.append(dict(row, excess_ret20=row['ret20'] - section['benchmark_ret20']))
    if not admitted:
        raise ValueError('没有可排名股票')
    frame = pd.DataFrame(admitted)
    frame['rs_percentile'] = frame['excess_ret20'].rank(method='average', pct=True)
    return dict(date=date, status='PASS_EXPORTED_HISTORICAL_CROSS_SECTION', universe_count=len(expected),
                eligible_count=len(admitted), exclusion_counts=dict(Counter(r['reason'] for r in rows)),
                ranking_definition='20d excess return; average ties / eligible count; no event-calendar filter',
                rows=frame.sort_values('symbol').to_dict('records'), formal_strategy_validated=False)


def enrich_features(features, audited, mapping):
    result = copy.deepcopy(features)
    sections = {s['date']: s for s in audited}
    matches = []
    for day in result['days']:
        if day['date'] not in sections:
            continue  # 终点收盘特征不作为本次回放的入场排名。
        section = sections[day['date']]
        ranked = {r['symbol']: r for r in section['rows']}
        # 固定采用前一月末行业归属，不能选用信号日后的月末。
        mapping_date = (pd.Timestamp(day['date']).replace(day=1) - pd.Timedelta(days=1)).strftime('%Y-%m-%d')
        month = mapping.loc[mapping['date'] == mapping_date]
        for row in day['stocks']:
            rank = ranked.get(row['symbol'])
            if rank is None:
                row['blockers'].append('NOT_IN_ELIGIBLE_CROSS_SECTION')
                continue
            delta = row['ret20'] - rank['ret20']
            if abs(delta) > 1e-6:
                raise ValueError('样本原始日线与横截面前复权收益不一致')
            row['rs_percentile'] = rank['rs_percentile']
            row['ranking_asof'] = day['date']
            row['ranking_population'] = section['eligible_count']
            row['blockers'] = [r for r in row['blockers'] if r != 'FULL_PIT_UNIVERSE_RANKING_MISSING']
            industry = month.loc[month['symbol'] == row['symbol']]
            if len(industry) != 1:
                raise ValueError('前月末行业归属缺失或重复')
            row['industry'] = str(industry.iloc[0]['industry_code'])
            row['industry_asof'] = mapping_date
            row['industry_mapping_ready'] = True
            # 行业收益仍有生存者偏差，不在这里填充强度；财报门禁也不放行。
            row['event_clear'] = False
            row['pit_verified'] = False
            matches.append(dict(date=day['date'], symbol=row['symbol'], rs_percentile=row['rs_percentile'],
                                population=section['eligible_count'], return_delta=delta, industry=row['industry']))
    result['status'] = 'RANKING_AND_MAPPING_ADDED_EVENTS_AND_INDUSTRY_STRENGTH_BLOCKED'
    result['rank_matches'] = matches
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--log', required=True)
    p.add_argument('--features', required=True)
    p.add_argument('--mapping', required=True)
    p.add_argument('--output-dir', required=True)
    args = p.parse_args()
    log_bytes = Path(args.log).read_bytes()
    packets = decode_packets(log_bytes.decode('utf8'))
    dates = ['2019-04-16', '2019-04-17', '2019-04-18']
    audited = [audit_section(packets[d + '_cross_section']) for d in dates]
    feature_bytes = Path(args.features).read_bytes()
    mapping_bytes = Path(args.mapping).read_bytes()
    mapping = pd.read_csv(args.mapping, dtype=str)
    enriched = enrich_features(json.loads(feature_bytes), audited, mapping)
    enriched['source_sha256'] = dict(log=hashlib.sha256(log_bytes).hexdigest(),
        features=hashlib.sha256(feature_bytes).hexdigest(), mapping=hashlib.sha256(mapping_bytes).hexdigest())
    dest = Path(args.output_dir)
    dest.mkdir(parents=True, exist_ok=True)
    for name, obj in [('historical_cross_sections.json', audited), ('historical_ranked_features.json', enriched)]:
        (dest/name).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    print(json.dumps(dict(counts=[dict(date=s['date'], universe=s['universe_count'], eligible=s['eligible_count']) for s in audited],
                         sample_matches=enriched['rank_matches']), ensure_ascii=False))


if __name__ == '__main__':
    main()
