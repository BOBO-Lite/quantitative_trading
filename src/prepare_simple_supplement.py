"""只扩展回放实际缺少的持仓股票至固定季度终点，不按收益挑选覆盖。"""
import json
from pathlib import Path
from import_supermind_minute_probe import decode_packets
ROOT=Path(__file__).resolve().parents[1]

def main():
    out=ROOT/'reports/simple_research'
    missing=json.loads((out/'missing_minutes.json').read_text(encoding='utf8'))
    if not missing:raise ValueError('当前没有分钟缺口')
    days=[d['date'] for d in json.loads((out/'quarter_screen.json').read_text(encoding='utf8'))['days']]
    existing=set()
    for f in out.glob('minute_export*.txt'):
        for k,p in decode_packets(f.read_text(encoding='utf8')).items():
            if k.startswith('minute_'):existing.add((p['symbol'],p['date']))
    requests=sorted({(r['symbol'],day) for r in missing for day in days if day>=r['date']} - existing)
    source=(ROOT/'adapters/supermind_tech1_minute_probe.py').read_text(encoding='utf8')
    source='\n'.join('REQUESTS = '+repr(requests) if line.startswith('REQUESTS = ') else line for line in source.splitlines())+'\n'
    (ROOT/'adapters/supermind_tech1_supplement_probe.py').write_text(source,encoding='utf8')
    print(dict(symbols=sorted({s for s,d in requests}),symbol_days=len(requests)))

if __name__=='__main__':main()
