"""EXT-MOM1 isolated monthly account; real minute execution, FIFO dividend tax."""
import json,math
from collections import Counter
from decimal import Decimal,ROUND_CEILING,ROUND_FLOOR
from external_momentum import OUT,buy_eligible,weights
from s2_strategy_rules import fee
from corporate_actions import dividend_tax_rate

class MissingData(ValueError):pass

def tick(x,buy):
    return float(Decimal(str(x)).quantize(Decimal('.01'),rounding=ROUND_CEILING if buy else ROUND_FLOOR))

class Ledger:
    def __init__(self,events):
        self.cash=30000.;self.lots={};self.events=events;self.rights={};self.receivable=0.;self.tax=0.;self.dividends=0.;self.serial=0
    def qty(self,s):return sum(l['qty'] for l in self.lots.get(s,[]))
    def symbols(self):return {s for s in self.lots if self.qty(s)>0}
    def available(self,s,day):return sum(l['qty']-(l.get('locked_qty',0) if day<l.get('unlock','') else 0) for l in self.lots.get(s,[]) if l['entry']<day)
    def record(self,day):
        for i,e in enumerate(self.events):
            if e['record_date']==day:self.rights[i]=[dict(lot=l['id'],entry=l['entry'],qty=l['qty'],untaxed=l['qty'],tax_per_unit=e.get('taxable_cash_per_share',e['cash_per_share'])) for l in self.lots.get(e['symbol'],[]) if l['qty']]
    def open(self,day):
        for i,e in enumerate(self.events):
            if e['ex_date']==day:
                if i not in self.rights:raise MissingData('missing dividend record '+str(e))
                value=sum(r['qty'] for r in self.rights[i])*e['cash_per_share'];self.receivable+=value;self.dividends+=value
                ratio=e.get('shares_per_share',0.)
                if ratio:
                    for r in self.rights[i]:
                        lots=[l for l in self.lots[e['symbol']] if l['id']==r['lot']];l=lots[0]
                        if l['qty']!=r['qty']:raise MissingData('stock record/ex-date quantity changed')
                        extra=r['qty']*ratio
                        if abs(extra-round(extra))>1e-7:raise MissingData('fractional corporate allocation requires real allocation '+e['symbol']+' '+day)
                        l['qty']+=int(round(extra));l['locked_qty']=int(round(extra));l['unlock']=e['shares_trading_date'];l['price']/=1+ratio
                        for j,rights in self.rights.items():
                            for old in rights:
                                if old['lot']==l['id']:old['untaxed']*=1+ratio;old['tax_per_unit']/=1+ratio
            if e['pay_date']==day:
                value=sum(r['qty'] for r in self.rights.get(i,[]))*e['cash_per_share'];self.receivable-=value;self.cash+=value
    def buy(self,s,q,px,cost,day):
        charge=fee(q*px,multiplier=cost)
        if q%100 or q<=0 or q*px+charge>self.cash+1e-8:raise ValueError('invalid buy funding/lot')
        self.cash-=q*px+charge;self.serial+=1
        self.lots.setdefault(s,[]).append(dict(id=self.serial,entry=day,qty=q,price=px))
        return charge,0.
    def sell(self,s,q,px,cost,day):
        if q<=0 or q>self.available(s,day):raise ValueError('T+1 or unavailable')
        remaining=q;tax=0.
        for l in self.lots[s]:
            if not remaining:break
            if l['entry']>=day:continue
            available=l['qty']-(l.get('locked_qty',0) if day<l.get('unlock','') else 0)
            sold=min(remaining,available);l['qty']-=sold;remaining-=sold
            for i,e in enumerate(self.events):
                if e['symbol']!=s or e['ex_date']>day:continue
                for r in self.rights.get(i,[]):
                    if r['lot']==l['id']:
                        n=min(sold,r['untaxed']);r['untaxed']-=n;tax+=n*r['tax_per_unit']*dividend_tax_rate(l['entry'],day)
        charge=fee(q*px,sell=True,multiplier=cost);self.cash+=q*px-charge-tax;self.tax+=tax
        return charge,tax

def execute(bar,daily,buy,requested,cost):
    if daily['is_paused'] or bar['volume']<=0:return 0,None,'paused_or_empty'
    high=tick(daily['high_limit'],False);low=tick(daily['low_limit'],True)
    if buy and (daily['is_st'] or bar['open']>=high) or not buy and bar['open']<=low:return 0,None,'state_or_limit'
    px=tick(bar['open']*(1+(.001*cost if buy else -.001*cost)),buy)
    if px<low or px>high or px<bar['low']-1e-8 or px>bar['high']+1e-8:return 0,None,'outside_real_bar'
    q=min(requested,int(bar['volume']*.01/100)*100)
    return q,px,'filled' if q==requested else 'participation'

def replay(screen,daily,minutes,events,unsupported,cost):
    calendar=[d for d in screen['calendar'] if '2018-01-01'<=d<='2020-12-31'];allcal=screen['calendar']
    book=Ledger(events);targets={};curve=[];fills=[];orders=[];decisions=[];peak=30000.;maxdd=0.
    for e in events:
        if e['record_date']<calendar[0]<=e['ex_date']:
            book.rights[events.index(e)]=[]
    def row(s,d):
        if s not in daily or d not in daily[s]:raise MissingData('daily '+s+' '+d)
        return daily[s][d]
    for day in calendar:
        previous=allcal[allcal.index(day)-1]
        book.open(day)
        for e in events:
            if e['ex_date']==day and e.get('shares_per_share',0) and e['symbol'] in targets:
                targets[e['symbol']]=int(round(targets[e['symbol']]*(1+e['shares_per_share'])))
        # Known ex-dividend cash adjustment; never infer stock quantity from price factors.
        def mark(s):
            same=[e for e in events if e['symbol']==s and e['ex_date']==day]
            return (row(s,previous)['close']-sum(e['cash_per_share'] for e in same))/(1+sum(e.get('shares_per_share',0) for e in same))
        equity=book.cash+book.receivable+sum(book.qty(s)*mark(s) for s in book.symbols())
        if day in screen['rankings']:
            snap=screen['rankings'][day];rows=snap['rows'];by={r['symbol']:r for r in rows};rank={r['symbol']:i+1 for i,r in enumerate(rows)}
            keep=[s for s in sorted(book.symbols()) if rank.get(s,101)<=100 and by[s]['close']>by[s]['ma100']]
            chosen=list(keep)
            if snap['market_on']:
                for r in rows:
                    if len(chosen)>=5:break
                    if r['symbol'] not in chosen and buy_eligible(r):chosen.append(r['symbol'])
            target_weights=weights([by[s] for s in chosen]);targets={s:0 for s in book.symbols()-set(chosen)}
            for s in chosen:
                px=mark(s);current=book.qty(s);target=int(equity*target_weights[s]/px/100)*100
                if current and abs(current*px/equity-target_weights[s])<.05:target=current
                if not snap['market_on']:target=min(target,current)
                if 0<target<current:target=current-int((current-target)/100)*100
                if not current and target*px<4000:target=0
                targets[s]=target
            decisions.append(dict(date=day,signal=snap['signal'],market_on=snap['market_on'],chosen=chosen,target_weights=target_weights,targets=dict(targets),equity_before_trade=equity))
        for buy in (False,True):
            for s in list(targets):
                current=book.qty(s);delta=targets[s]-current
                if (delta>0)!=buy or delta==0:continue
                d=row(s,day)
                if d['is_paused']:
                    orders.append(dict(date=day,symbol=s,buy=buy,requested=abs(delta),reason='paused'));continue
                key=s+'|'+day
                if key not in minutes:raise MissingData('minute '+s+' '+day)
                bar=minutes[key];requested=abs(delta)
                if not buy:requested=min(requested,book.available(s,day))
                q,px,reason=execute(bar,d,buy,requested,cost)
                if buy and q:
                    while q and q*px+fee(q*px,multiplier=cost)>book.cash+1e-8:q-=100
                    if not current and q*px<4000:q=0;reason='small_initial_fill'
                orders.append(dict(date=day,symbol=s,buy=buy,requested=requested,quantity=q,price=px,reason=reason))
                if q:
                    charge,tax=(book.buy(s,q,px,cost,day) if buy else book.sell(s,q,px,cost,day))
                    fills.append(dict(datetime=day+'T09:35:00',symbol=s,buy=buy,quantity=q,price=px,fee=charge,dividend_tax=tax,cash=book.cash))
        exposure=sum(book.qty(s)*row(s,day)['close'] for s in book.symbols());equity=book.cash+book.receivable+exposure
        if book.cash<-.00001 or not math.isfinite(equity):raise ValueError('account conservation')
        for e in unsupported:
            if e['record_date']==day and book.qty(e['symbol']):raise MissingData('unsupported corporate entitlement '+str(e))
        book.record(day);peak=max(peak,equity);dd=1-equity/peak;maxdd=max(maxdd,dd)
        curve.append(dict(date=day,cash=book.cash,equity=equity,exposure=exposure,receivable=book.receivable,drawdown=dd,positions={s:book.qty(s) for s in sorted(book.symbols())}))
    from datetime import date
    years=(date.fromisoformat(calendar[-1])-date.fromisoformat(calendar[0])).days/365.25
    return dict(status='COMPLETED',variant='EXT-MOM1-M0',cost=cost,metrics=dict(total_return=equity/30000-1,cagr=(equity/30000)**(1/years)-1,max_daily_close_drawdown=maxdd),final=curve[-1],fills=fills,orders=orders,decisions=decisions,daily=curve,dividends=book.dividends,dividend_tax=book.tax,scope='source-inspired A-share adaptation; daily close drawdown, no account halt overlay')
