"""合并已核验年度数据，从2018年初连续回放；不按年重置资金。"""
import argparse,ast,copy,json
from pathlib import Path
from import_supermind_minute_probe import decode_packets
from simple_minute_cache import Cache,MissingMinutes,first_entry_dates
from simple_corporate_events import build_events
from simple_minute_aliases import apply_aliases
from research_portfolio import run_bundle
from s2_strategy_rules import Policy
import simple_strategy_rules as rules
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'reports/simple_research'

def merge_cache(caches):
    result=Cache({})
    for cache in caches:
        for s,history in cache.daily.items():
            target=result.daily.setdefault(s,{})
            for d,row in history.items():
                if d in target and target[d]!=row:raise ValueError('跨年原始日线冲突：'+str((s,d)))
                target[d]=row
        for key,rows in cache.minutes.items():
            if key in result.minutes and result.minutes[key]!=rows:raise ValueError('跨年原始分钟冲突：'+str(key))
            result.minutes[key]=rows
        result.checks.extend(cache.checks)
    return result

def clean_boundary(day):
    result=copy.deepcopy(day)
    result['candidates']=[r for r in result['candidates'] if result['route']=='trend_breakout' and rules.needs_minutes(r,result['route'])]
    for r in result['candidates']:r.pop('listing_bars',None)
    return {k:result[k] for k in ('date','benchmark','route','candidates','universe_count')}

def load_inputs(end_year):
    caches=[];days={}
    for year in range(2018,end_year+1):
        folder=BASE/str(year);screen=json.loads((folder/'screen.json').read_text(encoding='utf8'))
        if screen['status']!='PASS_TECH1_HISTORY_SCREEN':raise ValueError('年度日线未通过')
        for day in screen['days']:
            date=day['date']
            if date in days and clean_boundary(day)!=clean_boundary(days[date]):raise ValueError('跨年信号边界冲突：'+date)
            days[date]=day
        packets={}
        for f in sorted(folder.glob('minute_export*.txt')):
            raw=f.read_text(encoding='utf8')
            if 'TECH1_ENTRY_MINUTE_EXPORT_DONE' not in raw:raise ValueError('分钟日志未完成')
            for key,value in decode_packets(raw).items():
                if key in packets and packets[key]!=value:raise ValueError('年度缓存冲突')
                packets[key]=value
        deferred=[]
        for f in sorted(folder.glob('prefetch_export*.txt')):
            raw=f.read_text(encoding='utf8')
            if 'TECH1_ENTRY_MINUTE_EXPORT_DONE' not in raw:raise ValueError('预取导出不完整')
            decoded=decode_packets(raw)
            source=folder/f'prefetch_probe_{f.stem[-2:]}.py'
            tree=ast.parse(source.read_text(encoding='utf8'))
            wanted=set(next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='REQUESTS' for t in n.targets)))
            received={(v['symbol'],v['date']) for k,v in decoded.items() if k.startswith('minute_')}
            if wanted!=received:raise ValueError('预取包集合与请求不一致：'+f.name)
            for key,value in decoded.items():
                if key.startswith('minute_') and len(value['dates'])!=240:
                    deferred.append(dict(symbol=value['symbol'],date=value['date'],rows=len(value['dates']),reason='incomplete optional prefetch; actual replay still requires complete minutes'));continue
                if key in packets and packets[key]!=value:raise ValueError('预取与已验收缓存冲突')
                packets[key]=value
        if deferred:(folder/'prefetch_deferred.json').write_text(json.dumps(deferred,ensure_ascii=False,indent=2),encoding='utf8')
        caches.append(Cache(apply_aliases(packets,folder)))
    return merge_cache(caches),[days[d] for d in sorted(days)]

def main():
    p=argparse.ArgumentParser();p.add_argument('--end-year',type=int,required=True);p.add_argument('--prepare',action='store_true');a=p.parse_args()
    if a.end_year not in range(2019,2027):raise ValueError('未登记范围')
    out=BASE/f'continuous_2018_{a.end_year}';out.mkdir(exist_ok=True)
    cache,days=load_inputs(a.end_year);calendar=[d['date'] for d in days]
    if a.prepare:
        source=(ROOT/'adapters/supermind_tech1_corporate_probe.py').read_text(encoding='utf8')
        source='\n'.join('SYMBOLS = '+repr(sorted(cache.daily)) if line.startswith('SYMBOLS = ') else line for line in source.splitlines())+'\n'
        source=source.replace('20190301','20180101').replace('2019-03-01','2018-01-01').replace('20190628',calendar[-1].replace('-','')).replace('2019-06-28',calendar[-1])
        (out/'corporate_probe.py').write_text(source,encoding='utf8')
        print(dict(status='INPUT_BOUNDARIES_PASS',days=len(days)-1,symbols=len(cache.daily),cached_stock_days=len(cache.minutes)));return
    raw=(out/'corporate_export.txt').read_text(encoding='utf8')
    if 'TECH1_CORPORATE_EXPORT_DONE' not in raw:raise ValueError('连续公司行动导出未完成')
    packets=decode_packets(raw);cash=[];unknown=[];unsupported=[];first=first_entry_dates(days)
    for s in sorted(cache.daily):
        try:
            events,other=build_events(packets,[s],first.get(s,calendar[1]));cash.extend(events);unsupported.extend(other)
        except (ValueError,KeyError) as exc:unknown.append(dict(symbol=s,error=str(exc)))
    closes=cache.closing_many(calendar[1:],out/'close_features_cache.json')
    bundle=dict(research_version=rules.VERSION,source_kind='VERIFIED_CONTINUOUS_HISTORY',initial_cash=30000.,calendar=calendar,record_minute_curve=True,corporate_events=cash,unresolved_corporate_symbols=sorted({r['symbol'] for r in unknown}),unsupported_corporate_events=unsupported,
        days=[dict(date=calendar[i],previous_close=dict(date=calendar[i-1],benchmark=days[i-1]['benchmark'],stocks=days[i-1]['candidates']),close_features=closes[i-1]) for i in range(1,len(calendar))])
    (out/'corporate_events.json').write_text(json.dumps(dict(cash=cash,unknown=unknown,unsupported=unsupported),ensure_ascii=False,indent=2),encoding='utf8')
    missing=[];statuses=[]
    for cost in (1.,1.5):
        try:
            result=run_bundle(bundle,Policy(cost_multiplier=cost),rules=rules,minute_loader=cache.load)
            (out/f'cost{cost}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
            statuses.append(dict(cost=cost,status='COMPLETED'))
            print(dict(cost=cost,final=result['final'],metrics=result['metrics'],fills=len(result['fills'])))
        except MissingMinutes as exc:
            missing.extend(exc.requests);statuses.append(dict(cost=cost,status='MISSING_MINUTES',requests=exc.requests));print(dict(cost=cost,missing=exc.requests))
        except ValueError as exc:
            row=dict(cost=cost,status='BLOCKED_REPLAY',error=str(exc));statuses.append(row);print(row)
    unique=[dict(symbol=s,date=d) for s,d in sorted({(r['symbol'],r['date']) for r in missing})]
    (out/'missing_minutes.json').write_text(json.dumps(unique,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'run_status.json').write_text(json.dumps(statuses,ensure_ascii=False,indent=2),encoding='utf8')

if __name__=='__main__':main()
