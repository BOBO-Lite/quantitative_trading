"""长期基准与历史行业样本核验；不把样本就绪提升为全策略就绪。"""
import copy
import hashlib
import json
import math
from pathlib import Path
import pandas as pd
from import_supermind_minute_probe import decode_packets

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def benchmark_frame(packet, current):
    if packet['symbol'] != '000905.SH':
        raise ValueError('基准代码错误')
    rows = [{'date': t[:10], 'close': c} for t, c in packet['data']['close'].items()]
    frame = pd.DataFrame(rows).sort_values('date')
    for f in (frame, current):
        if f.empty or f.date.duplicated().any() or not all(math.isfinite(c) and c > 0 for c in f.close):
            raise ValueError('基准日期重复、空集或收盘无效')
        pd.to_datetime(f.date, errors='raise')
    overlap = frame.merge(current, on='date')
    if overlap.empty or (overlap.close_x - overlap.close_y).abs().max() > .005:
        raise ValueError('基准重叠校验失败')
    merged = pd.concat([frame, current[current.date > frame.date.max()]], ignore_index=True)
    return merged, dict(overlap_days=len(overlap), max_close_difference=float((overlap.close_x-overlap.close_y).abs().max()))


def industry_series(packets, mapping_reference):
    mapping = packets['industry_memberships']['mappings']
    if set(mapping) != {'20190228', '20190331'}:
        raise ValueError('历史月份不完整')
    expected = set()
    for month, sectors in mapping.items():
        members = [s for v in sectors.values() for s in v['members']]
        if len(members) != len(set(members)) or any(not v['members'] for v in sectors.values()):
            raise ValueError('行业重复成分或空行业')
        ref = mapping_reference[mapping_reference.date == pd.Timestamp(month).strftime('%Y-%m-%d')]
        ref = ref[ref.symbol.str.startswith(('000','001','002','003','600','601','603','605'))]
        actual = {s: k for k, v in sectors.items() for s in v['members']}
        if ref.symbol.duplicated().any() or actual != dict(zip(ref.symbol, ref.industry_code)):
            raise ValueError('历史行业归属与独立月末快照不一致')
        expected.update(members)
    prices, dates = {}, None
    for key, packet in packets.items():
        if not key.startswith('industry_prices_'):
            continue
        if packet['price_basis'] != 'pre_adjusted_ratio_only_not_execution_price':
            raise ValueError('行业价格口径错误')
        if dates is None:
            dates = packet['dates']
        if packet['dates'] != dates or dates != sorted(set(dates)):
            raise ValueError('交易日不一致或重复')
        for row in packet['rows']:
            if row['symbol'] in prices or len(row['close']) != len(dates):
                raise ValueError('重复股票或价格长度不符')
            prices[row['symbol']] = row['close']
    if set(prices) != expected:
        raise ValueError('行业行情分母覆盖不完整')
    benchmark_dates = sorted(t[:10] for t in packets['long_benchmark']['data']['close']
                             if '2019-03-01' <= t[:10] <= '2019-04-18')
    if dates != benchmark_dates:
        raise ValueError('行业交易日存在遗漏')
    rows = []
    for i, day in enumerate(dates[1:], 1):
        month = (pd.Timestamp(day).replace(day=1)-pd.Timedelta(days=1)).strftime('%Y%m%d')
        for code, sector in mapping[month].items():
            returns = []
            for symbol in sector['members']:
                prior, now = prices[symbol][i-1:i+1]
                if any(v is None or not math.isfinite(v) or v <= 0 for v in (prior, now)):
                    raise ValueError(f'需要的成分股价格缺失：{day}/{symbol}')
                returns.append(now/prior-1)
            rows.append(dict(date=day, industry_code=code, industry_name=sector['name'],
                             industry_asof=pd.Timestamp(month).strftime('%Y-%m-%d'),
                             member_count=len(returns), equal_weight_return=sum(returns)/len(returns)))
    frame = pd.DataFrame(rows).sort_values(['industry_code', 'date'])
    frame['industry_return20'] = frame.groupby('industry_code').equal_weight_return.transform(
        lambda values: (1+values).rolling(20, min_periods=20).apply(math.prod, raw=True)-1)
    frame['industry_percentile'] = frame.groupby('date').industry_return20.rank(method='average', pct=True)
    return frame.sort_values(['date', 'industry_code'])


def enrich(features, series):
    result = copy.deepcopy(features)
    for day in result['days']:
        if day['date'] == '2019-04-19':
            continue  # 回放终点收盘不作为本次入场信号，保持原有缺证据状态。
        for stock in day['stocks']:
            match = series[(series.date == day['date']) & (series.industry_code == stock['industry'])]
            if len(match) != 1 or not math.isfinite(match.iloc[0].industry_return20):
                raise ValueError('信号日行业强度缺失')
            row = match.iloc[0]
            if stock['industry_asof'] != row.industry_asof:
                raise ValueError('信号行业时点不一致')
            for k in ('industry_return20', 'industry_percentile'):
                stock[k] = float(row[k])
            stock['industry_strength_ready'] = True
            stock['blockers'] = [b for b in stock['blockers'] if b != 'PIT_INDUSTRY_FEATURES_MISSING']
            stock['event_clear'] = False
            stock['pit_verified'] = False
    result['status'] = 'HISTORICAL_RANK_AND_INDUSTRY_ADDED_EVENT_GATE_BLOCKED'
    return result


def main():
    out = ROOT/'reports/s2_research/long_history'
    raw = out/'platform_export.txt'
    text = raw.read_text(encoding='utf8')
    if 'LONG_AND_INDUSTRY_EXPORT_DONE' not in text:
        raise ValueError('平台导出未完成')
    packets = decode_packets(text)
    current = ROOT/'runtime/s1_benchmark.csv'
    mapping = ROOT/'runtime/industry_history/monthly_industry.csv.gz'
    features = ROOT/'reports/s2_research/portfolio_replay/historical_ranked_features.json'
    benchmark, overlap = benchmark_frame(packets['long_benchmark'], pd.read_csv(current))
    industry = industry_series(packets, pd.read_csv(mapping, dtype=str))
    enriched = enrich(json.loads(features.read_text(encoding='utf8')), industry)
    benchmark.to_csv(out/'research_benchmark.csv', index=False)
    industry.to_csv(out/'industry_daily_returns.csv', index=False)
    (out/'historical_enriched_features.json').write_text(json.dumps(enriched, ensure_ascii=False, indent=2), encoding='utf8')
    files = [raw, current, mapping, features, out/'research_benchmark.csv', out/'industry_daily_returns.csv', out/'historical_enriched_features.json']
    manifest = dict(status='PASS_BENCHMARK_AND_HISTORICAL_INDUSTRY_SAMPLE',
                    benchmark_start=benchmark.date.min(), benchmark_end=benchmark.date.max(), benchmark_days=len(benchmark),
                    benchmark_overlap=overlap, industry_rows=len(industry),
                    industry_count=int(industry.industry_code.nunique()),
                    membership_counts={d:sum(len(v['members']) for v in m.values()) for d,m in packets['industry_memberships']['mappings'].items()},
                    industry_definition='previous month-end classified historical mainboard members; daily equal-weight returns compounded over 20 sessions; average-tie percentile',
                    limitations=['行业样本仅2019年3月至4月；未分类股票不被猜测归入行业', '前复权价仅用于收益比率，不用于成交或现金账本', '完整策略财报时点、长期状态和分钟覆盖仍缺'],
                    formal_strategy_validated=False, hashes={str(f.relative_to(ROOT)):sha(f) for f in files})
    (out/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k:v for k,v in manifest.items() if k!='hashes'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
