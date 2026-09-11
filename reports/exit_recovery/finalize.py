import json,hashlib
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf8')
checked=0
for folder in ('exit_horizon','hold_benchmarks'):
    prior=read(ROOT/f'reports/{folder}/integrity.json')
    for kind in ('files_sha256','production_inputs_sha256'):
        for name,digest in prior[kind].items():
            assert sha(ROOT/name)==digest,name
            checked+=1
production=prior['production_inputs_sha256']
assert sha(OUT/'PROTOCOL.md')==read(OUT/'protocol_lock.json')['sha256']
restore=read(OUT/'platform_restore.json');assert restore['exact_match'] and restore['reloaded']
assert not read(OUT/'missing_minutes.json') and not read(OUT/'decision.json')['eligible']
data=read(ROOT/'reports/hold_benchmarks/historical_inputs.json');cases=list(OUT.glob('case_*.json'));assert len(cases)==32
entered=0;points=0
for p in cases:
    blob=read(p);c=blob['case'];r=blob['result'];assert r['status']!='BLOCKED'
    if c['signal']:
        assert c['exit']<c['signal']<c['end']
        assert not any(c['trigger']['trigger_time'][:10]<=e['record_date']<=c['signal'] for e in data['unsupported'][c['symbol']])
    fills=r.get('fills',[])
    if fills:
        entered+=1;buys=[f for f in fills if f['buy']];sells=[f for f in fills if not f['buy']]
        assert len(buys)==1
        assert buys[0]['quantity']<=c['original_quantity'] and buys[0]['quantity']%100==0
        assert buys[0]['fill_time'][:10]>c['signal']
        for f in fills:assert (datetime.fromisoformat(f['fill_time'])-datetime.fromisoformat(f['intent_time'])).total_seconds()==60
        for f in sells:assert f['fill_time'][:10]>buys[0]['fill_time'][:10]
        final=r['final']
        cash=c['starting_cash']+sum((-1 if f['buy'] else 1)*f['quantity']*f['price']-f['fees'] for f in fills)+final['dividend_income']-final['dividend_tax']-final['dividend_receivable']
        assert abs(cash-final['cash'])<1e-6
        assert abs(final['equity']-c['starting_cash']-r['increment'])<1e-6
        assert sum(f['quantity'] for f in sells)==buys[0]['quantity'],'terminal open shares require explicit review'
    for day in r.get('daily',[]):assert day['cash']>=-1e-6
    points+=len(r.get('daily',[]))
assert entered==18
normalizer=read(OUT/'data_normalization_01.json')
assert normalizer['stock_days']==19 and not normalizer['duplicates']
assert normalizer['normalized_sha256']==hashlib.sha256((OUT/'minute_export_01.txt').read_text(encoding='utf8').encode()).hexdigest()
assert normalizer['raw_sha256']==sha(OUT/'raw_platform_log_01.txt')
for source in read(OUT/'minute_sources.json'):assert sha(ROOT/source['file'])==source['sha256']
save('execution_audit.json',dict(status='PASS_RESEARCH_NOT_ADOPTED',prior_hash_checks=checked,paths=32,
    entered_paths=entered,daily_equity_points=points,tests_passed=4,new_stock_days=19,new_minutes=4560,
    no_future_entry=True,t_plus_one=True,cash_reconciliation=True,platform_restored=True,live_orders=False))
update='> 2026-09-10保护退出恢复研究完成：固定L/LM两规则×两成本共32条逐笔路径全部闭合；18条实际再入场、8条无信号、6条未买入。L正常/压力实际重入增量中位数-0.07%/-0.74%，LM +0.63%/-1.80%，不代表组合收益；两候选均未通过事前准入，不接FH。补齐19股票日分钟，4项测试通过，平台原代码已恢复。下一步扩大固定定义样本并检查入场相对市场优势，不继续围绕小样本调参。详见[恢复信号研究](reports/exit_recovery/RESULT.md)。\n\n'
for name in ('README.md','SYSTEM_STATUS.md','CHANGELOG.md'):
    p=ROOT/name;text=p.read_text(encoding='utf-8-sig')
    if not text.startswith(update):p.write_text(update+text,encoding='utf8')
paths=list(OUT.iterdir())+[ROOT/'src/exit_recovery_research.py',ROOT/'src/report_exit_recovery.py',ROOT/'tests/test_exit_recovery_research.py']
manifest={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(paths) if p.is_file() and p.name!='integrity.json'}
save('integrity.json',dict(status='EXIT_RECOVERY_COMPLETE_NOT_ADOPTED',files_sha256=manifest,production_inputs_sha256=production))
for name,digest in read(OUT/'integrity.json')['files_sha256'].items():assert sha(ROOT/name)==digest
print(json.dumps(dict(files=len(manifest),prior_hash_checks=checked,paths=32,entered=18,points=points)))
