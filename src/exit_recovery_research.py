"""Causal one-shot reclaim entries after FH protective exits; isolated cash sleeves."""
import json,hashlib,math
from pathlib import Path
from statistics import mean,median
from hold_benchmarks import trade_batches,original_pnl
from research_execution import ReplayBroker
from s2_strategy_rules import Policy,fee
from simple_strategy_rules import research_regime
from import_supermind_minute_probe import LINE,decode_packets
from simple_minute_cache import rows as packet_rows

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/exit_recovery'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def save(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')

def features(history,day,trigger,events):
    dates=sorted(d for d in history if d<=day)
    if len(dates)<10 or dates[-1]!=day:raise ValueError('missing_feature_warmup')
    bar=history[day]
    ma=mean(history[d]['close']*history[d]['factor'] for d in dates[-10:])/bar['factor']
    level=trigger['stop']-sum(e['cash_per_share'] for e in events if trigger['trigger_time'][:10]<e['ex_date']<=day)
    return bar['close'],level,ma

def first_signal(history,calendar,exit_day,trigger,events,mode):
    start=calendar.index(exit_day)
    for i in range(start+1,min(start+21,len(calendar))):
        day=calendar[i];prior=calendar[i-1]
        c,level,ma=features(history,day,trigger,events)
        pc,pl,_=features(history,prior,trigger,events)
        if not history[day]['is_paused'] and pc<=pl and c>level and (mode=='L' or c>ma):return day
    return None

def minute_index(wanted):
    keys={'minute_'+d+'_'+s for s,d in wanted};found={};sources=[]
    for p in sorted((ROOT/'reports').rglob('minute_export*.txt')):
        text=p.read_text(encoding='utf8')
        selected=[m.group(0) for m in LINE.finditer(text) if m[1] in keys]
        if not selected:continue
        packets=decode_packets('\n'.join(selected))
        for packet in packets.values():
            key=packet['symbol'],packet['date'];bars=packet_rows(packet)
            if key in found:assert found[key]==bars,'conflicting_minute_source'
            found[key]=bars
        sources.append(dict(file=p.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    save('minute_sources.json',sources)
    return found

def simulate(case,minutes,data,calendar,bench):
    symbol=case['symbol'];history=data['daily'][symbol];cash=case['starting_cash'];signal=case['signal']
    if not signal:return dict(status='NO_SIGNAL',increment=0.,fills=[],daily=[])
    if any(e['symbol']==symbol for e in data['errors']+data['conflicts']):raise ValueError('unresolved_corporate_source')
    start_i=calendar.index(signal)+1;end_i=calendar.index(case['end'])
    if start_i>end_i:return dict(status='SIGNAL_TOO_LATE',increment=0.,fills=[],daily=[])
    start=calendar[start_i]
    events=[e for e in data['events'][symbol] if start<=e['record_date']<=case['end']]
    broker=ReplayBroker(cash=cash,policy=Policy(cost_multiplier=case['cost']),corporate_events=events)
    pending=None;entered=None;curve=[];decisions=[]
    for i in range(start_i,end_i+1):
        day=calendar[i];prior=calendar[i-1]
        bm=bench[prior];route=research_regime(*(bm[k] for k in ('close','ma20','ma60','slope5','ret20')))
        # Empty sleeves still process the dividend book, but need no fictitious price bars.
        needs_bars=day==start or bool(broker.positions)
        if needs_bars:
            if (symbol,day) not in minutes:raise ValueError('missing_minutes:'+symbol+':'+day)
            bars=minutes[symbol,day]
            from research_portfolio import session_minutes
            assert [b['datetime'] for b in bars]==session_minutes(day)
            ref=history[day]
            assert abs(bars[-1]['close']-ref['close'])<1e-7
            assert abs(sum(b['volume'] for b in bars)-ref['volume'])<max(1,ref['volume']*1e-6)
            for raw in bars:
                bar=dict(raw,**{k:ref[k] for k in ('factor','is_paused','is_st','high_limit','low_limit')})
                bar['is_paused']=bool(bar['is_paused']);bar['is_st']=bool(bar['is_st'])
                stamp=bar['datetime'];broker.on_minute(stamp,{symbol:bar})
                if entered is None and broker.positions:entered=day
                if broker.positions and entered!=day and (pending or route=='defensive_cash'):
                    if not pending:
                        pending='market_defense';decisions.append(dict(date=stamp,reason=pending))
                    if not bar['is_paused']:
                        broker.submit(symbol,broker.positions[symbol].quantity,stamp,False,broker.positions[symbol].factor)
                if day==start and stamp.endswith('09:31:00'):
                    if route=='defensive_cash':decisions.append(dict(date=day,reason='entry_market_defense'))
                    else:
                        limit=math.floor(history[signal]['close']*1.04*100+1e-8)/100
                        qty=min(case['original_quantity'],int(cash/limit/100)*100)
                        while qty and qty*limit+fee(qty*limit,multiplier=case['cost'])>cash:qty-=100
                        if qty:broker.submit(symbol,qty,stamp,True,bar['factor'],limit)
                        else:decisions.append(dict(date=day,reason='insufficient_round_lot_cash'))
            if broker.positions:
                c,level,ma=features(history,day,case['trigger'],data['events'][symbol])
                reason='recovery_failed' if c<=level or c<ma else 'reentry_time_exit' if i-calendar.index(entered)+1>=20 else None
                if reason and not pending:pending=reason;decisions.append(dict(date=day,reason=reason,close=c,level=level,ma10=ma))
                for e in data['unsupported'][symbol]:
                    if e['record_date']==day:raise ValueError('unsupported_share_action')
            broker.close_day(day)
        else:
            broker.cash+=broker.corporate.open_day(day);broker.corporate.close_day(day,{})
        curve.append(dict(date=day,**broker.snapshot()))
    for o in broker.orders:
        if o['status']=='PENDING':o['status']='EXPIRED_END_OF_SAMPLE'
    independent=cash+sum((-1 if f['buy'] else 1)*f['quantity']*f['price']-f['fees'] for f in broker.fills)+broker.corporate.gross_income-broker.corporate.tax_paid-broker.corporate.receivable
    assert abs(independent-broker.cash)<1e-6
    peak=cash;worst=0.
    for point in curve:
        peak=max(peak,point['equity']);worst=max(worst,1-point['equity']/peak)
    return dict(status='COMPLETE' if entered else 'NO_FILL',increment=broker.equity-cash,
        max_daily_drawdown_pct=worst*100,
        fills=broker.fills,orders=broker.orders,daily=curve,decisions=decisions,final=broker.snapshot(),corporate_ledger=broker.corporate.ledger)

def main():
    assert hashlib.sha256((OUT/'PROTOCOL.md').read_bytes()).hexdigest()==read(OUT/'protocol_lock.json')['sha256']
    data=read(ROOT/'reports/hold_benchmarks/historical_inputs.json')
    bench={d['date']:d['benchmark'] for y in (2018,2019,2020) for d in read(ROOT/f'reports/simple_research/{y}/screen.json')['days']}
    calendar=sorted(d for d in bench if '2018-01-01'<=d<='2020-12-31')
    cases=[];wanted=set()
    for cost in (1.0,1.5):
        trades=trade_batches(read(ROOT/f'reports/e1_reentry_pair/FH_cost{cost}.json'))
        lookup={(t['buy']['symbol'],t['buy']['fill_time'][:10]):t for t in trades}
        for trigger in read(ROOT/f'reports/exit_horizon/triggers_cost{cost}.json'):
            if trigger['reason']!='close_confirmed_stop':continue
            symbol=trigger['symbol'];entry=trigger['entry_date'];trade=lookup[symbol,entry];buy=trade['buy'];exit_day=trade['sells'][-1]['fill_time'][:10]
            # Existing original sleeves have no unpaid dividend assumption hidden in cash.
            assert not any(entry<=e['record_date']<exit_day and e['pay_date']>exit_day for e in data['events'][symbol]),'unpaid_original_dividend'
            capital=buy['price']*buy['quantity']+buy['fees'];original=original_pnl(trade,data['events'][symbol])
            end=calendar[calendar.index(entry)+59]
            for mode in ('L','LM'):
                signal=first_signal(data['daily'][symbol],calendar,exit_day,trigger,data['events'][symbol],mode)
                case=dict(cost=cost,mode=mode,symbol=symbol,entry=entry,exit=exit_day,end=end,signal=signal,trigger=trigger,
                    original_quantity=buy['quantity'],original_capital=capital,original_profit=original,starting_cash=capital+original)
                cases.append(case)
                if signal:
                    wanted.update((symbol,d) for d in calendar if signal<d<=end)
    save('signals.json',cases);print('SIGNALS '+str(sum(bool(c['signal']) for c in cases))+'/'+str(len(cases)),flush=True)
    minutes=minute_index(wanted);save('available_minutes.json',[dict(symbol=s,date=d) for s,d in sorted(minutes)])
    results=[];missing=set()
    for index,case in enumerate(cases):
        try:result=simulate(case,minutes,data,calendar,bench)
        except ValueError as e:
            result=dict(status='BLOCKED',reason=str(e))
            if str(e).startswith('missing_minutes:'):
                _,s,d=str(e).split(':');missing.add((s,d))
        save(f'case_{index:02d}.json',dict(case=case,result=result))
        results.append(dict(**{k:case[k] for k in ('cost','mode','symbol','entry','signal')},
            **{k:result[k] for k in ('status','reason','increment') if k in result},
            increment_pct=result.get('increment',0)/case['original_capital']*100 if result['status']!='BLOCKED' else None))
    save('results.json',results);save('missing_minutes.json',[dict(symbol=s,date=d) for s,d in sorted(missing)])
    print(json.dumps(results,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
