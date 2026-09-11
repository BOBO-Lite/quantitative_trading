"""Seal the partial signal stage without promoting it to performance validation."""
import hashlib,json
from datetime import datetime,timezone
from assemble_sizeq_signals import OUT,run as merge
from audit_sizeq_ttm import run as ttm
from audit_sizeq_signals import audit

ROOT=OUT.parents[2]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def run():
    ttm()
    for name in ['signals_pilot','signals_2018','signals_2019','signals_2020','signals_2019_repair']:
        audit(OUT/(name+'_export.txt'))
    merge()
    parent=OUT.parent/'integrity.json';old=json.loads(parent.read_text(encoding='utf8'))
    predecessor=json.loads((OUT/'predecessor.json').read_text(encoding='utf8'))
    assert predecessor['manifest_sha256']==sha(parent)
    assert predecessor['files_unchanged']==len(old['evidence_sha256'])==61
    progress={'README.md','SYSTEM_STATUS.md','CHANGELOG.md'}
    untouched={p:h for p,h in old['evidence_sha256'].items() if p not in progress}
    assert all(sha(ROOT/p)==h for p,h in untouched.items())
    assert all(sha(ROOT/p)==h for p,h in old['frozen_sha256'].items())
    restore=json.loads((OUT/'platform_restore.json').read_text(encoding='utf8'))
    assert restore['exact_match'] and restore['reloaded'] and restore['characters']==27858
    for name,n in [('tests',338),('core_tests',6)]:
        text=(OUT/(name+'.txt')).read_text(encoding='utf8')
        assert 'Ran '+str(n)+' tests' in text and '\nOK' in text
    validation=json.loads((OUT/'system_validation.txt').read_text(encoding='utf8'))
    assert validation['status']=='PASS' and not validation['errors']
    extras=['src/sizeq_signals.py','src/audit_sizeq_signals.py','src/assemble_sizeq_signals.py',
            'src/audit_sizeq_ttm.py','src/seal_sizeq_continuation.py',
            'tests/test_sizeq_signals.py','tests/test_sizeq_public_evidence.py']
    files=[p for p in OUT.rglob('*') if p.is_file() and p.name!='integrity.json']+[ROOT/p for p in sorted(progress)]+[ROOT/p for p in extras]
    data=json.loads((OUT/'combined_signals.json').read_text(encoding='utf8'))
    manifest=dict(status='PASS_PARTIAL_SIGNAL_STAGE_INTEGRITY',checked_at=datetime.now(timezone.utc).isoformat(),
         signal_status=data['status'],passed_signals=data['passed_signals'],blocked_dates=data['blocked_dates'],
         portfolio_performance_completed=False,module_tests=338,core_tests=6,predecessor_sha256=sha(parent),
         unchanged_predecessor_files=len(untouched),intentionally_updated_progress=sorted(progress),
         frozen_sha256=old['frozen_sha256'],platform_restored=True,
         evidence_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(set(files))})
    (OUT/'integrity.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('SEALED',len(files),'files;',len(untouched),'unchanged predecessor files; performance incomplete')

if __name__=='__main__':run()
