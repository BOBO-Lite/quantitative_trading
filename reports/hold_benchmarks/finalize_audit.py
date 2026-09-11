"""Verify the fixed holding comparison and seal its research artifacts."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

previous = read(ROOT / 'reports/fh_volatility/integrity.json')
mutable = {'README.md', 'SYSTEM_STATUS.md', 'CHANGELOG.md'}
checked = 0
for key in ('files_sha256', 'production_inputs_sha256'):
    for name, expected in previous[key].items():
        if name in mutable:
            continue
        assert sha(ROOT / name) == expected, name
        checked += 1
assert sha(OUT / 'PROTOCOL.md') == read(OUT / 'protocol_lock.json')['sha256']
restore = read(OUT / 'platform_restore.json')
assert restore['exact_match'] and restore['reloaded']
points = 0
for cost in (1.0, 1.5):
    fh = read(ROOT / f'reports/e1_reentry_pair/FH_cost{cost}.json')
    first = next(f for f in fh['fills'] if f['buy'])
    for label in ('START_SINGLE_FULL', 'FIRST_SIGNAL_FULL', 'FIRST_SIGNAL_SAME_QTY'):
        result = read(OUT / f'{label}_cost{cost}.json')
        assert len(result['curve']) == 730
        assert len({r['date'] for r in result['curve']}) == 730
        terminal = result['curve'][-1]
        independent = terminal['cash'] + terminal['receivable'] + result['buy']['quantity'] * result['terminal_raw_close']
        assert abs(independent - result['final_equity']) < 1e-6
        assert abs(result['independent_equity_error']) < 1e-6
        if label == 'FIRST_SIGNAL_SAME_QTY':
            assert all(result['buy'][k] == first[k] for k in ('quantity', 'price', 'fees', 'fill_time'))
        points += len(result['curve'])
summaries = read(OUT / 'case_summary.json')
assert [(r['complete'], r['blocked']) for r in summaries] == [(34, 2), (35, 3)]
assert sum(r['status'] == 'COMPLETE' for r in read(OUT / 'cases.json')) == 69
normalizers = [read(OUT / f'data_normalization_{i:02d}.json') for i in (1, 2)]
assert sum(r['stock_days'] for r in normalizers) == 9
assert all(not r['duplicates'] for r in normalizers)
for i, r in enumerate(normalizers, 1):
    # Normalizer hashes canonical LF text before Windows writes CRLF bytes.
    canonical = (OUT / f'minute_export_{i:02d}.txt').read_text(encoding='utf-8')
    assert hashlib.sha256(canonical.encode()).hexdigest() == r['normalized_sha256']
    assert sha(OUT / f'raw_platform_log_{i:02d}.txt') == r['raw_sha256']
save('execution_audit.json', dict(status='PASS_WITH_EXPLICIT_BLOCKED_CASES',
    prior_hash_checks=checked, protocol_lock=True, daily_account_points=points,
    same_entry_parities=2, completed_case_cost_paths=69, blocked_case_cost_paths=5,
    supplemental_stock_days=9, platform_restore=restore,
    live_orders=False, production_inputs_sha256=previous['production_inputs_sha256']))
update = '> 2026-09-10持有基准对照完成：2018—2020正常成本累计收益，徐工机械期初单股持有+18.69%（日收盘回撤32.20%），南京银行FH首买点全仓持有-4.13%，FH组合+8.17%（回撤11.25%）。同买点逐笔对照完成34/35条成本路径，剩余2/3条公司行动阻塞；不可汇总为组合收益。下一步优先恢复真实退出原因、统一20/60交易日窗口，再验证单项退出改动的完整账户。招商南油首次成本3.822及实际退出4.03已由用户确认。详见[持有基准及下一步](reports/hold_benchmarks/RESULT.md)。\n\n'
for name in mutable:
    path = ROOT / name
    original = path.read_text(encoding='utf-8-sig')
    if not original.startswith(update):
        path.write_text(update + original, encoding='utf-8')
paths = list(OUT.iterdir()) + [ROOT / 'src' / n for n in ('collect_hold_benchmarks.py', 'hold_benchmarks.py', 'report_hold_benchmarks.py')]
paths += [ROOT / 'tests/test_hold_benchmarks.py']
files = {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(paths) if p.is_file() and p.name != 'integrity.json'}
save('integrity.json', dict(status='HOLD_BENCHMARKS_COMPLETE_WITH_EXPLICIT_BLOCKED_CASES', files_sha256=files,
    production_inputs_sha256=previous['production_inputs_sha256']))
for name, expected in read(OUT / 'integrity.json')['files_sha256'].items():
    assert sha(ROOT / name) == expected, name
print(json.dumps(dict(sealed_files=len(files), prior_hash_checks=checked, account_points=points, completed_cases=69, blocked_cases=5)))
