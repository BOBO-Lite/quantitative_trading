"""Replay the cited trade with its original buy fixed, to isolate the exit repair."""
import json
from run_e1_confirmation import ROOT,OUT,save
from e1_confirmation import ConfirmationRules,prior_features,MODES
from import_supermind_minute_probe import decode_packets
from simple_minute_cache import Cache
from simple_history_replay import merge_cache
from research_execution import ReplayBroker
from e1_asymmetric import AsymmetricRules
from e1_turning_rules import TurningRules
import simple_strategy_rules as base

def main():
    symbol='002317.SZ';case=json.loads((ROOT/'reports/e1_turning/case_002317.json').read_text(encoding='utf8'));buy=case['fills']['E1'][0]
    files=list((ROOT/'reports/simple_research/2019').glob('minute_export*.txt'))+[ROOT/'reports/simple_research/2019/prefetch_export02.txt',ROOT/'reports/exit_research/extension_2020/minute_export_02.txt']
    caches=[]
    for path in files:
        raw=path.read_text(encoding='utf8');assert 'TECH1_ENTRY_MINUTE_EXPORT_DONE' in raw
        packets={k:v for k,v in decode_packets(raw).items() if v.get('symbol')==symbol and (k.startswith('daily_') or k.startswith('minute_'))}
        if packets:caches.append(Cache(packets))
    cache=merge_cache(caches)
    old=json.loads((ROOT/'reports/exit_research/extension_2020/E1_cost1.0.json').read_text(encoding='utf8'))
    order=next(o for o in old['orders'] if o['order_id']==buy['order_id'])
    screen=json.loads((ROOT/'reports/simple_research/2019/screen.json').read_text(encoding='utf8'))
    signal=next(r for d in screen['days'] if d['date']=='2019-12-24' for r in d['candidates'] if r['symbol']==symbol)
    benchmarks={}
    for year in (2018,2019,2020):
        for d in json.loads((ROOT/f'reports/simple_research/{year}/screen.json').read_text(encoding='utf8'))['days']:benchmarks[d['date']]=d['benchmark']['close']
    output={}
    for mode in ('E1','W','P')+MODES:
        rules=TurningRules('P') if mode=='P' else AsymmetricRules('W' if mode=='W' else '')
        if mode in MODES:rules=ConfirmationRules(mode)
        broker=ReplayBroker(30000.);p=None;scheduled=False;seen=0
        for day in case['daily']:
            date=day['date'];benchmark=day['prior_market'];route=rules.research_regime(benchmark['close'],benchmark['ma20'],benchmark['ma60'])
            prior_dates=sorted(d for d in benchmarks if d<date)
            feature=prior_features(cache.daily[symbol],prior_dates[-1],benchmarks[prior_dates[-1]]/benchmarks[prior_dates[-6]]-1)
            for original_bar in cache.minutes[symbol,date]:
                bar=dict(original_bar,confirmation=feature,symbol=symbol)
                t=bar['datetime']
                if t<buy['intent_time']:continue
                assert bar['factor']==signal['factor'],'case requires dividend-aware extension'
                broker.on_minute(t,{symbol:bar})
                if t==buy['intent_time']:broker.submit(symbol,buy['quantity'],t,True,bar['factor'],order['limit'])
                for fill in broker.fills[seen:]:
                    if fill['buy']:
                        price=fill['price'];distance=base.stop_distance(signal,price)
                        p=dict(entry_date=date,entry_price=price,initial_r=price*distance,stop=price*(1-distance),quantity=fill['quantity'],route=route,target_ma20=signal['target_ma20_raw'],highest_close=price,holding_days=0)
                seen=len(broker.fills)
                if p and symbol in broker.positions and date>p['entry_date']:
                    reason='scheduled_exit' if scheduled else rules.exit_reason(p,bar,route,0.,p['holding_days'])
                    if reason:
                        scheduled=True
                        if not bar['is_paused'] and not any(o['status']=='PENDING' for o in broker.orders):broker.submit(symbol,broker.positions[symbol].quantity,t,False,bar['factor'])
                if p and symbol not in broker.positions:break
                if t.endswith('15:00:00') and p:
                    p['holding_days']+=1;c=day['close_features']
                    if rules.exit_reason(p,bar,route,0.,p['holding_days'],True):scheduled=True
                    p=rules.close_protection(p,bar['close'],c['ma10_raw'],c['atr20_raw'])
            if p and symbol not in broker.positions:break
        assert len(broker.fills)==2 and not broker.positions
        for k in ('fill_time','price','quantity','fees'):assert broker.fills[0][k]==buy[k],(mode,k)
        if mode in ('E1','W'):
            expected=case['fills'][mode][1]
            for k in ('fill_time','price','quantity','fees','net_pnl'):assert broker.fills[1][k]==expected[k],(mode,k)
        output[mode]=dict(fills=broker.fills,net_pnl=broker.realized_pnl,events=rules.events)
    save('case_confirmation.json',dict(scope='Original entry time/price/quantity fixed. Individual trade only; drawdown=0 because original case never reached hard drawdown while held. No cash dividends in the constant-factor window; original E1/W fills exactly reproduced.',results=output))
    print(json.dumps({k:dict(net_pnl=v['net_pnl'],sell=v['fills'][1]['fill_time'],price=v['fills'][1]['price']) for k,v in output.items()},ensure_ascii=False))

if __name__=='__main__':main()
