"""Seal SIZEQ data stage, preserving predecessor research and frozen live files."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from verify_sizeq_data import run, OUT
ROOT=OUT.parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def seal():
    run()
    oldpath=ROOT/'reports/external_momentum/integrity.json'
    old=json.loads(oldpath.read_text(encoding='utf8'))
    progress={'README.md','SYSTEM_STATUS.md','CHANGELOG.md'}
    prior=json.loads((OUT/'predecessor_check.json').read_text(encoding='utf8'))
    assert prior['manifest_sha256']==sha(oldpath) and not prior['mismatches']
    assert prior['files_checked_before_progress_update']==len(old['evidence_sha256'])
    unchanged={f:h for f,h in old['evidence_sha256'].items() if f not in progress}
    assert all(sha(ROOT/f)==h for f,h in unchanged.items())
    frozen_code={f:h for f,h in old['frozen_sha256'].items() if f!='runtime/s1_daily.csv'}
    assert all(sha(ROOT/f)==h for f,h in frozen_code.items())
    update=json.loads((OUT/'concurrent_daily_update.json').read_text(encoding='utf8'))['update_manifest']
    assert update['daily_sha256_before']==old['frozen_sha256']['runtime/s1_daily.csv']
    assert update['daily_sha256_after']==sha(ROOT/'runtime/s1_daily.csv')
    restore=json.loads((OUT/'platform_restore.json').read_text(encoding='utf8'))
    assert restore['exact_match'] and restore['characters']==27858
    audit=json.loads((OUT/'data_stage_audit.json').read_text(encoding='utf8'))
    assert audit['pilot']['status']=='PASS_SINGLE_SIGNAL_DECISION_AUDIT'
    # PowerShell captures native text using UTF-16 in this environment.
    raw=(OUT/'tests.txt').read_bytes()
    log=raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')
    assert 'Ran 323 tests' in log and '\nOK' in log
    extras=['src/external_size_quality.py','src/audit_sizeq_pilot.py','src/verify_sizeq_data.py','src/seal_sizeq_data.py','tests/test_external_size_quality.py','tests/test_sizeq_pilot_audit.py','adapters/supermind_sizeq_feasibility.py']
    paths=[p for p in OUT.rglob('*') if p.is_file() and p.name!='integrity.json']+[ROOT/p for p in sorted(progress)]+[ROOT/p for p in extras]
    manifest=dict(status='PASS_SIZEQ_SINGLE_SIGNAL_DATA_STAGE_INTEGRITY',checked_at=datetime.now(timezone.utc).isoformat(),tests_passed=323,predecessor_manifest_sha256=sha(oldpath),predecessor_files_checked_before_update=len(old['evidence_sha256']),unchanged_predecessor_evidence_files=len(unchanged),intentionally_updated_progress_documents=sorted(progress),frozen_sha256=frozen_code,runtime_daily_change=dict(before=update['daily_sha256_before'],after=update['daily_sha256_after'],documented_update_at=update['generated_at'],not_a_sizeq_input=True,historical_byte_identity_proven=False),platform_original_restored=True,portfolio_performance_completed=False,evidence_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(set(paths))})
    (OUT/'integrity.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in manifest.items() if k not in ['evidence_sha256','frozen_sha256']},ensure_ascii=False))
    print('sealed_files',len(manifest['evidence_sha256']))
if __name__=='__main__':seal()
