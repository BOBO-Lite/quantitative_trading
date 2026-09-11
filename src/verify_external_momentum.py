"""Second accounting reconstruction in original purchase units, independent of Ledger.

Uses recorded fills (does not independently reproduce order selection/matching).
Recomputes fees, distribution entitlements, FIFO taxes, all daily shares/cash/equity.
"""
import json,math
from datetime import date
from dateutil.relativedelta import relativedelta
from external_momentum import OUT
from run_external_momentum import inputs

def verify(result,data):
    daily,minutes,events,unsupported=data;cost=result['cost'];cash=30000.;accrued=0.;lots=[];rights={};checks=0;largest=0.;tax_total=0.
    def near(a,b,label):
        nonlocal largest
        largest=max(largest,abs(a-b))
        if abs(a-b)>1e-6:raise ValueError(label+' '+str((a,b)))
    for dayrow in result['daily']:
        day=dayrow['date']
        for j,e in enumerate(events):
            if e['ex_date']==day:
                rs=rights.get(j,[]);accrued+=sum(r['cash'] for r in rs)
                if e.get('shares_per_share',0):
                    for r in rs:lots[r['lot']]['factor']*=1+e['shares_per_share']
            if e['pay_date']==day:
                value=sum(r['cash'] for r in rights.get(j,[]));cash+=value;accrued-=value
        for f in (f for f in result['fills'] if f['datetime'][:10]==day):
            notional=f['price']*f['quantity'];charge=(max(5,notional*.0002)+notional*(.00001+(.0005 if not f['buy'] else 0)))*cost
            near(charge,f['fee'],'fee');tax=0.
            if f['buy']:
                cash-=notional+charge
                lots.append(dict(symbol=f['symbol'],entry=day,units=float(f['quantity']),factor=1.))
            else:
                remaining=f['quantity']
                for i,l in enumerate(lots):
                    if l['symbol']!=f['symbol'] or l['units']<=1e-10:continue
                    if l['entry']>=day:raise ValueError('reference T+1')
                    units=min(l['units'],remaining/l['factor']);sold=units*l['factor'];l['units']-=units;remaining-=sold
                    buydate=date.fromisoformat(l['entry']);selldate=date.fromisoformat(day)
                    rate=.2 if selldate<=buydate+relativedelta(months=1) else .1 if selldate<=buydate+relativedelta(years=1) else 0.
                    for j,rs in rights.items():
                        if events[j]['ex_date']>day:continue
                        for r in rs:
                            if r['lot']==i:
                                u=min(units,r['untaxed_units']);r['untaxed_units']-=u;tax+=u*r['tax_per_unit']*rate
                    if remaining<1e-8:break
                near(remaining,0,'sold beyond holdings');cash+=notional-charge-tax;tax_total+=tax
            near(tax,f['dividend_tax'],'tax');near(cash,f['cash'],'fill cash');checks+=1
        positions={}
        for l in lots:
            if l['units']>1e-10:positions[l['symbol']]=positions.get(l['symbol'],0)+l['units']*l['factor']
        if set(positions)!=set(dayrow['positions']):raise ValueError('position symbols')
        for s,q in positions.items():near(q,dayrow['positions'][s],'position quantity')
        equity=cash+accrued+sum(q*daily[s][day]['close'] for s,q in positions.items())
        near(cash,dayrow['cash'],'daily cash');near(accrued,dayrow['receivable'],'receivable');near(equity,dayrow['equity'],'daily equity')
        for j,e in enumerate(events):
            if e['record_date']==day:
                rights[j]=[dict(lot=i,units=l['units'],untaxed_units=l['units'],cash=l['units']*l['factor']*e['cash_per_share'],tax_per_unit=l['factor']*e.get('taxable_cash_per_share',e['cash_per_share'])) for i,l in enumerate(lots) if l['symbol']==e['symbol'] and l['units']>1e-10]
    near(tax_total,result['dividend_tax'],'total taxes')
    return dict(status='PASS_INDEPENDENT_ACCOUNT_RECONSTRUCTION',cost=cost,days=len(result['daily']),fills=checks,maximum_difference=largest,scope='same fills, separate original-unit accounting; not RQAlpha parity or independent signals/matching')

if __name__=='__main__':
    data=inputs();results=[]
    for cost in (1.,1.5):
        result=json.loads((OUT/f'M0_cost{cost}.json').read_text(encoding='utf8'));results.append(verify(result,data))
    (OUT/'account_verification.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(results,ensure_ascii=False,indent=2))
