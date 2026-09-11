"""RECOVERY1完整路径的独立RQAlpha账户核验。"""
import json
import argparse
import pandas as pd
from recovery_research import prepare,OUT,ROOT
from validate_simple_quarter_rqalpha import validate

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--variants',nargs='+',choices=['R1','R2'],default=['R1','R2']);args=parser.parse_args()
    cache,bundle=prepare()
    metadata=pd.read_csv(ROOT/'runtime/industry_history/monthly_universe.csv.gz',dtype=str).drop_duplicates('symbol').set_index('symbol').to_dict('index')
    previous=json.loads((OUT/'rqalpha_parity.json').read_text(encoding='utf8')) if (OUT/'rqalpha_parity.json').exists() else []
    checks=[r for r in previous if r['variant'] not in args.variants]
    for variant in args.variants:
        for cost in (1.,1.5):
            path=OUT/f'{variant}_cost{cost}.json'
            if not path.exists():
                result=dict(variant=variant,cost=cost,status='NOT_RUN_INCOMPLETE_REPLAY')
            else:
                expected=json.loads(path.read_text(encoding='utf8'))
                try:
                    result=validate(cost,cache,metadata,bundle['corporate_events'],out=OUT,expected=expected,calendar=bundle['calendar'])
                    result.update(variant=variant,status='PASS_RECOVERY_MINUTE_PARITY')
                except ValueError as exc:result=dict(variant=variant,cost=cost,status='BLOCKED_PARITY',error=str(exc))
            checks.append(result)
            (OUT/'rqalpha_parity.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf8')
            print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
