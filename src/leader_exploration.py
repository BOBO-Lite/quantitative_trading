"""Exploratory daily trend leaders. Factor-return exposure proxy, never a broker ledger."""
import json,hashlib,math
from collections import Counter
from pathlib import Path
import numpy as np
import pandas as pd
from import_supermind_minute_probe import decode_packets

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/leader_exploration'
SOURCE=ROOT/'reports/external_momentum'

def save(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')

def features(frame):
    f=frame.sort_index().copy()
    for k in ('open','high','low','close'):f['a_'+k]=f[k]*f['factor']
    c=f.a_close
    for n in (10,20,60):f['ma'+str(n)]=c.rolling(n).mean()
    f['strength']=c/c.shift(60)-1
    f['prior_high20']=f.a_high.rolling(20).max().shift(1)
    f['low10']=f.a_low.rolling(10).min().shift(1)
    f['vol20']=f.volume.rolling(20).mean().shift(1)
    f['prev_close']=c.shift(1)
    f['prev_ma10']=f.ma10.shift(1)
    return f

def inputs():
    history={};membership={};hashes={};duplicates=0;conflicts=0
    for p in sorted(SOURCE.glob('screen_export_*.txt')):
        hashes[p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
        packets=decode_packets(p.read_text(encoding='utf8'))
        for key,snapshot in sorted(packets.items()):
            if not key.startswith('extmom_'):continue
            membership[snapshot['trade']]=snapshot['members']
            for item in snapshot['rows']:
                w=item['window'];stock=history.setdefault(item['symbol'],{})
                for i,day in enumerate(w['dates']):
                    row={k:values[i] for k,values in w['data'].items()}
                    if day in stock:
                        duplicates+=1
                        if any(not math.isclose(row[k],stock[day][k],rel_tol=1e-8,abs_tol=1e-7) for k in row):conflicts+=1
                        continue # Earliest retained export, never choose by subsequent return.
                    stock[day]=row
    screen=json.loads((SOURCE/'screen.json').read_text(encoding='utf8'))
    end=max(d for stock in history.values() for d in stock)
    days=[d for d in screen['calendar'] if '2018-01-02'<=d<=end]
    frames={s:features(pd.DataFrame.from_dict(rows,orient='index').reindex(screen['calendar'])) for s,rows in history.items()}
    byday={d:{} for d in screen['calendar'] if d<=end}
    for s,f in frames.items():
        for d,row in f.iterrows():
            if d in byday and pd.notna(row['a_close']):byday[d][s]=row.to_dict()
    universe={};active=[];missing=Counter();eligible=Counter();sizes=[]
    for d in days:
        if d in membership:active=membership[d]
        universe[d]=active
        sizes.append(len(active))
        for s in active:
            if s not in byday[d]:missing['missing_member_days']+=1
            elif not math.isfinite(byday[d][s]['strength']):missing['missing_60day_window']+=1
            else:eligible['member_days_with_60day_window']+=1
    audit=dict(start=days[0],end=days[-1],days=len(days),symbols=len(frames),source_sha256=hashes,
               overlapping_rows=duplicates,overlap_conflicts_kept_earliest=conflicts,
               missing=dict(missing),coverage=dict(eligible),universe_member_days=sum(sizes),
               scope='historical CSI500 mainboard monthly membership, incomplete reconstructed daily windows',
               limitations=['data originally exported only for valid month-end windows; missingness can bias the sample',
                            'future month-end membership does not determine daily selection; previous known monthly membership used',
                            'factor-return exposure proxy; no exact cash-dividend or share-distribution ledger',
                            'daily open and approximate price-limit checks; no minute queue, fill or capacity validation'])
    save('input_audit.json',audit)
    return days,universe,byday,screen['benchmark'],audit

def candidates(rows,members,entry):
    valid=[(s,rows[s]) for s in members if s in rows and math.isfinite(rows[s]['strength']) and not rows[s]['is_st'] and not rows[s]['is_paused']]
    valid.sort(key=lambda x:(-x[1]['strength'],x[0]))
    leaders=valid[:max(1,math.ceil(len(valid)*.1))]
    selected=[]
    for s,r in leaders:
        if not (r['a_close']>r['ma10']>r['ma20']>r['ma60'] and r['strength']>.15):continue
        if entry=='breakout':ok=r['a_close']>r['prior_high20'] and r['volume']>=1.2*r['vol20']
        else:ok=r['prev_close']<=1.02*r['prev_ma10'] and r['a_close']>r['prev_close'] and r['volume']>=r['vol20']
        if ok:selected.append(s)
    return selected

def exit_signal(row,position,method):
    if method=='trail8':return row['a_close']<=position['peak']*.92
    if method=='ma10':return row['a_close']<row['ma10']
    return row['a_close']<=row['low10']

def fee(value,sell,cost):
    # Explicit historical-rate assumption for exploration; not broker-verified fees.
    return (max(5.,value*.0003)+value*.00002+(value*.001 if sell else 0))*cost

def run(days,universe,byday,benchmark,entry,method,cost,market_filter=False):
    cash=30000.;positions={};pending_buys=[];pending_sells=set();curve=[];trades=[];gaps=Counter();fills=[]
    market=pd.Series(benchmark).sort_index();ma=market.rolling(60).mean().to_dict()
    prevday=None
    for day in days:
        rows=byday[day]
        for s in sorted(list(pending_sells)):
            if s not in positions:pending_sells.remove(s);continue
            r=rows.get(s);p=positions[s]
            if r is None or not math.isfinite(r['a_open']):gaps['sell_missing_day']+=1;continue
            if r['is_paused'] or r['volume']<=0:gaps['sell_paused']+=1;continue
            if math.isfinite(r['prev_close']) and r['a_open']/r['prev_close']-1<=-.095:gaps['sell_limit_proxy']+=1;continue
            value=p['units']*r['a_open']*(1-.001*cost);charge=fee(value,True,cost);cash+=value-charge
            trades.append(dict(symbol=s,entry=p['entry'],exit=day,pnl=value-charge-p['initial'],return_pct=(value-charge)/p['initial']*100-100))
            fills.append(dict(date=day,symbol=s,side='sell',value=value,fee=charge,signal=p['sell_signal']))
            del positions[s];pending_sells.remove(s)
        opening_equity=cash+sum(p['units']*(rows[s]['a_open'] if s in rows else p['mark']) for s,p in positions.items())
        for s in pending_buys:
            if len(positions)>=3:break
            if s in positions:continue
            r=rows.get(s)
            if r is None:gaps['buy_missing_day']+=1;continue
            if r['is_paused'] or r['is_st'] or r['volume']<=0:gaps['buy_state']+=1;continue
            if math.isfinite(r['prev_close']) and r['a_open']/r['prev_close']-1>=.095:gaps['buy_limit_proxy']+=1;continue
            px=r['open']*(1+.001*cost);budget=min(cash,opening_equity/3)
            qty=int(budget/px/100)*100
            while qty>0 and qty*px+fee(qty*px,False,cost)>budget:qty-=100
            if not qty:gaps['buy_lot_or_cash']+=1;continue
            value=qty*px;charge=fee(value,False,cost);cash-=value+charge
            positions[s]=dict(units=qty/r['factor'],initial=value+charge,entry=day,peak=r['a_open'],mark=r['a_open'])
            fills.append(dict(date=day,symbol=s,side='buy',value=value,fee=charge,signal=prevday,initial_raw_shares=qty))
        for s,p in positions.items():
            r=rows.get(s)
            if r is None:gaps['held_missing_mark_carried']+=1;continue
            p['mark']=r['a_close'];p['peak']=max(p['peak'],r['a_close'])
            if exit_signal(r,p,method):pending_sells.add(s);p.setdefault('sell_signal',day)
        equity=cash+sum(p['units']*p['mark'] for p in positions.values())
        if cash<-.00001:raise ValueError('negative cash')
        curve.append(dict(date=day,equity=equity,cash=cash,positions=len(positions)))
        pending_buys=candidates(rows,universe[day],entry)
        if market_filter and not benchmark[day]>ma.get(day,float('inf')):pending_buys=[]
        prevday=day
    vals=np.array([30000.]+[r['equity'] for r in curve]);dd=1-vals/np.maximum.accumulate(vals)
    years={};base=30000.
    for year in sorted({d[:4] for d in days}):
        group=[r for r in curve if r['date'].startswith(year)];last=group[-1]['equity'];years[year]=dict(start=group[0]['date'],end=group[-1]['date'],return_pct=(last/base-1)*100);base=last
    pnl=[t['pnl'] for t in trades];wins=sum(v for v in pnl if v>0);loss=-sum(v for v in pnl if v<0)
    return dict(status='EXPLORATORY_INCOMPLETE_DATA',entry=entry,exit=method,cost=cost,market_filter=market_filter,
       metrics=dict(total_return_pct=(vals[-1]/30000-1)*100,cagr_pct=((vals[-1]/30000)**(252/len(days))-1)*100,
                    max_drawdown_pct=float(dd.max()*100),final_equity=float(vals[-1]),closed_trades=len(trades),
                    win_rate_pct=100*sum(v>0 for v in pnl)/len(pnl) if pnl else None,profit_factor=wins/loss if loss else None,
                    mean_exposure_pct=float(np.mean([1-r['cash']/r['equity'] for r in curve])*100),fees=sum(f['fee'] for f in fills)),
       yearly=years,data_gap_effects=dict(gaps),curve=curve,trades=trades,fills=fills,
       final_positions={s:dict(entry=p['entry'],proxy_value=p['units']*p['mark']) for s,p in positions.items()})

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    days,universe,rows,bm,audit=inputs();summary=[]
    for market_filter in (False,True):
        for entry in ('breakout','pullback'):
            for method in ('trail8','ma10','low10'):
                for cost in (1.,1.5):
                    r=run(days,universe,rows,bm,entry,method,cost,market_filter)
                    name=f'{entry}_{method}_cost{cost}'+('_market60' if market_filter else '')+'.json';save(name,r)
                    assert all(f['signal']<f['date'] for f in r['fills'])
                    ledger=30000+sum(f['value']-f['fee'] if f['side']=='sell' else -f['value']-f['fee'] for f in r['fills'])
                    assert abs(ledger-r['curve'][-1]['cash'])<1e-6
                    assert abs(ledger+sum(v['proxy_value'] for v in r['final_positions'].values())-r['metrics']['final_equity'])<1e-6
                    summary.append(dict(file=name,**{k:v for k,v in r.items() if k not in ('curve','trades','fills','final_positions')}))
    last=days[-1]
    e1=json.loads((ROOT/'reports/exit_research/E1_cost1.0.json').read_text(encoding='utf8'))
    save('baseline_available_keys.json',list(e1))
    save('comparison.json',dict(status='EXPLORATORY_INCOMPLETE_DATA',input_audit=audit,runs=summary,
                               selection_warning='All six rules are exploratory comparisons on the same historical sample; best is not out-of-sample proof.'))
    for r in summary:print(r['entry'],r['exit'],r['cost'],r['market_filter'],json.dumps(r['metrics'],ensure_ascii=False))

if __name__=='__main__':main()
