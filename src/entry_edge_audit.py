"""Validate and compare prespecified daily signal-price diagnostics."""
import json,hashlib
from pathlib import Path
from statistics import mean,median
from collections import Counter
from import_supermind_minute_probe import decode_packets,LINE
import simple_strategy_rules as rules
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/entry_edge'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def save(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')

def normalize(year):
    raw=(OUT/f'raw_{year}.txt').read_text(encoding='utf8')
    assert 'ENTRY_EDGE_EXPORT_DONE' in raw and '日志条数超过限制' not in raw
    lines=[]
    for line in raw.splitlines():
        line=line.strip().removeprefix('- generic: ')
        if LINE.fullmatch(line):lines.append(line)
    packets=decode_packets('\n'.join(lines));meta=packets.pop('edge_meta')
    request=read(OUT/f'requests_{year}.json')
    assert meta['year']==year and meta['signal_dates']==sorted(request)
    assert set(packets)=={'edge_'+d for d in request}
    originals={d['date']:d for d in read(ROOT/f'reports/simple_research/{year}/screen.json')['days']}
    diagnostics=[];checks=0
    for day in request:
        p=packets['edge_'+day];original={r['symbol']:r for r in originals[day]['candidates']}
        assert sorted(r['symbol'] for r in p['fh'])==sorted(request[day]),'candidate coverage '+day
        assert len(p['members'])==len(set(p['members']))
        for row in p['fh']:
            old=original[row['symbol']]
            assert abs(row['signal_close']-old['raw_close'])<1e-8
            assert abs(row['signal_factor']-old['factor'])<1e-8
            assert abs(row['amount20']-old['amount20'])<max(1e-5,old['amount20']*1e-12)
            checks+=1
        for row in p['fh']+p['momentum']:
            for h,r in row['outcomes'].items():
                if r['status']=='OK':
                    assert abs(r['ret']-(r['close']*r['end_factor']/(r['open']*r['entry_factor'])-1))<1e-12
                    assert day<p['windows'][h]['entry']<=p['windows'][h]['end']
        assert p['momentum']==sorted(p['momentum'],key=lambda r:(-r['mom60'],r['symbol']))
        assert all(r['mom60']>0 and r['above_ma60'] for r in p['momentum'])
        diagnostics.extend(dict(date=day,symbol=s,error=e) for s,e in p['errors'])
    save(f'data_{year}.json',packets)
    save(f'audit_{year}.json',dict(signal_input_checks=checks,errors=diagnostics,
        raw_sha256=hashlib.sha256((OUT/f'raw_{year}.txt').read_bytes()).hexdigest(),dates=len(request)))
    print(year,checks,'errors',len(diagnostics),Counter(r['error'] for r in diagnostics),flush=True)

def report():
    packets={}
    for year in (2018,2019,2020):packets.update(read(OUT/f'data_{year}.json'))
    calendar=sorted({d['date'] for year in (2018,2019,2020) for d in read(ROOT/f'reports/simple_research/{year}/screen.json')['days']})
    actual={}
    for cost in (1.,1.5):
        actual[cost]={(f['symbol'],calendar[calendar.index(f['intent_time'][:10])-1]) for f in read(ROOT/f'reports/e1_reentry_pair/FH_cost{cost}.json')['fills'] if f['buy']}
    daily=[];signal_rows=[]
    for p in packets.values():
        day=p['date']
        for row in p['fh']:
            for h,o in row['outcomes'].items():signal_rows.append(dict(date=day,symbol=row['symbol'],horizon=int(h),**o,actual_cost1=(row['symbol'],day) in actual[1.],actual_cost15=(row['symbol'],day) in actual[1.5]))
        for h in ('5','20','60'):
            window=p['windows'][h]
            if window is None:continue
            market=window['close']/window['open']-1;pool=p['pool_stats'][h]
            pool_mean=pool['sum']/pool['valid'] if pool['valid'] else None
            groups={'FH_ALL':p['fh'],'FH_TOP5':sorted(p['fh'],key=lambda r:(-r['amount20'],r['symbol']))[:5],'MOM_TOP5':p['momentum']}
            for label,rows in groups.items():
                valid=[r['outcomes'][h] for r in rows if r['outcomes'][h]['status']=='OK']
                # Keep gaps in coverage; report available-price averages explicitly.
                daily.append(dict(date=day,horizon=int(h),group=label,n=len(rows),valid=len(valid),
                    mean_return=mean(r['ret'] for r in valid) if valid else None,
                    market=market,pool=pool_mean,pool_n=pool['n'],pool_valid=pool['valid'],
                    untradable=sum(r['entry_paused'] or r['entry_st'] or r['entry_at_limit'] for r in valid),
                    source_errors=len(p['errors'])))
    save('signal_cases.json',signal_rows);save('daily_comparison.json',daily)
    summary=[]
    for year in ('ALL','2018','2019','2020'):
        for h in (5,20,60):
            for group in ('FH_ALL','FH_TOP5','MOM_TOP5'):
                rs=[r for r in daily if (year=='ALL' or r['date'].startswith(year)) and r['horizon']==h and r['group']==group]
                rs=[r for r in rs if r['mean_return'] is not None and r['pool'] is not None]
                summary.append(dict(year=year,horizon=h,group=group,dates=len(rs),
                    mean_pct=mean(r['mean_return'] for r in rs)*100 if rs else None,
                    excess_pool_pct=mean(r['mean_return']-r['pool'] for r in rs)*100 if rs else None,
                    excess_market_pct=mean(r['mean_return']-r['market'] for r in rs)*100 if rs else None,
                    outperform_pool_dates=sum(r['mean_return']>r['pool'] for r in rs),
                    missing=sum(r['n']-r['valid'] for r in rs),untradable=sum(r['untradable'] for r in rs)))
    save('summary.json',summary)
    actual_summary=[]
    for cost,flag in ((1.,'actual_cost1'),(1.5,'actual_cost15')):
        for h in (5,20,60):
            for filled in (True,False):
                rs=[r for r in signal_rows if r['horizon']==h and r[flag]==filled and r['status']=='OK']
                actual_summary.append(dict(cost=cost,horizon=h,actually_filled=filled,n=len(rs),mean_pct=mean(r['ret'] for r in rs)*100 if rs else None,median_pct=median(r['ret'] for r in rs)*100 if rs else None))
    save('actual_vs_unfilled.json',actual_summary)
    print(json.dumps([r for r in summary if r['year']=='ALL'],ensure_ascii=False),flush=True)

if __name__=='__main__':
    import sys
    assert hashlib.sha256((OUT/'PROTOCOL.md').read_bytes()).hexdigest()==read(OUT/'protocol_lock.json')['sha256']
    if len(sys.argv)>1:normalize(int(sys.argv[1]))
    else:report()
