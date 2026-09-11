"""固定能力样本的可复现核对，不输出策略绩效或启用交易。"""
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from import_supermind_minute_probe import decode_packets


def run():
    folder = Path(__file__).resolve().parent
    log_path = folder / 'platform_probe_6a9fe624b480bf00b634243b.txt'
    packets = decode_packets(log_path.read_text(encoding='utf-8'))
    expected = {'000939.SZ_historical_daily'} | {
        symbol + suffix for symbol in ['000001.SZ', '600036.SH']
        for suffix in ['_dividend', '_dividend_details']}
    assert set(packets) == expected
    assert all(v['status'] == 'RETURNED' for v in packets.values())
    d = packets['000939.SZ_historical_daily']['data']
    fields = ['open', 'high', 'low', 'close', 'volume', 'turnover', 'factor',
              'is_st', 'is_paused', 'high_limit', 'low_limit']
    assert set(d) == set(fields)
    days = sorted(d['close'])
    assert len(days) == 243 and days[0][:10] == '2018-01-02' and days[-1][:10] == '2018-12-28'
    for field in fields:
        assert set(d[field]) == set(days)
    for day in days:
        row = {key: d[key][day] for key in fields}
        assert all(isinstance(x, (int, float)) and math.isfinite(x) for x in row.values())
        assert 0 < row['low'] <= min(row['open'], row['close']) <= max(row['open'], row['close']) <= row['high']
        assert row['factor'] > 0 and row['volume'] >= 0 and row['turnover'] >= 0
        assert row['is_st'] in (0, 1) and row['is_paused'] in (0, 1)
        assert 0 < row['low_limit'] <= row['high_limit']
        if row['is_paused']:
            assert row['volume'] == row['turnover'] == 0
    active = [day for day in days if d['is_paused'][day] == 0 and d['volume'][day] > 0]
    assert len(active) == 124
    actions = []
    for symbol in ['000001.SZ', '600036.SH']:
        simple = packets[symbol + '_dividend']['data']
        detail = packets[symbol + '_dividend_details']['data']
        indices = set(detail['stock_bonus_symbol'])
        assert len(indices) == 2 and all(set(column) == indices for column in detail.values())
        assert all(set(column) == set(simple['symbol']) for column in simple.values())
        ex_dates = set()
        for index in sorted(indices):
            assert detail['stock_bonus_symbol'][index] == symbol
            ex = detail['stock_bonus_ex_dividend_date'][index]
            assert ex not in ex_dates and simple['symbol'][ex] == symbol
            ex_dates.add(ex)
            record = detail['stock_bonus_date_of_record'][index]
            pay = detail['stock_bonus_date_payable'][index]
            announcement = detail['stock_bonus_dividend_announcement_date'][index]
            assert announcement <= record < ex <= pay
            assert '2017-01-01' <= ex[:10] <= '2019-04-19'
            assert simple['cash_dividends'][ex] >= 0
            assert simple['give_stock'][ex] == detail['stock_bonus_per_share_bonus'][index] == 0
            assert simple['transfer_stock'][ex] == detail['stock_bonus_per_share_capital_stock'][index] == 0
            # 这里的Z来自平台日期序列化；这些字段仅代表日，不代表精确公开时刻。
            actions.append(dict(symbol=symbol, ex_date=ex[:10], record_date=record[:10],
                                pay_date=pay[:10], announcement_date=announcement[:10],
                                cash_per_share=simple['cash_dividends'][ex],
                                shares_per_share=0, normalized_date_only=True))
        assert ex_dates == set(simple['symbol'])
    metadata = json.loads((ROOT / 'runtime/industry_history/raw/supermind_industry_history_2018.json').read_text(encoding='utf-8'))
    info = [r for r in metadata['universe_snapshots']['20180131'] if r['symbol'] == '000939.SZ']
    assert len(info) == 1
    output = dict(status='FIXED_CAPABILITY_SAMPLE_CHECKED', log_sha256=hashlib.sha256(log_path.read_bytes()).hexdigest(),
                  packets=5, daily_rows=len(days), active_days=len(active), paused_days=119,
                  st_days=sum(bool(d['is_st'][day]) for day in days),
                  metadata_delisted_date=info[0]['de_listed_date'],
                  dividend_events=actions, dividend_events_count=len(actions),
                  corporate_action_execution_validated=False, full_universe_coverage_validated=False,
                  formal_strategy_validated=False)
    (folder / 'platform_capability_audit.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    run()
