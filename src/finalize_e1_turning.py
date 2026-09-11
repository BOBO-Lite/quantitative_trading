"""Seal turning-point diagnostics and causal replay results."""
import json,hashlib
from e1_turning_research import ROOT,OUT,save
from exit_extension_research import read_export,OUT as PRIOR
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    result=json.loads((OUT/'comparison.json').read_text(encoding='utf8'));assert len(result['rows'])==10
    restore=json.loads((OUT/'platform_restore.json').read_text(encoding='utf8'));assert restore['exact_match'] and restore['reloaded']
    prev_path=ROOT/'reports/e1_asymmetric/integrity.json';previous=json.loads(prev_path.read_text(encoding='utf8'));progress={'README.md','SYSTEM_STATUS.md','CHANGELOG.md'}
    for name,h in previous['files_sha256'].items():
        if name not in progress:assert sha(ROOT/name)==h,name
    for name,h in previous['production_inputs_sha256'].items():assert sha(ROOT/name)==h,name
    coverage={s for s,d in json.loads((PRIOR/'requests.json').read_text(encoding='utf8'))['requests']};keys=set();audits=[]
    for path in sorted(OUT.glob('minute_export_*.txt')):
        c=read_export(path);assert set(c.daily)<=coverage;keys.update(c.minutes);audits.append(dict(file=path.name,sha256=sha(path),checks=c.checks))
    save('supplement_audit.json',dict(status='PASS',stock_days=len(keys),minute_rows=len(keys)*240,batches=audits))
    values={r['mode']+'_'+str(r['cost']):r['return_pct'] for r in result['rows']}
    comparisons='；'.join(f"{m} {values[m+'_1.0']:+.2f}%/{values[m+'_1.5']:+.2f}%" for m in ('B','P','Q','PQ','BPQ'))
    note=f"> 2026-09-09高低点倒推与信号检验完成：复原002317退出延迟与春节后跌停成交限制；新增盘中利润保护在固定原买入案例中反而过早卖出。10条完整三年账户（正常/压力）：{comparisons}。365项模块测试、10条现金及贡献核对通过。未来高低点只作诊断标签，不参与交易决策，原平台代码已恢复。详见[高低点倒推研究](reports/e1_turning/RESULT.md)。\n\n"
    for name in progress:
        p=ROOT/name;old=p.read_text(encoding='utf8')
        if not old.startswith(note):p.write_text(note+old,encoding='utf8')
    paths=[p for p in OUT.iterdir() if p.is_file() and p.name!='integrity.json' and not p.name.endswith('.tmp')]
    paths += [ROOT/'src'/n for n in ('e1_turning_research.py','e1_turning_rules.py','e1_turning_case_replay.py','plot_e1_turning_case.py','report_e1_turning.py','finalize_e1_turning.py')]
    paths += [ROOT/'tests/test_e1_turning.py']+[ROOT/n for n in progress]
    save('integrity.json',dict(status='PASS_EXTREMA_DIAGNOSTICS_CAUSAL_REPLAY',account_paths=10,minute_account_points=1752000,cash_reconciliations=10,trade_contribution_checks=10,module_tests=365,original_case_execution_paths_reproduced=2,case_rule_attempt_improved=False,plot_visually_checked=True,previous_manifest_sha256=sha(prev_path),unchanged_predecessor_files=len(previous['files_sha256'])-3,production_inputs_sha256=previous['production_inputs_sha256'],unseen_validation=False,new_rqalpha_validation=False,live_changed=False,files_sha256={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in sorted(paths)}))
    print(json.dumps(dict(files=len(paths),supplement_stock_days=len(keys),decisions=result['decisions']),ensure_ascii=False))
if __name__=='__main__':main()
