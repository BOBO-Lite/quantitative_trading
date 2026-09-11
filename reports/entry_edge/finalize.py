import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf8')
checks=0
for folder in ('exit_recovery','exit_horizon','hold_benchmarks'):
    seal=read(ROOT/f'reports/{folder}/integrity.json')
    for key in ('files_sha256','production_inputs_sha256'):
        for name,digest in seal[key].items():assert sha(ROOT/name)==digest,name;checks+=1
production=seal['production_inputs_sha256']
assert sha(OUT/'PROTOCOL.md')==read(OUT/'protocol_lock.json')['sha256']
assert read(OUT/'platform_restore.json')['exact_match'] and read(OUT/'platform_restore.json')['reloaded']
audit=read(OUT/'coverage_audit.json')
assert audit['original_signal_checks']==6419 and audit['source_errors']==0 and not audit['conflicts']
assert audit['actual_normal']==36 and audit['actual_pressure']==38
assert audit['cached_raw_endpoint_field_checks']==4348
assert audit['signal_statuses']=={'OK':19131,'MISSING_ENDPOINT':1,'CENSORED':125}
for year in (2018,2019,2020):
    a=read(OUT/f'audit_{year}.json');assert sha(OUT/f'raw_{year}.txt')==a['raw_sha256']
summary=read(OUT/'summary.json');assert len(summary)==36
decision=read(OUT/'decision.json')
assert decision['fh_cross_year_price_edge'] and not decision['momentum_cross_year_price_edge']
for row in read(OUT/'complete_date_sensitivity.json'):
    if row['year'] in ('2019','2020') and row['horizon'] in (20,60) and row['group']=='FH_ALL':
        assert row['excess_pool_pct']>0 and row['excess_market_pct']>0
save('execution_audit.json',dict(status='PRICE_DIAGNOSTIC_COMPLETE_NOT_PORTFOLIO',prior_hash_checks=checks,
    dates=156,signal_pairs=6419,price_windows_ok=19131,price_windows_missing=1,censored=125,
    independent_cached_field_checks=4348,platform_restored=True,production_unchanged=True,
    new_account_return_computed=False,live_orders=False))
note='> 2026-09-10买点价值检查完成：原条件6419个股票-信号日、156日期。FH候选20/60日平均相对中证500差额+0.68/+3.17个百分点（复权价格统计，非年化或账户净收益）；2019/2020方向均正，2018仅2天不足判断。简单60日动量前5在20/60日落后，不替换FH。保留候选的初步选股优势，暂停退出微调，下一步固定跨时期检验和完整账户宽基对照。保留终点缺价/删失与涨停等不可交易标记。详见[买点价值检查](reports/entry_edge/RESULT.md)。\n\n'
for name in ('README.md','SYSTEM_STATUS.md','CHANGELOG.md'):
    p=ROOT/name;text=p.read_text(encoding='utf-8-sig')
    if not text.startswith(note):p.write_text(note+text,encoding='utf8')
files=list(OUT.iterdir())+[ROOT/'src/entry_edge_audit.py',ROOT/'src/report_entry_edge.py']
manifest={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(files) if p.is_file() and p.name!='integrity.json'}
save('integrity.json',dict(status='ENTRY_PRICE_EDGE_DIAGNOSTIC_COMPLETE',files_sha256=manifest,production_inputs_sha256=production))
for name,digest in read(OUT/'integrity.json')['files_sha256'].items():assert sha(ROOT/name)==digest
print(json.dumps(dict(files=len(manifest),prior_hash_checks=checks,signal_pairs=6419)))
