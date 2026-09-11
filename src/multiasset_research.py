"""ETF3固定资产源合并、3万元可买性审计与连续回放；保留原始包。"""
import base64,hashlib,json,zlib
from pathlib import Path
from collections import Counter
from etf_dataset import ROOT,build
from etf_replay import replay,size,tick
from import_supermind_minute_probe import decode_packets

OUT=ROOT/'reports/multiasset_research'
BASE=ROOT/'reports/etf_research/extended_2018_2026'
SYMBOLS=('510300.SH','511010.SH','518880.SH')

def merge(name):
    sources=[BASE/name,OUT/('raw_'+name)];combined={};provenance={}
    for source in sources:
        packets=decode_packets(source.read_text(encoding='utf8'))
        for k,v in packets.items():
            if '510500' in k:continue
            if k in combined and combined[k]!=v:raise ValueError('跨源重复包冲突：'+k)
            combined[k]=v;provenance.setdefault(k,[]).append(source.relative_to(ROOT).as_posix())
    lines=[]
    for k,v in sorted(combined.items()):
        raw=json.dumps(v,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('utf8');encoded=base64.b64encode(zlib.compress(raw)).decode('ascii')
        parts=[encoded[i:i+3000] for i in range(0,len(encoded),3000)]
        for i,p in enumerate(parts):lines.append(f'MINBUNDLE {k} {i} {len(parts)} {len(raw)} {hashlib.sha256(raw).hexdigest()} {p}')
    (OUT/name).write_text('\n'.join(lines)+'\n',encoding='utf8')
    (OUT/(name+'.provenance.json')).write_text(json.dumps(dict(note='仅重封已校验数据包，没有生成或修改行情',packets=provenance,source_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}),ensure_ascii=False,indent=2),encoding='utf8')

def inputs(minutes=True):
    merge('probe_export.txt')
    if minutes:merge('minute_export.txt')
    return build(minutes,out=OUT,symbols=SYMBOLS,corporate_dir=OUT)

def main():
    import sys
    if '--daily-only' in sys.argv:
        data=inputs(False);print('日线审计通过',len(data[0]),data[0][-1]);return
    data=inputs();summary=[];lot=[]
    for s in SYMBOLS:
        sample=data[1][s]
        values=[r['close']*100 for d,r in sample.items() if d>='2018-01-01']
        lot.append(dict(symbol=s,min_historical_one_lot=min(values),max_historical_one_lot=max(values),latest_one_lot=sample[data[0][-1]]['close']*100,
                        fixed_30000_gap_budget_position_cap=7500,latest_planned_quantity=size(tick(sample[data[0][-1]]['close']*1.02,False),tick(sample[data[0][-1]]['close']*1.02,False)*.94,30000,30000,0,0,1.)))
    for cost in (1.,1.5):
        r=replay(*data,cost=cost,end=data[0][-1],variant='ETF3.0',symbols=SYMBOLS)
        (OUT/f'cost{cost}.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf8')
        summary.append({k:r[k] for k in ('version','cost','status','days','final','metrics','block')})
        summary[-1]['fills_by_symbol']=dict(Counter(f['symbol'] for f in r['fills']))
    (OUT/'lot_feasibility.json').write_text(json.dumps(lot,ensure_ascii=False,indent=2),encoding='utf8')
    (OUT/'run_status.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
