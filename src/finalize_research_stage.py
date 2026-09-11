"""封存ETF3及退出研究证据；校验冻结源与全部结果，不宣称部署验收。"""
import hashlib,json
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    multi=ROOT/'reports/multiasset_research';exits=ROOT/'reports/exit_research'
    frozen={'adapters/supermind_s1_minute_backtest.py':'c1e87739dcea419665650e4d714ea8d5a414a9ac849cd08d7596c30dcdfaf9e5',
            'runtime/s1_daily.csv':'e741a2bc7c5d0d6bb9e542fb10c30737592f720e3b0b089d29f268398ce38b29'}
    for path,sha in frozen.items():
        if digest(ROOT/path)!=sha:raise ValueError('冻结文件摘要改变：'+path)
    extension=exits/'extension_2020';entry=ROOT/'reports/entry_research'
    restore=json.loads((extension/'platform_restore.json').read_text(encoding='utf8'))
    if not restore['same'] or restore['characters']!=27858 or not restore.get('verified_after_reload'):raise ValueError('平台恢复验证不通过')
    extended_checks=json.loads((extension/'rqalpha_parity.json').read_text(encoding='utf8'))
    entry_checks=json.loads((entry/'rqalpha_parity.json').read_text(encoding='utf8'))
    if len(extended_checks)!=6 or any(r['status']!='PASS_EXIT_EXTENSION_MINUTE_PARITY' for r in extended_checks):raise ValueError('2020退出核账未完成')
    if len(entry_checks)!=2 or any(r['status']!='PASS_ENTRY_MINUTE_PARITY' for r in entry_checks):raise ValueError('买点核账未完成')
    from exit_extension_research import check_prefix
    for variant in ('E0','E1','E2'):
        for cost in (1.,1.5):
            result=json.loads((extension/f'{variant}_cost{cost}.json').read_text(encoding='utf8'))
            old=json.loads((exits/f'{variant}_cost{cost}.json').read_text(encoding='utf8'))
            check_prefix(result,old)
            if len(result['daily'])!=730 or len(result['minute_curve'])!=175200:raise ValueError('2020覆盖不完整')
    for cost in (1.,1.5):
        baseline=json.loads((entry/f'B0_cost{cost}.json').read_text(encoding='utf8'))
        reference=json.loads((extension/f'E0_cost{cost}.json').read_text(encoding='utf8'))
        if baseline!=reference:raise ValueError('买点基准未复现')
    regressions=json.loads((multi/'previous_versions_regression.json').read_text(encoding='utf8'))
    if len(regressions)!=4 or not all(r['entire_result_identical'] for r in regressions):raise ValueError('旧ETF回归未完成')
    checks=json.loads((exits/'rqalpha_parity.json').read_text(encoding='utf8'))
    if len(checks)!=4 or any(r['status']!='PASS_EXIT_MINUTE_ACCOUNT_PARITY' for r in checks):raise ValueError('退出RQAlpha未通过')
    mchecks=json.loads((multi/'rqalpha_parity.json').read_text(encoding='utf8'))
    if len(mchecks)!=2 or any(r['status']!='PASS_ETF_EXECUTION_ACCOUNT_PARITY' for r in mchecks):raise ValueError('ETF3RQAlpha未通过')
    for c in (1.,1.5):
        a=json.loads((exits/f'E0_cost{c}.json').read_text(encoding='utf8'))
        b=json.loads((ROOT/f'reports/simple_research/continuous_2018_2019/cost{c}.json').read_text(encoding='utf8'))
        if a!=b:raise ValueError('E0原版回归不一致')
    paired=json.loads((exits/'paired_trades.json').read_text(encoding='utf8'))
    if any(v['status']!='CLOSED' for r in paired['trades'] for v in r['variants'].values()):raise ValueError('配对有未解决样本')
    files=[ROOT/p for p in ('src/etf_dataset.py','src/etf_replay.py','src/multiasset_research.py','src/report_multiasset_research.py',
        'src/validate_etf_rqalpha.py','adapters/rqalpha_etf_mod.py','src/exit_research.py','src/paired_exit_research.py',
        'src/report_exit_research.py','src/prepare_exit_2020.py','src/validate_exit_rqalpha.py','src/research_portfolio.py',
        'src/research_execution.py','src/corporate_actions.py','src/simple_history_replay.py','src/simple_minute_cache.py',
        'src/simple_strategy_rules.py','src/s2_strategy_rules.py','tests/test_exit_research.py','tests/test_etf_research.py',
        'src/finalize_research_stage.py','src/exit_extension_research.py','src/entry_research.py','src/prepare_exit_gap.py',
        'src/prepare_entry_gap.py','src/validate_exit_extension_rqalpha.py','src/validate_entry_rqalpha.py',
        'src/report_exit_extension.py','src/report_entry_research.py','tests/test_exit_extension_research.py',
        'tests/test_entry_research.py','reports/BUY_SELL_FINDINGS_2026-09-09.md','SYSTEM_STATUS.md','README.md','CHANGELOG.md')]
    for folder in (multi,exits,entry,ROOT/'reports/s2_research/github_alpha_review_20260909'):
        files += [p for p in folder.rglob('*') if p.is_file() and p.name not in ('manifest.json','integrity.json')]
    for year in ('2018','2019'):
        folder=ROOT/'reports/simple_research'/year
        files += [p for p in folder.iterdir() if p.is_file() and (p.name.startswith(('minute_export','prefetch_export','prefetch_probe')) or p.name=='screen.json')]
    files += [ROOT/p for p in ('reports/simple_research/continuous_2018_2019/corporate_events.json','reports/simple_research/continuous_2018_2019/corporate_export.txt','reports/simple_research/2020/screen.json','reports/s2_research/GITHUB_ALPHA_FINDINGS_2026-09-09.md')]
    evidence={p.relative_to(ROOT).as_posix():digest(p) for p in sorted(set(files))}
    record=dict(status='PASS_RESEARCH_STAGE_INTEGRITY',checked_at=datetime.now(timezone.utc).isoformat(),frozen_sha256=frozen,
        etf3_daily_account_comparisons=sum(r['daily_comparisons'] for r in mchecks),exit_minute_account_comparisons=sum(r['minute_comparisons'] for r in checks),
        extension_and_entry_minute_comparisons=sum(r['minute_comparisons'] for r in extended_checks+entry_checks),
        extension_and_entry_fills=sum(r['fills'] for r in extended_checks+entry_checks),
        fixed_entry_baseline_samples_by_cost={'1.0':25,'1.5':37},evidence_sha256=evidence,
        limitations=['历史研究，不是实盘部署验收','2020退出和买点已完成；原买点及收紧买点2020无成交，不代表活跃行情验证','配对样本可能重叠，不可当组合收益或独立样本相加'])
    (exits/'integrity.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    (multi/'manifest.json').write_text(json.dumps(dict(scope='ETF3研究证据，非部署验收',sha256={k:v for k,v in evidence.items() if k.startswith(('src/','adapters/','tests/','reports/multiasset_research/'))}),ensure_ascii=False,indent=2),encoding='utf8')
    # 既有清单记录源代码路径，源已扩展；保留旧清单并明确当前重校验时间。
    for p in [ROOT/'reports/etf_research/manifest.json',ROOT/'reports/etf_research/extended_2018_2026/manifest.json']:
        current=json.loads(p.read_text(encoding='utf8'));backup=p.with_name('manifest_before_stage_refresh.json')
        if not backup.exists():backup.write_bytes(p.read_bytes())
        current['sha256']={k:digest(ROOT/k) for k in current['sha256']}
        current['refreshed_at']=record['checked_at'];current['refresh_basis']='ETF1/2完整本地结果与训练前缀回归一致；旧RQAlpha报告为既有核账，本次新增ETF3/退出RQ核验。'
        p.write_text(json.dumps(current,ensure_ascii=False,indent=2),encoding='utf8')
    for path,sha in evidence.items():
        if digest(ROOT/path)!=sha:raise ValueError('证据生成后变更：'+path)
    print(json.dumps({k:v for k,v in record.items() if k!='evidence_sha256'},ensure_ascii=False));print('evidence_files',len(evidence))

if __name__=='__main__':main()
