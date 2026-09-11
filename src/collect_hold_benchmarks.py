"""Read existing signed export packets for fixed benchmark/entry cases only."""
import json,hashlib
from pathlib import Path
from import_supermind_minute_probe import LINE,decode_packets
from simple_minute_cache import rows
from simple_corporate_events import build_events
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/hold_benchmarks'
def main():
    wanted={'000425.SZ','601009.SH'}
    for cost in (1.,1.5):
        r=json.loads((ROOT/f'reports/e1_reentry_pair/FH_cost{cost}.json').read_text(encoding='utf8'))
        wanted.update(f['symbol'] for f in r['fills'] if f['buy'])
    keys={prefix+s for prefix in ('daily_','dividend_','details_') for s in wanted}
    daily={s:{} for s in wanted};events={s:{} for s in wanted};unsupported={s:{} for s in wanted};conflicts=[];sources=[];errors=[]
    paths=sorted(set((ROOT/'reports').rglob('minute_export*.txt'))|set((ROOT/'reports').rglob('corporate_export*.txt')))
    for p in paths:
        raw=p.read_text(encoding='utf8');parts=[m.group(0) for m in LINE.finditer(raw) if m[1] in keys]
        if not parts:continue
        packets=decode_packets('\n'.join(parts));used=[]
        for k,packet in packets.items():
            if not k.startswith('daily_'):continue
            s=packet['symbol'];used.append(k)
            for r in rows(packet):
                d=r['datetime'][:10]
                if not '2017-12-01'<=d<='2020-12-31':continue
                if d in daily[s]:
                    old=daily[s][d]
                    if any(old.get(f)!=r.get(f) for f in ('open','high','low','close','factor','is_paused')):
                        conflicts.append(dict(symbol=s,date=d,file=str(p.relative_to(ROOT))))
                else:daily[s][d]=r
        for s in wanted:
            if 'dividend_'+s not in packets or 'details_'+s not in packets:continue
            try:
                cash,other=build_events(packets,[s],start='2018-01-01')
                for e in cash:
                    if e['ex_date']>'2020-12-31':continue
                    v={k:v for k,v in e.items() if k!='source_rows_merged'};old=events[s].get(e['ex_date'])
                    if old and old!=v:conflicts.append(dict(symbol=s,event=e['ex_date'],file=str(p.relative_to(ROOT))))
                    events[s][e['ex_date']]=v
                for e in other:
                    if e['ex_date']<='2020-12-31':unsupported[s][e['ex_date']]=e
                used+=['dividend_'+s,'details_'+s]
            except (ValueError,KeyError) as e:errors.append(dict(symbol=s,file=str(p.relative_to(ROOT)),error=str(e)))
        sources.append(dict(file=str(p.relative_to(ROOT)),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),keys=used))
    result=dict(daily=daily,events={s:list(v.values()) for s,v in events.items()},unsupported={s:list(v.values()) for s,v in unsupported.items()},conflicts=conflicts,errors=errors,sources=sources)
    (OUT/'historical_inputs.json').write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')),encoding='utf8')
    print(json.dumps(dict(symbols=len(wanted),days={s:len(d) for s,d in daily.items()},conflicts=len(conflicts),source_errors=len(errors),sources=len(sources))))
if __name__=='__main__':main()
