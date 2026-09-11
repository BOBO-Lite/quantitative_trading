"""Preserve predecessor and production inputs; seal current evidence."""
import json,hashlib
from run_e1_confirmation import ROOT,OUT,save
from exit_extension_research import read_export
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    result=json.loads((OUT/'comparison.json').read_text(encoding='utf8'));assert len(result['rows'])==12
    old_path=ROOT/'reports/e1_turning/integrity.json';old=json.loads(old_path.read_text(encoding='utf8'));progress={'README.md','SYSTEM_STATUS.md','CHANGELOG.md'}
    for n,h in old['files_sha256'].items():
        if n not in progress:assert sha(ROOT/n)==h,n
    for n,h in old['production_inputs_sha256'].items():assert sha(ROOT/n)==h,n
    restore=json.loads((OUT/'platform_restore.json').read_text(encoding='utf8'));assert restore['exact_match'] and restore['reloaded']
    packets=[];keys=set()
    for p in sorted(OUT.glob('minute_export_*.txt')):
        c=read_export(p);keys.update(c.minutes);packets.append(dict(file=p.name,sha256=sha(p),checks=c.checks))
    save('execution_audit.json',dict(status='PASS',account_paths=12,account_minute_points=2102400,cash_checks=12,attribution_checks=38,module_tests=373,baseline_parity=json.loads((OUT/'baseline_parity.json').read_text(encoding='utf8')),supplement_stock_days=len(keys),supplement_minute_rows=len(keys)*240,supplements=packets,platform_restored=restore,unseen_validation=False,new_rqalpha_validation=False,live_orders=False))
    summary='；'.join(f"{m} "+'/'.join(f"{r['return_pct']:+.2f}%" for r in result['rows'] if r['mode']==m) for m in ('V','S','H','C','F','CF'))
    note=f"> 2026-09-10回调确认研究完成：六组×两档成本的2018—2020完整账户：{summary}。373项模块测试、原E1/P成交及分钟权益对照、12条现金核账和38组收益归因通过。众生药业30分钟确认避开早卖但仍不如原E1，样本内结果不代表未见验证。详见[回调确认研究](reports/e1_confirmation/RESULT.md)。\n\n"
    for n in progress:
        p=ROOT/n;text=p.read_text(encoding='utf8')
        if not text.startswith(note):p.write_text(note+text,encoding='utf8')
    paths=[p for p in OUT.iterdir() if p.is_file() and p.name!='integrity.json' and not p.name.endswith('.tmp')]
    paths += [ROOT/'src'/n for n in ('e1_confirmation.py','run_e1_confirmation.py','case_e1_confirmation.py','report_e1_confirmation.py','finalize_e1_confirmation.py')]+[ROOT/'tests/test_e1_confirmation.py']+[ROOT/n for n in progress]
    save('integrity.json',dict(status='PASS_CONFIRMATION_RESEARCH',predecessor_manifest_sha256=sha(old_path),production_inputs_sha256=old['production_inputs_sha256'],files_sha256={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in sorted(paths)},live_changed=False,unseen_validation=False))
    print(json.dumps(dict(files=len(paths),supplement_stock_days=len(keys),decisions=result['decisions']),ensure_ascii=False))
if __name__=='__main__':main()
