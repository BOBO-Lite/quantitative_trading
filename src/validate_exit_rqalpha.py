"""退出候选在RQAlpha真实账户中独立核对全部分钟和成交。"""
import json
import pandas as pd
from exit_research import prepare,OUT,BASE
from validate_simple_quarter_rqalpha import validate,ROOT

def main():
    cache,bundle=prepare()
    metadata=pd.read_csv(ROOT/'runtime/industry_history/monthly_universe.csv.gz',dtype=str).drop_duplicates('symbol').set_index('symbol').to_dict('index')
    results=[]
    for variant in ('E1','E2'):
        for cost in (1.,1.5):
            expected=json.loads((OUT/f'{variant}_cost{cost}.json').read_text(encoding='utf8'))
            try:
                result=validate(cost,cache,metadata,bundle['corporate_events'],out=OUT,expected=expected,calendar=bundle['calendar'])
                result.update(variant=variant,status='PASS_EXIT_MINUTE_ACCOUNT_PARITY')
            except ValueError as e:result=dict(variant=variant,cost=cost,status='BLOCKED_PARITY',error=str(e))
            results.append(result)
            (OUT/'rqalpha_parity.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
            print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
