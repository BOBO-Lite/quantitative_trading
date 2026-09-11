"""预取已确认信号的潜在持仓窗口，仅减少往返；实际回放仍决定是否成交。"""
import argparse,json
from pathlib import Path
from simple_history_replay import load_inputs
import simple_strategy_rules as rules
from simple_minute_aliases import ALIASES
ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument('--end-year',type=int,required=True);a=p.parse_args()
    cache,days=load_inputs(a.end_year);requests=set();confirmed=[]
    for i in range(1,len(days)):
        day=days[i]['date'];pre=days[i-1]
        if pre['route']!='trend_breakout':continue
        for row in pre['candidates']:
            if not rules.needs_minutes(row,pre['route']):continue
            bars=cache.minutes.get((row['symbol'],day))
            if not bars:continue
            volume=amount=0
            for bar in bars:
                volume+=bar['volume'];amount+=bar['turnover']
                if volume and rules.entry_confirmed(row,bar,pre['route'],bars[0]['open'],amount/volume):
                    confirmed.append((row['symbol'],day))
                    if row['symbol'] in {v[0] for v in ALIASES.values()}:break
                    for j in range(i+1,min(i+23,len(days))):
                        target=days[j]['date']
                        if target.startswith(str(a.end_year)) and (row['symbol'],target) not in cache.minutes:requests.add((row['symbol'],target))
                        if days[j-1]['route']=='defensive_cash':break
                    break
    out=ROOT/'reports/simple_research'/str(a.end_year)
    source=(out/'minute_probe.py').read_text(encoding='utf8');ordered=sorted(requests)
    for start in range(0,len(ordered),1400):
        code='\n'.join('REQUESTS = '+repr(ordered[start:start+1400]) if line.startswith('REQUESTS = ') else line for line in source.splitlines())+'\n'
        (out/f'prefetch_probe_{start//1400+1:02d}.py').write_text(code,encoding='utf8')
    record=dict(scope='data prefetch only; no portfolio decisions and no fabricated minutes',confirmed_symbol_days=len(confirmed),requested_symbol_days=len(ordered),symbols=len({s for s,d in ordered}),batches=(len(ordered)+1399)//1400,requests=ordered)
    (out/'prefetch_requests.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    print({k:v for k,v in record.items() if k!='requests'})

if __name__=='__main__':main()
