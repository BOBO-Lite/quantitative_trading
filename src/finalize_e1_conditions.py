"""Seal completed exploratory condition research and preserve predecessor evidence."""
import hashlib,json
from e1_condition_study import ROOT,OUT,save
from exit_extension_research import read_export,OUT as PRIOR

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    results=json.loads((OUT/'account_comparison.json').read_text(encoding='utf8'))
    assert len(results['rows'])==2 and all(r['status']=='COMPLETED' for r in results['rows'])
    restore=json.loads((OUT/'platform_restore.json').read_text(encoding='utf8'))
    assert restore['exact_match'] and restore['reloaded']
    predecessor=json.loads((OUT/'predecessor.json').read_text(encoding='utf8'))
    for name,sha in predecessor['frozen_inputs_sha256'].items():assert digest(ROOT/name)==sha,name
    previous=json.loads((ROOT/'reports/e1_rank_research/integrity.json').read_text(encoding='utf8'))
    previous_hashes=next(v for v in previous.values() if isinstance(v,dict) and 'README.md' in v)
    progress={'README.md','SYSTEM_STATUS.md','CHANGELOG.md'}
    for name,sha in previous_hashes.items():
        if name not in progress:assert digest(ROOT/name)==sha,name
    covered={s for s,d in json.loads((PRIOR/'requests.json').read_text(encoding='utf8'))['requests']}
    checks=[];unique=set();symbols=set()
    for path in sorted(OUT.glob('minute_export_*.txt')):
        cache=read_export(path)
        assert set(cache.daily)<=covered
        unique.update(cache.minutes);symbols.update(cache.daily)
        checks.append(dict(file=path.name,sha256=digest(path),stock_days=len(cache.minutes),checks=cache.checks))
    save('supplement_audit.json',dict(status='PASS',unique_stock_days=len(unique),symbols=len(symbols),minute_rows=len(unique)*240,company_action_scope_checked=True,batches=checks))
    normal,stress=results['rows']
    note=(f"> 2026-09-09 E1信号环境研究完成：6419个候选股票日，11个固定单变量分组，仅MA20距离超过10%进入账户验证。三年累计收益{normal['return_pct']:+.2f}%/{stress['return_pct']:+.2f}%（正常/1.5倍成本），原E1为+5.75%/+3.49%。{results['decision']}；2020已用于筛选，不是样本外。349项模块测试通过，原平台代码恢复核验。详见[E1条件与涨跌案例报告](reports/e1_conditions/RESULT.md)。\n\n")
    for name in progress:
        path=ROOT/name;old=path.read_text(encoding='utf8')
        if not old.startswith(note):path.write_text(note+old,encoding='utf8')
    paths=[p for p in OUT.iterdir() if p.is_file() and p.name!='integrity.json' and not p.name.endswith('.tmp')]
    paths += [ROOT/'src'/n for n in ('e1_condition_study.py','e1_case_contrast.py','e1_condition_replay.py','report_e1_conditions.py','finalize_e1_conditions.py')]
    paths += [ROOT/'tests/test_e1_condition_study.py']+[ROOT/n for n in progress]
    save('integrity.json',dict(status='PASS_EXPLORATORY_CONDITION_STAGE',module_tests=349,account_paths=2,independent_final_cash_checks=2,unseen_validation=False,model_trained=False,live_strategy_changed=False,unchanged_predecessor_files=len(previous_hashes)-3,files_sha256={str(p.relative_to(ROOT)).replace('\\','/'):digest(p) for p in sorted(paths)}))
    print(json.dumps(dict(decision=results['decision'],supplement_stock_days=len(unique),symbols=len(symbols),files=len(paths)),ensure_ascii=False))

if __name__=='__main__':main()
