"""收紧追价的真实RQAlpha账户独立核验。"""
import json
import pandas as pd
from exit_extension_research import prepare, read_export, ROOT
from simple_history_replay import merge_cache
from validate_simple_quarter_rqalpha import validate

def main():
    out=ROOT/'reports/entry_research'
    cache,bundle=prepare()
    cache=merge_cache([cache]+[read_export(p) for p in sorted(out.glob('minute_export_*.txt'))])
    metadata=pd.read_csv(ROOT/'runtime/industry_history/monthly_universe.csv.gz',dtype=str).drop_duplicates('symbol').set_index('symbol').to_dict('index')
    checks=[]
    for cost in (1.,1.5):
        expected=json.loads((out/f'B1_cost{cost}.json').read_text(encoding='utf8'))
        try:
            result=validate(cost,cache,metadata,bundle['corporate_events'],out=out,expected=expected,calendar=bundle['calendar'])
            result.update(variant='B1',status='PASS_ENTRY_MINUTE_PARITY')
        except ValueError as exc:result=dict(variant='B1',cost=cost,status='BLOCKED_PARITY',error=str(exc))
        checks.append(result)
        (out/'rqalpha_parity.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__': main()
