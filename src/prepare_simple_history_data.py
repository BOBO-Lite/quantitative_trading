"""生成已核验年度候选分钟及公司行动只读请求；持仓补齐每次最多30交易日。"""
import argparse,json
from pathlib import Path
from import_supermind_minute_probe import decode_packets
ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument('--year',type=int,required=True);p.add_argument('--supplement',action='store_true');p.add_argument('--continuous-end',type=int);a=p.parse_args()
    out=ROOT/'reports/simple_research'/str(a.year)
    screen=json.loads((out/'screen.json').read_text(encoding='utf8'))
    if screen['status']!='PASS_TECH1_HISTORY_SCREEN':raise ValueError('日线未核验')
    dates=[r['date'] for r in screen['days']]
    requests=sorted({(r['symbol'],r['entry_date']) for r in screen['minute_requests']})
    if a.supplement:
        missing_file=(ROOT/'reports/simple_research'/f'continuous_2018_{a.continuous_end}'/'missing_minutes.json') if a.continuous_end else out/'missing_minutes.json'
        missing=[r for r in json.loads(missing_file.read_text(encoding='utf8')) if r['date'].startswith(str(a.year))];existing=set()
        for f in out.glob('minute_export*.txt'):
            for k,v in decode_packets(f.read_text(encoding='utf8')).items():
                if k.startswith('minute_'):existing.add((v['symbol'],v['date']))
        requests=sorted({(r['symbol'],d) for r in missing for d in dates[dates.index(r['date']):dates.index(r['date'])+30]}-existing)
    if not requests:raise ValueError('没有待请求的分钟')
    source=(ROOT/'adapters/supermind_tech1_minute_probe.py').read_text(encoding='utf8')
    source='\n'.join('REQUESTS = '+repr(requests) if line.startswith('REQUESTS = ') else line for line in source.splitlines())+'\n'
    source=source.replace("'20181201'",repr(str(a.year-1)+'0901')).replace("'20190628'",repr(dates[-1].replace('-','')))
    (out/('supplement_probe.py' if a.supplement else 'minute_probe.py')).write_text(source,encoding='utf8')
    if not a.supplement:
        for start in range(0,len(requests),700):
            part='\n'.join('REQUESTS = '+repr(requests[start:start+700]) if line.startswith('REQUESTS = ') else line for line in source.splitlines())+'\n'
            (out/f'minute_probe_{start//700+1:02d}.py').write_text(part,encoding='utf8')
    if not a.supplement:
        symbols=sorted({s for s,d in requests})
        source=(ROOT/'adapters/supermind_tech1_corporate_probe.py').read_text(encoding='utf8')
        source='\n'.join('SYMBOLS = '+repr(symbols) if line.startswith('SYMBOLS = ') else line for line in source.splitlines())+'\n'
        source=source.replace('20190301',str(a.year)+'0101').replace('2019-03-01',str(a.year)+'-01-01').replace('20190628',dates[-1].replace('-','')).replace('2019-06-28',dates[-1])
        (out/'corporate_probe.py').write_text(source,encoding='utf8')
    print(dict(symbol_days=len(requests),symbols=len({s for s,d in requests}),supplement=a.supplement))

if __name__=='__main__':main()
