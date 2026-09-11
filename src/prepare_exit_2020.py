"""准备冻结退出规则的2020历史扩展数据请求；不计算或筛选绩效。"""
import json
from pathlib import Path
from simple_strategy_rules import select_signal,needs_minutes
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/exit_research/extension_2020'

def main():
    OUT.mkdir(exist_ok=True)
    screen=json.loads((ROOT/'reports/simple_research/2020/screen.json').read_text(encoding='utf8'))
    if screen['status']!='PASS_TECH1_HISTORY_SCREEN':raise ValueError('2020日线未通过')
    days=screen['days'];requests=set()
    for previous,current in zip(days,days[1:]):
        if not current['date'].startswith('2020'):continue
        route=previous['route']
        for row in previous['candidates']:
            if select_signal(row,route) and needs_minutes(row,route):requests.add((row['symbol'],current['date']))
    carry=set()
    for variant in ('E1','E2'):
        for cost in (1.,1.5):
            r=json.loads((OUT.parent/f'{variant}_cost{cost}.json').read_text(encoding='utf8'))
            carry.update(r['positions'])
    dates=[d['date'] for d in days if d['date'].startswith('2020')]
    for s in carry:
        for d in dates[:22]:requests.add((s,d))
    template=(ROOT/'adapters/supermind_tech1_minute_probe.py').read_text(encoding='utf8')
    template=template.replace('20181201','20190701').replace('20190628','20201231')
    ordered=sorted(requests)
    for i in range(0,len(ordered),800):
        code='\n'.join('REQUESTS = '+repr(ordered[i:i+800]) if line.startswith('REQUESTS = ') else line for line in template.splitlines())+'\n'
        (OUT/f'minute_probe_{i//800+1:02d}.py').write_text(code,encoding='utf8')
    status=dict(status='PREPARED_NOT_EXPORTED',screen_days=len(dates),requested_symbol_days=len(ordered),symbols=len({s for s,d in ordered}),carry_symbols=sorted(carry),batches=(len(ordered)+799)//800,requests=ordered,note='从2018起连续核账，不在2020重置资金；分钟/公司行动仍待取得及核验，不宣称完成2020回测')
    (OUT/'requests.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf8')
    print({k:v for k,v in status.items() if k!='requests'})

if __name__=='__main__':main()
