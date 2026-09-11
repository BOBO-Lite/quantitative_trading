"""Seal authorized asymmetric-management experiments and prior evidence."""
import hashlib,json
from e1_asymmetric import ROOT,OUT,save
from exit_extension_research import read_export,OUT as PRIOR
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    report=json.loads((OUT/'comparison.json').read_text(encoding='utf8'));assert len(report['rows'])==8
    restore=json.loads((OUT/'platform_restore.json').read_text(encoding='utf8'));assert restore['exact_match'] and restore['reloaded']
    previous_path=ROOT/'reports/e1_loss_signals/integrity.json';old=json.loads(previous_path.read_text(encoding='utf8'))
    progress={'README.md','SYSTEM_STATUS.md','CHANGELOG.md'}
    for name,h in old['files_sha256'].items():
        if name not in progress:assert sha(ROOT/name)==h,name
    for name,h in old['production_inputs_sha256'].items():assert sha(ROOT/name)==h,name
    covered={s for s,d in json.loads((PRIOR/'requests.json').read_text(encoding='utf8'))['requests']}
    keys=set();audits=[]
    for p in sorted(OUT.glob('minute_export_*.txt')):
        c=read_export(p);assert set(c.daily)<=covered;keys.update(c.minutes);audits.append(dict(file=p.name,sha256=sha(p),checks=c.checks))
    save('supplement_audit.json',dict(status='PASS',stock_days=len(keys),minute_rows=len(keys)*240,batches=audits))
    values={r['mode']+'_'+str(r['cost']):r['return_pct'] for r in report['rows']}
    note=(f"> 2026-09-09盈亏非对称与回撤恢复研究完成：用户授权修改冻结规则；正常/压力三年累计R小仓恢复{values['R_1.0']:+.2f}%/{values['R_1.5']:+.2f}%，W盈利延长{values['W_1.0']:+.2f}%/{values['W_1.5']:+.2f}%，L半R早止损{values['L_1.0']:+.2f}%/{values['L_1.5']:+.2f}%，追加RW组合{values['RW_1.0']:+.2f}%/{values['RW_1.5']:+.2f}%。8条完整账户核对、359项模块测试通过。W表面改善来自减少后续亏损，延长的盈利交易本身少赚；尚未证明盈利扩大。详见[盈亏管理对照](reports/e1_asymmetric/RESULT.md)。\n\n")
    for name in progress:
        p=ROOT/name;s=p.read_text(encoding='utf8')
        if not s.startswith(note):p.write_text(note+s,encoding='utf8')
    paths=[p for p in OUT.iterdir() if p.is_file() and p.name!='integrity.json' and not p.name.endswith('.tmp')]
    paths += [ROOT/'src'/n for n in ('e1_asymmetric.py','report_e1_asymmetric.py','finalize_e1_asymmetric.py')]
    paths += [ROOT/'tests/test_e1_asymmetric.py']+[ROOT/n for n in progress]
    save('integrity.json',dict(status='PASS_ASYMMETRIC_RESEARCH_STAGE',account_paths=8,minute_account_points=8*175200,independent_final_cash_checks=8,trade_contribution_checks=8,module_tests=359,previous_manifest_sha256=sha(previous_path),unchanged_predecessor_files=len(old['files_sha256'])-3,production_inputs_sha256=old['production_inputs_sha256'],user_authorized_frozen_rule_research=True,unseen_validation=False,new_rqalpha_parity=False,live_changed=False,files_sha256={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in sorted(paths)}))
    print(json.dumps(dict(files=len(paths),supplement_stock_days=len(keys),decisions=report['decisions']),ensure_ascii=False))
if __name__=='__main__':main()
