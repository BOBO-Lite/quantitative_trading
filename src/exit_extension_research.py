"""冻结 EXIT1 连续扩展；输入集合完整核验，旧区间账户轨迹必须不变。"""
import ast
import argparse
import json
from pathlib import Path
from collections import Counter
from exit_research import prepare as prepare_original, ExitRules
from simple_history_replay import clean_boundary, merge_cache
from simple_minute_cache import Cache, MissingMinutes
from import_supermind_minute_probe import decode_packets
from simple_corporate_events import build_events
from research_portfolio import run_bundle
from s2_strategy_rules import Policy

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/exit_research/extension_2020'

def read_export(path):
    raw = path.read_text(encoding='utf8')
    if 'TECH1_ENTRY_MINUTE_EXPORT_DONE' not in raw:
        raise ValueError('分钟导出缺少结束标记：' + path.name)
    probe = path.with_name(path.name.replace('minute_export', 'minute_probe').replace('.txt', '.py'))
    tree = ast.parse(probe.read_text(encoding='utf8'))
    wanted = set(next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'REQUESTS' for t in n.targets)))
    packets = decode_packets(raw)
    received = {(v['symbol'], v['date']) for k, v in packets.items() if k.startswith('minute_')}
    daily = {v['symbol'] for k, v in packets.items() if k.startswith('daily_')}
    if wanted != received or daily != {s for s, d in wanted}:
        raise ValueError('分钟或日线包集合不等于请求集合：' + path.name)
    return Cache(packets)

def prepare():
    original_cache, old_bundle = prepare_original()
    old_days = []
    for year in (2018, 2019):
        old_days.extend(json.loads((ROOT/f'reports/simple_research/{year}/screen.json').read_text(encoding='utf8'))['days'])
    screen = json.loads((ROOT/'reports/simple_research/2020/screen.json').read_text(encoding='utf8'))
    if screen['status'] != 'PASS_TECH1_HISTORY_SCREEN':
        raise ValueError('2020日线未通过')
    by_date = {d['date']: d for d in old_days}
    for day in screen['days']:
        if day['date'] in by_date and clean_boundary(day) != clean_boundary(by_date[day['date']]):
            raise ValueError('2020信号边界与旧区间不一致')
        by_date[day['date']] = day
    requests = json.loads((OUT/'requests.json').read_text(encoding='utf8'))
    for i in range(1, requests['batches']+1):
        if not (OUT/f'minute_export_{i:02d}.txt').exists():
            raise ValueError(f'尚缺初始数据批次 {i}')
    caches = [read_export(p) for p in sorted(OUT.glob('minute_export_*.txt'))]
    received = set().union(*(set(c.minutes) for c in caches))
    if not {tuple(r) for r in requests['requests']} <= received:
        raise ValueError('2020总请求集合不完整')
    cache = merge_cache([original_cache]+caches)
    raw = (OUT/'corporate_export.txt').read_text(encoding='utf8')
    if 'TECH1_CORPORATE_EXPORT_DONE' not in raw:
        raise ValueError('公司行动导出未完成')
    packets = decode_packets(raw)
    symbols = {s for s, d in received}
    if set(packets) != {'dividend_'+s for s in symbols} | {'details_'+s for s in symbols}:
        raise ValueError('公司行动请求集合不完整')
    cash = list(old_bundle['corporate_events'])
    unsupported = list(old_bundle['unsupported_corporate_events'])
    unknown = set(old_bundle['unresolved_corporate_symbols'])
    errors = []
    for s in sorted(symbols):
        try:
            events, other = build_events(packets, [s], '2020-01-01')
            cash.extend(events); unsupported.extend(other)
        except (ValueError, KeyError) as exc:
            unknown.add(s); errors.append(dict(symbol=s,error=str(exc)))
    days = [by_date[d] for d in sorted(by_date)]
    calendar = [d['date'] for d in days]
    # 保留原区间收盘特征，新增股票的历史预热不能反向改动旧研究输入。
    new_dates = [d for d in calendar if d > old_bundle['calendar'][-1]]
    closes = cache.closing_many(new_dates, OUT/'close_features_cache.json')
    additions = []
    for date, close in zip(new_dates, closes):
        i = calendar.index(date)
        additions.append(dict(date=date, previous_close=dict(date=calendar[i-1],benchmark=days[i-1]['benchmark'],stocks=days[i-1]['candidates']),close_features=close))
    bundle = dict(old_bundle, calendar=calendar, days=old_bundle['days']+additions,
                  corporate_events=cash, unsupported_corporate_events=unsupported,
                  unresolved_corporate_symbols=sorted(unknown))
    (OUT/'corporate_events.json').write_text(json.dumps(dict(cash=cash,unsupported=unsupported,unknown=errors),ensure_ascii=False,indent=2),encoding='utf8')
    return cache, bundle

def check_prefix(result, old):
    for key in ('fills', 'daily', 'minute_curve', 'orders', 'decisions'):
        if result[key][:len(old[key])] != old[key]:
            raise ValueError('旧区间输出变化：'+key)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--interactive', action='store_true')
    parser.add_argument('--variants', nargs='+', choices=['E0','E1','E2'], default=['E0','E1','E2'])
    args=parser.parse_args()
    cache, bundle = prepare()
    print('INPUTS_VERIFIED',flush=True)
    statuses = []; missing = []; loaded=set(OUT.glob('minute_export_*.txt'))
    for variant in args.variants:
        for cost in (1.,1.5):
          while True:
            try:
                result = run_bundle(bundle, Policy(cost_multiplier=cost), rules=ExitRules(variant), minute_loader=cache.load)
                old = json.loads((OUT.parent/f'{variant}_cost{cost}.json').read_text(encoding='utf8'))
                check_prefix(result, old)
                (OUT/f'{variant}_cost{cost}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
                row = dict(variant=variant,cost=cost,status='COMPLETED',metrics=result['metrics'],final=result['final'],fills=len(result['fills']),exit_reasons=dict(Counter(f['reason'] for f in result['fills'] if not f['buy'])))
            except MissingMinutes as exc:
                if args.interactive:
                    (OUT/'missing_minutes.json').write_text(json.dumps(exc.requests,ensure_ascii=False,indent=2),encoding='utf8')
                    print('AWAIT_MINUTES '+json.dumps(exc.requests,ensure_ascii=False),flush=True)
                    if input().strip() != 'continue':
                        raise ValueError('增量回放已停止，未完成路径不输出绩效')
                    new=set(OUT.glob('minute_export_*.txt'))-loaded
                    if not new: raise ValueError('没有新增真实行情')
                    supplements=[read_export(p) for p in sorted(new)]
                    for supplement in supplements:
                        if not set(supplement.daily)<=set(cache.daily):
                            raise ValueError('增量股票超出已核验公司行动范围')
                    cache=merge_cache([cache]+supplements);loaded |= new
                    continue
                missing.extend(exc.requests)
                row = dict(variant=variant,cost=cost,status='MISSING_MINUTES',requests=exc.requests)
            except ValueError as exc:
                row = dict(variant=variant,cost=cost,status='BLOCKED_REPLAY',error=str(exc))
            statuses.append(row); print(json.dumps(row,ensure_ascii=False),flush=True)
            (OUT/'incremental_run_status.json').write_text(json.dumps(statuses,ensure_ascii=False,indent=2),encoding='utf8')
            break
    unique = [dict(symbol=s,date=d) for s,d in sorted({(r['symbol'],r['date']) for r in missing})]
    for name, value in [('missing_minutes',unique),('run_status',statuses)]:
        (OUT/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')

if __name__ == '__main__': main()
