"""仅为真实缺口追加固定27交易日窗口，不根据收益选取股票。"""
import json
from exit_extension_research import OUT, ROOT

def main():
    missing=json.loads((OUT/'missing_minutes.json').read_text(encoding='utf8'))
    days=[d['date'] for d in json.loads((ROOT/'reports/simple_research/2020/screen.json').read_text(encoding='utf8'))['days']]
    requests=set()
    for row in missing:
        i=days.index(row['date'])
        requests.update((row['symbol'],day) for day in days[i:i+27])
    if not requests: raise ValueError('没有待补真实持仓缺口')
    index=max(int(p.stem.rsplit('_',1)[1]) for p in OUT.glob('minute_probe_*.py'))+1
    source=(OUT/'minute_probe_01.py').read_text(encoding='utf8')
    source='\n'.join('REQUESTS = '+repr(sorted(requests)) if line.startswith('REQUESTS = ') else line for line in source.splitlines())+'\n'
    path=OUT/f'minute_probe_{index:02d}.py'
    path.write_text(source,encoding='utf8')
    print(json.dumps(dict(probe=path.name,requests=len(requests),missing=missing),ensure_ascii=False))

if __name__=='__main__': main()
