"""封存暂停恢复实验，并确认旧研究证据及冻结文件未被改写。"""
import hashlib,json
from datetime import datetime,timezone
from recovery_research import ROOT,OUT,PRIOR

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    oldpath=ROOT/'reports/exit_research/integrity.json'
    previous=json.loads(oldpath.read_text(encoding='utf8'))
    for rel,digest in previous['frozen_sha256'].items():
        if sha(ROOT/rel)!=digest:raise ValueError('冻结文件改变：'+rel)
    checked=0
    for rel,digest in previous['evidence_sha256'].items():
        if rel in ('README.md','SYSTEM_STATUS.md','CHANGELOG.md'):continue
        if sha(ROOT/rel)!=digest:raise ValueError('前期研究证据改变：'+rel)
        checked+=1
    restore=json.loads((OUT/'platform_restore.json').read_text(encoding='utf8'))
    if not restore.get('same') or not restore.get('verified_after_reload') or restore['characters']!=27858:
        raise ValueError('平台原代码未完成恢复核验')
    checks=json.loads((OUT/'rqalpha_parity.json').read_text(encoding='utf8'))
    if len(checks)!=4 or any(r['status']!='PASS_RECOVERY_MINUTE_PARITY' for r in checks):raise ValueError('四档独立账户核验未通过')
    for variant in ('R0','R1','R2'):
        for cost in (1.,1.5):
            result=json.loads((OUT/f'{variant}_cost{cost}.json').read_text(encoding='utf8'))
            if len(result['daily'])!=730 or len(result['minute_curve'])!=175200:raise ValueError('回放覆盖不完整')
            if variant=='R0' and result!=json.loads((PRIOR/f'E1_cost{cost}.json').read_text(encoding='utf8')):raise ValueError('原版结果未复现')
    files=[p for p in OUT.rglob('*') if p.is_file() and p.name!='integrity.json']
    files += [ROOT/p for p in ('src/recovery_research.py','src/prepare_recovery_gap.py','src/prepare_entry_gap.py','src/validate_recovery_rqalpha.py',
        'src/report_recovery_research.py','src/finalize_recovery_research.py','src/exit_research.py','src/exit_extension_research.py',
        'src/research_portfolio.py','src/research_execution.py','src/corporate_actions.py','src/s2_strategy_rules.py','src/simple_strategy_rules.py',
        'src/validate_simple_quarter_rqalpha.py','adapters/rqalpha_tech1_quarter_mod.py','tests/test_recovery_research.py',
        'README.md','SYSTEM_STATUS.md','CHANGELOG.md')]
    evidence={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(set(files))}
    record=dict(status='PASS_RECOVERY_RESEARCH_INTEGRITY',checked_at=datetime.now(timezone.utc).isoformat(),
        predecessor=oldpath.relative_to(ROOT).as_posix(),predecessor_sha256=sha(oldpath),unchanged_predecessor_evidence_files=checked,
        frozen_sha256=previous['frozen_sha256'],new_minute_comparisons=sum(r['minute_comparisons'] for r in checks),
        new_fill_comparisons=sum(r['fills'] for r in checks),baseline_full_results_identical=2,
        limitations=['研究，不启用实盘','已有历史，不是未见未来','15%是停止触发阈值，不保证成交损失不超过15%'],evidence_sha256=evidence)
    (OUT/'integrity.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    for rel,digest in evidence.items():
        if sha(ROOT/rel)!=digest:raise ValueError('封存时证据发生变化')
    print(json.dumps({k:v for k,v in record.items() if k!='evidence_sha256'},ensure_ascii=False));print('evidence_files',len(evidence))

if __name__=='__main__':main()
