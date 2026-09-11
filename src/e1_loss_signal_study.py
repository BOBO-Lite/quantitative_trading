"""Pre-entry contrasts, fixed-entry executable early exits, and exposure diagnosis."""
import json,hashlib
from collections import defaultdict,Counter
from statistics import mean,median
from e1_condition_study import ROOT
from recovery_research import prepare
from exit_extension_research import read_export
from simple_history_replay import merge_cache
from research_execution import ReplayBroker
import simple_strategy_rules as base

OUT=ROOT/'reports/e1_loss_signals'
def save(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')

def features(history,asof):
    rows=[v for d,v in sorted(history.items()) if d<=asof][-21:]
    if len(rows)!=21 or rows[-1]['datetime'][:10]!=asof:return None
    if any(r.get(k) is None or r[k]<=0 for r in rows for k in ('close','high','low','factor')):return None
    f=rows[-1]['factor'];c=[r['close']*r['factor']/f for r in rows]
    h=[r['high']*r['factor']/f for r in rows];l=[r['low']*r['factor']/f for r in rows]
    vol=[r['volume']*f/r['factor'] for r in rows]
    tr=[max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(1,21)]
    if mean(vol[-10:-5])<=0 or mean(tr)<=0:return None
    a=(c[-1]/c[-6]-1)*100;b=(c[-6]/c[-11]-1)*100
    location=(c[-1]-l[-1])/(h[-1]-l[-1]) if h[-1]>l[-1] else .5
    return dict(ret5_pct=a,prior5_pct=b,acceleration_pp=a-b,volume5_vs_previous5=mean(vol[-5:])/mean(vol[-10:-5]),atr5_vs20=mean(tr[-5:])/mean(tr),close_location=location)

def flags(f):return dict(decelerating=f['acceleration_pp']<=0,volume_fading=f['volume5_vs_previous5']<1,volatility_expanding=f['atr5_vs20']>1.25,weak_close=f['close_location']<.5)

def preentry(cache):
    data=json.loads((ROOT/'reports/e1_conditions/signals.json').read_text(encoding='utf8'))['signals'];rows=[];missing=Counter()
    for r in data:
        end=r['exit_days']['10'];value=r['outcomes']['10']
        if value is None or end is None:missing['future_label_missing']+=1;continue
        period='2018_2019' if end<='2019-12-31' else '2020' if r['asof']>='2020-01-01' else None
        if not period:missing['cross_period_label']+=1;continue
        f=features(cache.daily.get(r['symbol'],{}),r['asof'])
        if f is None:missing['feature_window_missing']+=1;continue
        rows.append(dict(symbol=r['symbol'],asof=r['asof'],period=period,forward10_pct=value,down5=value<-5,features=f,flags=flags(f)))
    output=[]
    for flag in ('decelerating','volume_fading','volatility_expanding','weak_close'):
        periods={}
        for period in ('2018_2019','2020'):
            dayrows=defaultdict(list)
            for r in rows:
                if r['period']==period:dayrows[r['asof']].append(r)
            comparisons=[]
            for d,rr in dayrows.items():
                yes=[r for r in rr if r['flags'][flag]];no=[r for r in rr if not r['flags'][flag]]
                if not yes or not no:continue
                comparisons.append(dict(date=d,flagged=len(yes),unflagged=len(no),return_difference_pp=mean(r['forward10_pct'] for r in yes)-mean(r['forward10_pct'] for r in no),down5_difference_pp=100*(mean(r['down5'] for r in yes)-mean(r['down5'] for r in no))))
            periods[period]=dict(comparable_dates=len(comparisons),flagged_cases=sum(x['flagged'] for x in comparisons),unflagged_cases=sum(x['unflagged'] for x in comparisons),mean_return_difference_pp=mean(x['return_difference_pp'] for x in comparisons) if comparisons else None,mean_down5_difference_pp=mean(x['down5_difference_pp'] for x in comparisons) if comparisons else None,dates=comparisons)
        output.append(dict(flag=flag,periods=periods))
    save('preentry.json',dict(label='next-session open to tenth close factor return, not realized trade PnL',missing=dict(missing),rows=rows,contrasts=output))
    print('PREENTRY',json.dumps([{**r,'periods':{p:{k:v for k,v in d.items() if k!='dates'} for p,d in r['periods'].items()}} for r in output]),flush=True)
    return {(r['symbol'],r['asof']):r['features'] for r in rows}

def paired(result):
    opened={};pairs=[]
    for f in result['fills']:
        if f['buy']:assert f['symbol'] not in opened;opened[f['symbol']]=f
        else:
            b=opened.pop(f['symbol']);assert b['quantity']==f['quantity'];pairs.append((b,f))
    assert not opened
    return pairs

def replay_pair(cache,bundle,result,b,s,mode):
    symbol=b['symbol'];start=b['fill_time'][:10];end=s['fill_time'][:10]
    days=[d for d in bundle['calendar'] if start<=d<=end]
    events=[e for e in bundle['corporate_events'] if e['symbol']==symbol and start<=e['record_date'] and e['ex_date']<=end]
    broker=ReplayBroker(30000.,corporate_events=events)
    order=next(o for o in result['orders'] if o['order_id']==b['order_id']);scheduled=None;seen=0;trigger=None
    for i,day in enumerate(days):
        for bar in cache.minutes[symbol,day]:
            t=bar['datetime']
            if t<b['intent_time']:continue
            broker.on_minute(t,{symbol:bar})
            if t==b['intent_time']:broker.submit(symbol,b['quantity'],t,True,bar['factor'],order['limit'])
            if symbol in broker.positions and day>start:
                original_due=t>=s['intent_time']
                early_due=scheduled is not None and day>scheduled
                pending=any(o['status']=='PENDING' for o in broker.orders)
                if (original_due or early_due) and not pending and not bar['is_paused']:
                    broker.submit(symbol,broker.positions[symbol].quantity,t,False,bar['factor'])
            if t.endswith('15:00:00'):
                if mode!='original' and symbol in broker.positions and i+1=={'F1':1,'F3':3}[mode]:
                    reference=b['price']-.8*sum(a['cash_per_share'] for a in broker.dividend_adjustments)
                    if bar['close']<reference:scheduled=day;trigger=dict(day=day,close_return_pct=(bar['close']/reference-1)*100)
                broker.close_day(day)
    assert not broker.positions,'unfinished pair'
    buys=[f for f in broker.fills if f['buy']];assert len(buys)==1
    for k in ('fill_time','price','quantity','fees'):assert buys[0][k]==b[k],(mode,'entry',k)
    if mode=='original':
        sells=[f for f in broker.fills if not f['buy']];assert len(sells)==1
        for k in ('fill_time','price','quantity','fees','net_pnl'):assert abs(sells[0][k]-s[k])<1e-6 if isinstance(s[k],(float,int)) else sells[0][k]==s[k],k
    snap=broker.snapshot();pnl=snap['equity']-30000
    assert abs(pnl-(snap['realized_pnl']+snap['dividend_income']-snap['dividend_tax']))<1e-6
    return dict(pnl=pnl,trigger=trigger,sells=[{k:f[k] for k in ('fill_time','price','quantity','fees')} for f in broker.fills if not f['buy']])

def account_study(cache,bundle,feature_map):
    summaries={};alltrades={};position_reports={}
    for name,path in [('E1',ROOT/'reports/exit_research/extension_2020/E1_cost1.0.json'),('filtered',ROOT/'reports/e1_conditions/ma20_far10_cost1.0.json')]:
        r=json.loads(path.read_text(encoding='utf8'));trades=[]
        for b,s in paired(r):
            asof=bundle['calendar'][bundle['calendar'].index(b['fill_time'][:10])-1]
            f=feature_map.get((b['symbol'],asof)) or features(cache.daily[b['symbol']],asof)
            results={mode:replay_pair(cache,bundle,r,b,s,mode) for mode in ('original','F1','F3')}
            trades.append(dict(symbol=b['symbol'],buy=b['fill_time'],original_sell=s['fill_time'],year=b['fill_time'][:4],entry_features=f,original_net_trade_pnl=s['net_pnl'],results=results))
        assert abs(sum(t['results']['original']['pnl'] for t in trades)-(r['final']['equity']-30000))<1e-5
        summaries[name]={}
        for mode in ('F1','F3'):
            triggered=[t for t in trades if t['results'][mode]['trigger']]
            changed=[t for t in trades if abs(t['results'][mode]['pnl']-t['results']['original']['pnl'])>1e-7]
            delta=lambda t:t['results'][mode]['pnl']-t['results']['original']['pnl']
            summaries[name][mode]=dict(trigger_count=len(triggered),triggered_original_losers=sum(t['original_net_trade_pnl']<0 for t in triggered),changed_trades=len(changed),total_pnl_difference=sum(map(delta,trades)),helped=sum(delta(t)>1e-7 for t in trades),hurt=sum(delta(t)<-1e-7 for t in trades),original_losers_difference=sum(delta(t) for t in trades if t['original_net_trade_pnl']<0),original_winners_difference=sum(delta(t) for t in trades if t['original_net_trade_pnl']>=0),yearly_difference={y:sum(delta(t) for t in trades if t['year']==y) for y in ('2018','2019','2020')})
        medians={}
        for label in ('winner','loser'):
            selected=[t for t in trades if (t['original_net_trade_pnl']>=0)==(label=='winner') and t['entry_features']]
            medians[label]=dict(count=len(selected),features={k:median(t['entry_features'][k] for t in selected) for k in selected[0]['entry_features']})
        summaries[name]['entry_medians']=medians
        byday={d['date']:d for d in bundle['days']};position_rows=[]
        for d in r['daily']:
            pre=byday[d['date']]['previous_close'];route=d['route'];qualified=[x for x in pre['stocks'] if base.select_signal(x,route) and base.needs_minutes(x,route) and (name=='E1' or x['close']/x['ma20']-1>.10+1e-12)]
            flat=abs(d['equity']-d['cash']-d['dividend_receivable'])<1e-6
            position_rows.append(dict(date=d['date'],flat=flat,route=route,close_drawdown=d['drawdown'],halted=d['halted'],qualified=len(qualified)))
        cross=Counter(('flat' if d['flat'] else 'invested',d['route'],'dd_ge12' if d['close_drawdown']>=.12 else 'dd_lt12','candidates' if d['qualified'] else 'none') for d in position_rows)
        position_reports[name]=dict(cross_counts=[dict(state=k[0],route=k[1],risk=k[2],candidates=k[3],days=v) for k,v in sorted(cross.items())],hard_halted_days=sum(d['halted'] for d in position_rows),risk_or_minimum_rejections=len(r['decisions']),daily=position_rows)
        alltrades[name]=trades
        print(name,json.dumps(summaries[name],ensure_ascii=False),flush=True)
    save('fixed_entry_exits.json',dict(scope='Fixed original entries and quantities, normal cost. Independent pair PnL differences, not portfolio return; no reinvestment. Original execution and aggregate final equity reproduced.',summaries=summaries,trades=alltrades))
    save('position_diagnosis.json',position_reports)

def main():
    OUT.mkdir(exist_ok=True);cache,bundle=prepare();print('BASE_READY',flush=True)
    for folder in ('e1_rank_research','e1_conditions'):
        for p in sorted((ROOT/'reports'/folder).glob('minute_export_*.txt')):cache=merge_cache([cache,read_export(p)])
    fm=preentry(cache);account_study(cache,bundle,fm)

if __name__=='__main__':main()
