"""为收紧追价产生的真实持仓缺口请求固定窗口，不按盈利筛选。"""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/entry_research'

def main():
    missing=json.loads((OUT/'missing_minutes.json').read_text(encoding='utf8'))
    days=sorted({d['date'] for year in (2018,2019,2020) for d in json.loads((ROOT/f'reports/simple_research/{year}/screen.json').read_text(encoding='utf8'))['days']})
    requests=set()
    for row in missing:
        i=days.index(row['date'])
        requests.update((row['symbol'],day) for day in days[i:i+27])
    if not requests: raise ValueError('没有实际待补缺口')
    first=min(d for s,d in requests);last=max(d for s,d in requests)
    source=(ROOT/'adapters/supermind_tech1_minute_probe.py').read_text(encoding='utf8')
    source=source.replace('20181201',str(int(first[:4])-1)+'0701').replace('20190628',last[:4]+'1231')
    source='\n'.join('REQUESTS = '+repr(sorted(requests)) if line.startswith('REQUESTS = ') else line for line in source.splitlines())+'\n'
    index=max([int(p.stem.rsplit('_',1)[1]) for p in OUT.glob('minute_probe_*.py')]+[0])+1
    path=OUT/f'minute_probe_{index:02d}.py'
    path.write_text(source,encoding='utf8')
    print(json.dumps(dict(probe=path.name,requests=len(requests),missing=missing),ensure_ascii=False))

if __name__=='__main__': main()
