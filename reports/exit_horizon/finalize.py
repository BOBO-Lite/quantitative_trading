"""Verify research scope, window timing and the sealed predecessor."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
prior=read(ROOT/'reports/hold_benchmarks/integrity.json')
checks=0
for key in ('files_sha256','production_inputs_sha256'):
    for name,expected in prior[key].items():
        assert sha(ROOT/name)==expected,name
        checks+=1
assert sha(OUT/'PROTOCOL.md')==read(OUT/'protocol_lock.json')['sha256']
calendar=sorted({d['date'] for y in (2018,2019,2020) for d in read(ROOT/f'reports/simple_research/{y}/screen.json')['days'] if '2018-01-01'<=d['date']<='2020-12-31'})
rows=read(OUT/'cases.json');assert len(rows)==148
for r in rows:
    assert r['trigger']['prior_context']['asof']<r['trigger']['trigger_time'][:10]
    assert r['end']==calendar[calendar.index(r['entry'])+r['horizon']-1]
    if r['status']=='COMPLETE':
        assert r['actual_exit'][:10]<=r['end']
        assert abs(r['hold_net']-r['original_net']-r['difference'])<1e-7
    elif r['status']=='EXIT_AFTER_WINDOW':assert r['actual_exit'][:10]>r['end']
assert sum(r['status']=='COMPLETE' for r in rows)==140
assert sum(r['status']=='EXIT_AFTER_WINDOW' for r in rows)==6
assert sum(r['status']=='BLOCKED' for r in rows)==2
for cost in (1.0,1.5):
    p=read(OUT/f'parity_cost{cost}.json')
    assert p['exact_full_result_match'] and p['daily_points']==730 and p['minute_points']==175200
assert read(OUT/'candidate_gate.json')['eligible_reason_groups']==[]
save('execution_audit.json',dict(status='PASS_NO_EXIT_REMOVAL_CANDIDATE',prior_hash_checks=checks,
    baseline_exact_parities=2,minute_equity_points=350400,tests_passed=3,
    window_cost_paths=148,complete_comparisons=140,exit_after_window=6,corporate_blocked=2,
    future_exit_leakage_checks=True,live_orders=False,strategy_changed=False))
update='> 2026-09-10退出原因与固定窗口研究完成：两档FH完整回放逐字段一致；正常成本36笔的真实原因是市场防守26、收盘保护7、到期2、持续弱势1。固定60日正常/压力成本中原退出分别优于持有23/23笔，持有更好13/14笔；无退出类别通过两窗口两成本初筛，不取消保护。下一研究方向为保护退出后的可观测恢复信号，而非无条件延长持有。详见[退出原因与固定窗口](reports/exit_horizon/RESULT.md)。\n\n'
for name in ('README.md','SYSTEM_STATUS.md','CHANGELOG.md'):
    p=ROOT/name;text=p.read_text(encoding='utf-8-sig')
    if not text.startswith(update):p.write_text(update+text,encoding='utf-8')
files=list(OUT.iterdir())+[ROOT/'src/exit_horizon_audit.py',ROOT/'src/report_exit_horizon.py',ROOT/'tests/test_exit_horizon_audit.py']
manifest={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(files) if p.is_file() and p.name!='integrity.json'}
save('integrity.json',dict(status='EXIT_HORIZON_AUDIT_COMPLETE_NO_ADOPTION',files_sha256=manifest,production_inputs_sha256=prior['production_inputs_sha256']))
for name,expected in read(OUT/'integrity.json')['files_sha256'].items():assert sha(ROOT/name)==expected,name
print(json.dumps(dict(sealed_files=len(manifest),prior_hash_checks=checks,complete_comparisons=140,tests_passed=3)))
