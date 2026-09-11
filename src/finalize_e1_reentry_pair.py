"""Seal cross-recovery tests and persist final-version requirements."""
import json,hashlib
from run_e1_reentry_pair import ROOT,OUT,save
from exit_extension_research import read_export
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    results=json.loads((OUT/'comparison.json').read_text(encoding='utf8'));assert len(results['rows'])==12
    assert len(json.loads((OUT/'attribution.json').read_text(encoding='utf8')))==20
    test_text=(OUT/'module_tests.txt').read_text(encoding='utf8');assert 'Ran 382 tests' in test_text and test_text.strip().endswith('OK')
    old_path=ROOT/'reports/e1_confirmation/integrity.json';old=json.loads(old_path.read_text(encoding='utf8'));progress={'README.md','SYSTEM_STATUS.md','CHANGELOG.md'}
    for n,h in old['files_sha256'].items():
        if n not in progress:assert sha(ROOT/n)==h,n
    for n,h in old['production_inputs_sha256'].items():assert sha(ROOT/n)==h,n
    used=bool(list(OUT.glob('minute_export_*.txt')))
    restore=json.loads((OUT/'platform_restore.json').read_text(encoding='utf8')) if used else dict(platform_used=False,reason='All needed minutes already cached; no platform mutation')
    if used:assert restore['exact_match'] and restore['reloaded']
    keys=set();batches=[]
    for p in sorted(OUT.glob('minute_export_*.txt')):
        c=read_export(p);keys.update(c.minutes);batches.append(dict(file=p.name,sha256=sha(p),checks=c.checks))
    save('execution_audit.json',dict(status='PASS',account_paths=12,account_minute_points=2102400,cash_checks=12,attribution_checks=20,module_tests=382,baseline_parity=json.loads((OUT/'baseline_parity.json').read_text(encoding='utf8')),supplement_stock_days=len(keys),supplement_minute_rows=len(keys)*240,supplements=batches,platform=restore,unseen_validation=False,new_rqalpha_validation=False,live_orders=False))
    summary='；'.join(m+' '+ '/'.join(f"{r['return_pct']:+.2f}%" for r in results['rows'] if r['mode']==m) for m in ('E1R','FR','E1U','FU','E1H','FH'))
    note=f"> 2026-09-10恢复开仓交叉验证完成：正常/压力三年累计 {summary}。382项模块测试、12条现金核账和20组收益归因通过。最终版必须解决12%空仓后不能恢复的问题，要求已写入FINAL_STRATEGY_REQUIREMENTS.md；旧停止规则只作对照。详见[恢复开仓交叉研究](reports/e1_reentry_pair/RESULT.md)。\n\n"
    for n in progress:
        p=ROOT/n;text=p.read_text(encoding='utf8')
        if not text.startswith(note):p.write_text(note+text,encoding='utf8')
    paths=[p for p in OUT.iterdir() if p.is_file() and p.name!='integrity.json' and not p.name.endswith('.tmp')]
    paths += [ROOT/'src'/n for n in ('e1_reentry_pair.py','run_e1_reentry_pair.py','report_e1_reentry_pair.py','finalize_e1_reentry_pair.py')]+[ROOT/'tests/test_e1_reentry_pair.py',ROOT/'FINAL_STRATEGY_REQUIREMENTS.md']+[ROOT/n for n in progress]
    save('integrity.json',dict(status='PASS_REENTRY_CROSS_RESEARCH',predecessor_manifest_sha256=sha(old_path),production_inputs_sha256=old['production_inputs_sha256'],files_sha256={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in sorted(paths)},live_changed=False,unseen_validation=False))
    print(json.dumps(dict(files=len(paths),supplement_stock_days=len(keys)),ensure_ascii=False))
if __name__=='__main__':main()
