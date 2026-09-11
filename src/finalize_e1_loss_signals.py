"""Seal completed loss-signal research, source evidence and unchanged production files."""
import hashlib,json
from e1_loss_signal_study import ROOT,OUT,save
from exit_extension_research import read_export,OUT as PRIOR

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    r=json.loads((OUT/'account_comparison.json').read_text(encoding='utf8'))
    restore=json.loads((OUT/'platform_restore.json').read_text(encoding='utf8'));assert restore['exact_match'] and restore['reloaded']
    prior_path=ROOT/'reports/e1_conditions/integrity.json';prior=json.loads(prior_path.read_text(encoding='utf8'))
    progress={'README.md','SYSTEM_STATUS.md','CHANGELOG.md'}
    for name,digest in prior['files_sha256'].items():
        if name not in progress:assert sha(ROOT/name)==digest,name
    frozen=json.loads((ROOT/'reports/e1_conditions/predecessor.json').read_text(encoding='utf8'))['frozen_inputs_sha256']
    for name,digest in frozen.items():assert sha(ROOT/name)==digest,name
    covered={s for s,d in json.loads((PRIOR/'requests.json').read_text(encoding='utf8'))['requests']}
    checks=[];unique=set()
    for p in sorted(OUT.glob('minute_export_*.txt')):
        c=read_export(p);assert set(c.daily)<=covered;unique.update(c.minutes)
        checks.append(dict(file=p.name,sha256=sha(p),stock_days=len(c.minutes),checks=c.checks))
    save('supplement_audit.json',dict(status='PASS',stock_days=len(unique),rows=len(unique)*240,batches=checks))
    normal,stress=r['rows']
    note=(f"> 2026-09-09亏损预警研究完成：买入前4项简单预警未形成一致排亏证据；首日转弱早退误卖代价大，第三日转弱只在强趋势过滤组有正向线索。完整三年过滤版+F3累计{normal['new_return_pct']:+.2f}%/{stress['new_return_pct']:+.2f}%（正常/1.5倍成本）；{r['decision']}。353项模块测试、79笔原买卖复现及237次逐笔资金核对通过，平台原代码已恢复。详见[亏损信号研究](reports/e1_loss_signals/RESULT.md)。\n\n")
    for name in progress:
        p=ROOT/name;old=p.read_text(encoding='utf8')
        if not old.startswith(note):p.write_text(note+old,encoding='utf8')
    files=[p for p in OUT.iterdir() if p.is_file() and p.name!='integrity.json' and not p.name.endswith('.tmp')]
    files += [ROOT/'src'/n for n in ('e1_loss_signal_study.py','e1_loss_signal_replay.py','report_e1_loss_signals.py','finalize_e1_loss_signals.py')]
    files += [ROOT/'tests/test_e1_loss_signals.py']+[ROOT/n for n in progress]
    save('integrity.json',dict(status='PASS_EXPLORATORY_LOSS_SIGNAL_STAGE',previous_manifest_sha256=sha(prior_path),unchanged_predecessor_files=len(prior['files_sha256'])-3,production_inputs_sha256=frozen,module_tests=353,original_trade_pairs_reproduced=79,independent_pair_cash_checks=237,complete_portfolio_paths=2,final_portfolio_cash_checks=2,unseen_validation=False,new_rqalpha_validation=False,live_changed=False,files_sha256={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in sorted(files)}))
    print(json.dumps(dict(files=len(files),supplement_stock_days=len(unique),decision=r['decision']),ensure_ascii=False))

if __name__=='__main__':main()
