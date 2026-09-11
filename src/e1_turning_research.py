"""Price-extrema diagnosis followed by causal rule comparisons in one loaded cache."""
import json,time,importlib
from pathlib import Path
from recovery_research import prepare,check_supplement
from exit_extension_research import read_export
from simple_history_replay import merge_cache
from simple_minute_cache import MissingMinutes
from research_portfolio import run_bundle
from s2_strategy_rules import Policy

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/e1_turning'
def save(name,value):(OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')

def resolve_known_rights_event(bundle):
    # Data correction only: a documented rights issue is not a zero dividend.
    # Keep the engine's actual-record-date holding guard; never exclude the stock.
    from copy import deepcopy
    from import_supermind_minute_probe import decode_packets
    from simple_corporate_events import build_events
    symbol='600919.SH';stamp='2020-12-17T00:00:00.000Z'
    packets=decode_packets((ROOT/'reports/exit_research/extension_2020/corporate_export.txt').read_text(encoding='utf8'))
    selected={k:deepcopy(packets[k]) for k in ('dividend_'+symbol,'details_'+symbol)}
    data=selected['dividend_'+symbol]['data']
    assert data['symbol'][stamp]==symbol
    assert all(data[k][stamp]==0 for k in ('cash_dividends','give_stock','transfer_stock'))
    assert set(data['symbol'])=={'2020-06-24T00:00:00.000Z',stamp}
    for values in data.values():values.pop(stamp)
    cash,other=build_events(selected,[symbol],'2020-01-01')
    assert len(cash)==1 and cash[0]['cash_per_share']==.278 and not other
    assert not any(e['symbol']==symbol and e['ex_date'].startswith('2020') for e in bundle['corporate_events'])
    issue=dict(symbol=symbol,record_date='2020-12-08',ex_date='2020-12-17',event_type='rights_issue',rights_per_share=.3,subscription_price=4.59)
    fixed=dict(bundle,corporate_events=bundle['corporate_events']+cash,
               unsupported_corporate_events=bundle['unsupported_corporate_events']+[issue],
               unresolved_corporate_symbols=[s for s in bundle['unresolved_corporate_symbols'] if s!=symbol])
    save('corporate_resolution.json',dict(symbol=symbol,source_url='https://epaper.cs.com.cn/zgzqb/html/2020-12/17/nw.D110000zgzqb_20201217_10-A07.htm',announcement='江苏银行2020-073配股发行结果公告',announcement_date='2020-12-17',cash_events=cash,rights_issue=issue,handling='Retain original actual-record-date holding guard. Stop if an account holds this stock on the rights record date; do not assume free shares or exclude earlier entries. Other unresolved symbols stay blocked.'))
    return fixed

def diagnose(cache,bundle):
    symbol='002317.SZ';start='2019-12-25';end='2020-02-03'
    original=json.loads((ROOT/'reports/exit_research/extension_2020/E1_cost1.0.json').read_text(encoding='utf8'))
    extended=json.loads((ROOT/'reports/e1_asymmetric/W_cost1.0.json').read_text(encoding='utf8'))
    fills={name:[f for f in result['fills'] if f['symbol']==symbol and start<=f['fill_time'][:10]<=end] for name,result in [('E1',original),('W',extended)]}
    buy=fills['E1'][0];factor=cache.daily[symbol][start]['factor'];bars=[];daily=[]
    for day in bundle['days']:
        d=day['date']
        if not start<=d<=end:continue
        minute=cache.minutes[symbol,d];pre=day['previous_close']['benchmark'];cl=day['close_features']['stocks'][symbol]
        daily.append(dict(date=d,raw_daily=cache.daily[symbol][d],close_features=cl,prior_market=pre,first_minutes=minute[:4],last_minute=minute[-1]))
        bars += [b for b in minute if b['datetime']>=buy['fill_time']]
    peak=max(bars,key=lambda b:b['high']*b['factor']);trough=min(bars,key=lambda b:b['low']*b['factor'])
    best_entry=None;best_pair=None
    for b in bars:
        # Hindsight envelope: earlier-day low then later-day high; not executable fills.
        earlier=[v for v in bars if v['datetime'][:10]<b['datetime'][:10]]
        if not earlier:continue
        low=min(earlier,key=lambda x:x['low']*x['factor'])
        gain=b['high']*b['factor']/(low['low']*low['factor'])-1
        if best_pair is None or gain>best_pair['return']:best_pair=dict(buy_time=low['datetime'],buy_low=low['low'],sell_time=b['datetime'],sell_high=b['high'],**{'return':gain})
    # Record extrema for every original trade, without using them as signal inputs.
    opened={};cases=[]
    for f in original['fills']:
        s=f['symbol']
        if f['buy']:opened[s]=f;continue
        b=opened.pop(s);window=[]
        for d in bundle['calendar']:
            if b['fill_time'][:10]<=d<=f['fill_time'][:10]:window += [x for x in cache.minutes[s,d] if b['fill_time']<=x['datetime']<f['fill_time']]
        base_factor=cache.daily[s][b['fill_time'][:10]]['factor']
        maxbar=max(window,key=lambda x:x['high']*x['factor']);minbar=min(window,key=lambda x:x['low']*x['factor'])
        after=[x for x in window if x['datetime']>minbar['datetime']]
        rebound=max(after,key=lambda x:x['high']*x['factor']) if after else None
        cases.append(dict(symbol=s,buy=b,sell=f,peak_time=maxbar['datetime'],peak_gain_pct=(maxbar['high']*maxbar['factor']/(b['price']*base_factor)-1)*100,trough_time=minbar['datetime'],trough_return_pct=(minbar['low']*minbar['factor']/(b['price']*base_factor)-1)*100,best_rebound_after_trough_pct=(rebound['high']*rebound['factor']/(b['price']*base_factor)-1)*100 if rebound else None,rebound_time=rebound['datetime'] if rebound else None))
    save('case_002317.json',dict(fills=fills,daily=daily,peak=peak,trough=trough,oracle_ordered_tplus1_price_envelope=best_pair,warning='Extrema are hindsight high/low prices, not executable prices. Study interval fixed by the two historical trade paths; no forecast claim.'))
    save('original_trade_extrema.json',dict(scope='actual holding windows only; no post-exit rebound claim',cases=cases))
    print('DIAGNOSIS_READY '+json.dumps(dict(fills=fills,peak=peak,trough=trough,oracle=best_pair)),flush=True)

def main():
    OUT.mkdir(exist_ok=True);cache,bundle=prepare();bundle=resolve_known_rights_event(bundle)
    for folder in ('e1_rank_research','e1_conditions','e1_loss_signals','e1_asymmetric'):
        for p in sorted((ROOT/'reports'/folder).glob('minute_export_*.txt')):cache=merge_cache([cache,read_export(p)])
    diagnose(cache,bundle)
    while not (OUT/'run_request.json').exists():time.sleep(1)
    request=json.loads((OUT/'run_request.json').read_text(encoding='utf8'))
    module=importlib.import_module('e1_turning_rules');loaded=set()
    statuses=json.loads((OUT/'run_status.json').read_text(encoding='utf8')) if (OUT/'run_status.json').exists() else []
    def extra():
        nonlocal cache
        for p in sorted(set(OUT.glob('minute_export_*.txt'))-loaded):
            c=read_export(p);check_supplement(c,cache);cache=merge_cache([cache,c]);loaded.add(p)
    extra()
    wanted=[(mode,cost) for mode in request['modes'] for cost in (1.,1.5)]
    while len(statuses)<len(wanted):
        completed={(r['mode'],r['cost']) for r in statuses};missing=set()
        for mode,cost in wanted:
            if (mode,cost) in completed:continue
            rules=module.TurningRules(mode)
            try:
                result=run_bundle(bundle,Policy(cost_multiplier=cost),rules=rules,minute_loader=cache.load)
                save(f'{mode}_cost{cost}.json',result);save(f'{mode}_cost{cost}_events.json',rules.events)
                row=dict(mode=mode,cost=cost,status='COMPLETED',metrics=result['metrics'],final=result['final'],fills=len(result['fills']));statuses.append(row);save('run_status.json',statuses);print(json.dumps(row),flush=True)
            except MissingMinutes as e:
                missing.update((r['symbol'],r['date']) for r in e.requests)
        if missing:
            requests=[dict(symbol=s,date=d) for s,d in sorted(missing)]
            save('missing_minutes.json',requests);print('AWAIT_TURNING_MINUTES '+json.dumps(requests),flush=True)
            while not set(OUT.glob('minute_export_*.txt'))-loaded:time.sleep(1)
            extra()
    save('missing_minutes.json',[])

if __name__=='__main__':main()
