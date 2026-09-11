"""2020连续退出扩展的独立账户核账，不将核账视为策略有效性证明。"""
import json
import pandas as pd
from exit_extension_research import prepare, OUT, ROOT
from validate_simple_quarter_rqalpha import validate

def main():
    cache,bundle=prepare()
    metadata=pd.read_csv(ROOT/'runtime/industry_history/monthly_universe.csv.gz',dtype=str).drop_duplicates('symbol').set_index('symbol').to_dict('index')
    checks=[]
    for variant in ('E0','E1','E2'):
        for cost in (1.,1.5):
            path=OUT/f'{variant}_cost{cost}.json'
            if not path.exists():
                check=dict(variant=variant,cost=cost,status='NOT_RUN_INCOMPLETE_REPLAY')
            else:
                expected=json.loads(path.read_text(encoding='utf8'))
                try:
                    check=validate(cost,cache,metadata,bundle['corporate_events'],out=OUT,expected=expected,calendar=bundle['calendar'])
                    check.update(variant=variant,status='PASS_EXIT_EXTENSION_MINUTE_PARITY')
                except ValueError as exc:
                    check=dict(variant=variant,cost=cost,status='BLOCKED_PARITY',error=str(exc))
            checks.append(check)
            (OUT/'rqalpha_parity.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf8')
            print(json.dumps(check,ensure_ascii=False),flush=True)

if __name__=='__main__': main()
