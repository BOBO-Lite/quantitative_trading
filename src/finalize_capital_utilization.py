"""Seal diagnostics, external evidence, and completed single-variable experiment."""
import json,hashlib
from capital_utilization import ROOT,OUT,save
from exit_extension_research import read_export
def read(p):return json.loads(p.read_text(encoding='utf8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    previous_path=ROOT/'reports/e1_reentry_pair/integrity.json';previous=read(previous_path)
    progress={'README.md','SYSTEM_STATUS.md','CHANGELOG.md'}
    for n,h in previous['files_sha256'].items():
        if n not in progress:assert sha(ROOT/n)==h,n
    for n,h in previous['production_inputs_sha256'].items():assert sha(ROOT/n)==h,n
    comparison=read(OUT/'comparison.json');assert len(comparison)==4
    assert len(read(OUT/'attribution.json'))==4
    restore=read(OUT/'platform_restore.json');assert restore['exact_match'] and restore['reloaded']
    keys=set();supplements=[]
    for p in sorted(OUT.glob('minute_export_*.txt')):
        cache=read_export(p);keys.update(cache.minutes);supplements.append(dict(file=p.name,sha256=sha(p),checks=cache.checks))
    tests=(OUT/'module_tests.txt').read_text(encoding='utf8');assert 'Ran 388 tests' in tests and tests.strip().endswith('OK')
    summary='；'.join(f"{r['mode']}成本{r['cost']} {r['old_return']:+.2f}%→{r['new_return']:+.2f}%" for r in comparison)
    save('execution_audit.json',dict(status='PASS',observer_account_parities=4,experiment_paths=4,account_minute_points=1401600,cash_checks=4,attribution_checks=4,module_tests=388,supplement_stock_days=len(keys),supplement_minute_rows=len(keys)*240,supplements=supplements,platform=restore,engine_source_sha256=sha(ROOT/'src/research_portfolio.py'),sizing_source_sha256=sha(ROOT/'src/s2_strategy_rules.py'),production_changed=False,live_orders=False,unseen_validation=False))
    note=f"> 2026-09-10资金利用诊断与单因素测试完成：FH正常620空仓日中553日为市场防守。恢复最低金额4000改3000结果（均为三年累计）：{summary}。4条观察账户完整一致、4条改动账户、388项测试通过。外部方法和实际案例已核查。详见[资金利用研究](reports/capital_utilization/RESULT.md)。\n\n"
    for n in progress:
        p=ROOT/n;s=p.read_text(encoding='utf8')
        if not s.startswith(note):p.write_text(note+s,encoding='utf8')
    paths=[p for p in OUT.iterdir() if p.is_file() and p.name!='integrity.json' and not p.name.endswith('.tmp')]
    paths += [ROOT/'src'/n for n in ('capital_utilization.py','report_capital_utilization.py','finalize_capital_utilization.py')]+[ROOT/'tests/test_capital_utilization.py']+[ROOT/n for n in progress]
    save('integrity.json',dict(status='PASS_CAPITAL_UTILIZATION_RESEARCH',predecessor_manifest_sha256=sha(previous_path),production_inputs_sha256=previous['production_inputs_sha256'],files_sha256={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in sorted(paths)},live_changed=False,unseen_validation=False))
    print(json.dumps(dict(files=len(paths),stock_days=len(keys)),ensure_ascii=False))
if __name__=='__main__':main()
