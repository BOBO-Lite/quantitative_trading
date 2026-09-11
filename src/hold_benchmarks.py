"""Cash-dividend hold controls; per-entry cases are not pooled portfolios."""
import json,math,csv,hashlib
from pathlib import Path
from types import SimpleNamespace
from statistics import median
from s2_strategy_rules import Policy,fee
from research_execution import ReplayBroker
from corporate_actions import CashDividendBook,dividend_tax_rate
from exit_extension_research import read_export

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/hold_benchmarks'
def save(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
def read(p):return json.loads(p.read_text(encoding='utf8'))

def drawdown(values,initial):
    peak=initial;worst=0.
    for value in values:peak=max(peak,value);worst=max(worst,1-value/peak)
    return worst

def hold_path(symbol,buy,capital,calendar,data):
    start=buy['fill_time'][:10];end=calendar[-1];quantity=buy['quantity'];history=data['daily'][symbol]
    dates=[d for d in calendar if d>=start]
    missing=[d for d in dates if d not in history]
    if missing:raise ValueError('missing_daily:'+missing[0]+':'+str(len(missing)))
    if any(e['record_date']>=start and e['record_date']<=end for e in data['unsupported'][symbol]):raise ValueError('unsupported_share_action')
    if any(e['symbol']==symbol for e in data['conflicts']):raise ValueError('conflicting_source')
    if any(e['symbol']==symbol for e in data['errors']):raise ValueError('unresolved_corporate_source')
    events=[e for e in data['events'][symbol] if start<=e['record_date']<=end]
    book=CashDividendBook(events);cash=capital-quantity*buy['price']-buy['fees']
    if cash< -1e-6:raise ValueError('entry_overspends')
    curve=[dict(date=d,equity=capital,cash=capital,receivable=0.) for d in calendar if d<start]
    previous=None
    for date in dates:
        bar=history[date]
        if any(not isinstance(bar.get(k),(int,float)) or not math.isfinite(bar[k]) or bar[k]<=0 for k in ('open','high','low','close','factor')):raise ValueError('bad_daily:'+date)
        if not bar['low']<=min(bar['open'],bar['close'])<=max(bar['open'],bar['close'])<=bar['high']:raise ValueError('bad_OHLC')
        cash+=book.open_day(date)
        div=book.adjustment(symbol,date)
        if previous and (bar['factor']!=previous['factor'] or div):
            if div is None or abs(previous['close']*previous['factor']/bar['factor']-(previous['close']-div))>.011:
                raise ValueError('unexplained_factor_change:'+date)
        book.close_day(date,{symbol:SimpleNamespace(quantity=quantity,entry_day=start)})
        curve.append(dict(date=date,cash=cash,receivable=book.receivable,equity=cash+quantity*bar['close']+book.receivable))
        previous=bar
    independent=capital-quantity*buy['price']-buy['fees']+quantity*history[end]['close']+sum(quantity*e['cash_per_share'] for e in events if e['ex_date']<=end)
    assert abs(independent-curve[-1]['equity'])<1e-6
    return dict(symbol=symbol,buy=buy,initial_capital=capital,final_equity=curve[-1]['equity'],
        profit=curve[-1]['equity']-capital,return_pct=(curve[-1]['equity']/capital-1)*100,
        close_drawdown_pct=drawdown([x['equity'] for x in curve],capital)*100,
        dividend_gross=book.gross_income,dividend_receivable=book.receivable,curve=curve,ledger=book.ledger,
        terminal_raw_close=history[end]['close'],independent_equity_error=independent-curve[-1]['equity'])

def execute_entry(cache,symbol,date,stamp,limit,cost,quantity=None):
    broker=ReplayBroker(cash=30000.,policy=Policy(cost_multiplier=cost))
    bars={b['datetime']:b for b in cache.minutes[symbol,date]}
    bar=bars[stamp];broker.on_minute(stamp,{symbol:bar})
    if quantity is None:
        quantity=int(30000/limit/100)*100
        while quantity and quantity*limit+fee(quantity*limit,multiplier=cost)>30000:quantity-=100
    broker.submit(symbol,quantity,stamp,True,bar['factor'],limit=limit)
    from datetime import datetime,timedelta
    nextstamp=(datetime.fromisoformat(stamp)+timedelta(minutes=1)).isoformat()
    broker.on_minute(nextstamp,{symbol:bars[nextstamp]})
    assert len(broker.fills)==1,'benchmark not filled'
    return broker.fills[0],broker.orders[0]

def trade_batches(result):
    opened={};out=[]
    for f in result['fills']:
        s=f['symbol']
        if f['buy']:
            assert s not in opened;opened[s]=dict(buy=f,sells=[])
        else:
            trade=opened[s];trade['sells'].append(f)
            if sum(x['quantity'] for x in trade['sells'])==trade['buy']['quantity']:out.append(opened.pop(s))
    assert not opened,'open actual batch needs separate comparison'
    return out

def original_pnl(trade,events):
    buy=trade['buy'];start=buy['fill_time'][:10]
    pnl=sum(f['net_pnl'] for f in trade['sells']);dividend=0.
    for e in events:
        if e['record_date']<start:continue
        for sell in trade['sells']:
            if e['record_date']<sell['fill_time'][:10]:
                dividend+=sell['quantity']*e['cash_per_share']*(1-dividend_tax_rate(start,sell['fill_time'][:10]))
    return pnl+dividend

def main():
    lock=read(OUT/'protocol_lock.json');assert lock['sha256']==hashlib.sha256((OUT/'PROTOCOL.md').read_bytes()).hexdigest()
    data=read(OUT/'historical_inputs.json');cache=read_export(OUT/'minute_export_01.txt')
    calendar=sorted({d['date'] for y in (2018,2019,2020) for d in read(ROOT/f'reports/simple_research/{y}/screen.json')['days'] if '2018-01-01'<=d['date']<='2020-12-31'})
    assert len(calendar)==730
    benchmarks=[];cases=[];summaries=[]
    for cost in (1.,1.5):
        fh=read(ROOT/f'reports/e1_reentry_pair/FH_cost{cost}.json')
        first=next(f for f in fh['fills'] if f['buy']);assert first['symbol']=='601009.SH'
        order=next(o for o in fh['orders'] if o['order_id']==first['order_id'])
        for label,symbol,date,stamp,limit,qty in [
            ('START_SINGLE_FULL','000425.SZ','2018-01-02','2018-01-02T09:31:00',math.floor(4.63*1.04*100+1e-8)/100,None),
            ('FIRST_SIGNAL_FULL','601009.SH','2018-01-26',first['intent_time'],order['limit'],None),
            ('FIRST_SIGNAL_SAME_QTY','601009.SH','2018-01-26',first['intent_time'],order['limit'],first['quantity'])]:
            buy,submitted=execute_entry(cache,symbol,date,stamp,limit,cost,qty)
            if label=='FIRST_SIGNAL_SAME_QTY':assert all(buy[k]==first[k] for k in ('price','quantity','fees','fill_time'))
            result=hold_path(symbol,buy,30000.,calendar,data)
            save(f'{label}_cost{cost}.json',dict(result,order=submitted))
            row={k:v for k,v in result.items() if k not in ('curve','ledger','buy')};row.update(label=label,cost=cost,quantity=buy['quantity'],buy_price=buy['price'])
            benchmarks.append(row)
        benchmarks.append(dict(label='FH',cost=cost,return_pct=fh['metrics']['marked_return']*100,profit=fh['final']['equity']-30000,
            close_drawdown_pct=drawdown([d['equity'] for d in fh['daily']],30000)*100,final_equity=fh['final']['equity']))
        current=[]
        for index,trade in enumerate(trade_batches(fh),1):
            buy=trade['buy'];symbol=buy['symbol'];capital=buy['quantity']*buy['price']+buy['fees']
            row=dict(cost=cost,index=index,symbol=symbol,entry=buy['fill_time'],quantity=buy['quantity'],
                exits=[dict(date=s['fill_time'],reason=s['reason'],quantity=s['quantity']) for s in trade['sells']])
            try:
                held=hold_path(symbol,buy,capital,calendar,data);pnl=original_pnl(trade,data['events'][symbol])
                row.update(status='COMPLETE',original_net=pnl,hold_net=held['profit'],hold_minus_original=held['profit']-pnl,
                    hold_return_pct=held['return_pct'],original_return_pct=pnl/capital*100,hold_close_drawdown_pct=held['close_drawdown_pct'])
            except ValueError as e:row.update(status='BLOCKED',reason=str(e))
            current.append(row)
        cases+=current;done=[r for r in current if r['status']=='COMPLETE']
        summaries.append(dict(cost=cost,total=len(current),complete=len(done),blocked=len(current)-len(done),
            hold_better=sum(r['hold_minus_original']>1e-6 for r in done),original_better=sum(r['hold_minus_original']< -1e-6 for r in done),
            median_hold_minus_original_yuan=median(r['hold_minus_original'] for r in done),
            median_hold_return_pct=median(r['hold_return_pct'] for r in done),median_original_return_pct=median(r['original_return_pct'] for r in done)))
    personal=[]
    with (ROOT/'runtime/s1_daily.csv').open(encoding='utf-8-sig',newline='') as stream:
        for row in csv.DictReader(stream):
            if row['symbol']=='601975.SH' and row['date']<='2026-09-09':personal.append(row)
    latest=max(personal,key=lambda r:r['date']);assert latest['date']=='2026-09-09';price=float(latest['close'])
    p=dict(cost=3.822,confirmed_exit=4.03,cutoff=latest['date'],hold_mark=price,quantity_from_archive=2000,
        exit_price_return_pct=(4.03/3.822-1)*100,hold_price_return_pct=(price/3.822-1)*100,
        exit_price_profit_2000=(4.03-3.822)*2000,hold_price_profit_2000=(price-3.822)*2000,
        difference_2000=(price-4.03)*2000,excludes_actual_fees_and_dividends=True)
    save('benchmarks.json',benchmarks);save('cases.json',cases);save('case_summary.json',summaries);save('nanyou.json',p)
    print(json.dumps(dict(benchmarks=benchmarks,case_summary=summaries,nanyou=p),ensure_ascii=False))

if __name__=='__main__':main()
