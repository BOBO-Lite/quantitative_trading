"""ETF1.0固定两标的、周入场/收盘风控、真实09:35分钟执行研究。"""
from datetime import date
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
import json
from statistics import mean
from etf_dataset import build,features,SYMBOLS,OUT

VERSION='ETF1.0'

def tick(value,buy=True):
    return float(Decimal(str(value)).quantize(Decimal('.001'),rounding=ROUND_CEILING if buy else ROUND_FLOOR))

def commission(notional,cost=1.):
    return float(Decimal(str(max(5.,notional*.0002)*cost)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))

def loss(quantity,cap,stop,cost):
    return quantity*max(0,cap-stop*(1-.001*cost))+commission(quantity*cap,cost)+commission(quantity*stop,cost)

def size(cap,stop,equity,cash,exposure,existing_risk,cost):
    qty=int(min(equity*.35,equity*.02/.08,equity*.7-exposure,cash)/cap/100)*100
    while qty>0:
        risk=loss(qty,cap,stop,cost)
        if qty*cap+commission(qty*cap,cost)<=cash and risk<=equity*.0125 and risk+existing_risk<=equity*.03:break
        qty-=100
    return qty if qty*cap>=4000 else 0

def execution(bar,daily,buy,quantity,cost,cap=None):
    if daily['is_paused'] or bar['volume']<=0:return 0,None,'paused_or_empty'
    # 平台涨跌停字段未对ETF最小价位取整；向最近0.001元还原交易阈值。
    hi=float(Decimal(str(daily['high_limit'])).quantize(Decimal('.001'),rounding=ROUND_HALF_UP))
    lo=float(Decimal(str(daily['low_limit'])).quantize(Decimal('.001'),rounding=ROUND_HALF_UP))
    if buy and bar['open']>=hi or not buy and bar['open']<=lo:return 0,None,'limit_locked'
    px=tick(bar['open']*(1+(.001*cost if buy else -.001*cost)),buy)
    if px>hi or px<lo or buy and cap is not None and px>cap:return 0,None,'price_limit'
    qty=min(quantity,int(bar['volume']*.01/100)*100)
    if not qty:return 0,None,'participation'
    return qty,px,'filled' if qty==quantity else 'partial'

def long_features(history):
    if len(history)<200:return None
    base=history[-1]['adjustment'];ma=mean(r['close']*r['adjustment']/base for r in history[-200:])
    return dict(date=history[-1]['date'],close=history[-1]['close'],ma60=ma,amount20=mean(r['turnover'] for r in history[-21:-1]),adjustment=base)

def replay(calendar,daily,events,minutes,cost=1.,end='2022-12-30',variant=VERSION,symbols=SYMBOLS):
    if variant not in ('ETF1.0','ETF2.0','ETF3.0'):raise ValueError('未登记研究版本')
    feature_fn=long_features if variant in ('ETF2.0','ETF3.0') else features
    cash=30000.;peak=cash;positions={};rights={};receivables={};paid=0.;fills=[];curve=[];orders=[];paused=False;hard=False
    history={s:[] for s in symbols};previous_features={};previous_day=None;pending={};status='COMPLETED';block=None
    for day in calendar:
        if day>end:break
        if day<'2018-01-01':
            for s in symbols:history[s].append(daily[s][day])
            previous_day=day;previous_features={s:feature_fn(history[s]) for s in symbols};continue
        # 当日已公开的除息事实可调整保护价，现金收益只在取得权利时记一次。
        for i,e in enumerate(events):
            s=e['symbol']
            if e['kind']=='cash' and e['ex_date']==day:
                amount=rights.get(i,0)*e['cash'];receivables[i]=amount
                if s in positions:
                    positions[s]['stop']-=e['cash'];positions[s]['highest_close']-=e['cash']
            if e.get('pay_date')==day:
                amount=receivables.pop(i,0);cash+=amount;paid+=amount
        # 定仓依据前收盘，除息口径转为当日；不读取尚未发生的当日高低收盘。
        marks={s:history[s][-1]['close']*history[s][-1]['adjustment']/daily[s][day]['adjustment'] for s in symbols}
        equity=cash+sum(receivables.values())+sum(p['quantity']*marks[s] for s,p in positions.items())
        sold_today=set()
        for s in sorted(list(pending)):
            if s not in positions:pending.pop(s);continue
            p=positions[s]
            if p['entry_date']==day:continue
            requested=p['quantity'];q,price,reason=execution(minutes[s,day],daily[s][day],False,requested,cost)
            orders.append(dict(date=day,symbol=s,buy=False,quantity=requested,reason=pending[s],execution=reason))
            if q:
                fee=commission(q*price,cost);cash+=q*price-fee;p['quantity']-=q;sold_today.add(s)
                fills.append(dict(datetime=day+'T09:35:00',symbol=s,buy=False,quantity=q,price=price,fee=fee,reason=pending[s]))
                if not p['quantity']:del positions[s];pending.pop(s)
        first_week=date.fromisoformat(day).isocalendar()[:2]!=date.fromisoformat(previous_day).isocalendar()[:2]
        if variant in ('ETF2.0','ETF3.0'):first_week=day[:7]!=previous_day[:7]
        if first_week and not paused and not hard:
            for s in symbols:
                f=previous_features[s]
                if s in positions or s in sold_today or f is None or f['amount20']<50_000_000:continue
                signal=f['close']>f['ma60'] if variant in ('ETF2.0','ETF3.0') else f['close']>f['ma20']>f['ma60']
                if not signal:continue
                ratio=f['adjustment']/daily[s][day]['adjustment'];cap=tick(f['close']*ratio*1.02,False)
                distance=.06 if variant in ('ETF2.0','ETF3.0') else max(2*f['atr']*ratio/cap,.03)
                if distance>.06:continue
                stop=cap*(1-distance)
                exposure=sum(p['quantity']*marks[a] for a,p in positions.items())
                equity=cash+sum(receivables.values())+exposure
                risk=sum(loss(p['quantity'],marks[a],p['stop'],cost) for a,p in positions.items())
                quantity=size(cap,stop,equity,cash,exposure,risk,cost)
                if not quantity:continue
                q,price,reason=execution(minutes[s,day],daily[s][day],True,quantity,cost,cap)
                # 参与率导致过小零碎成交时取消买单，退出不设最小金额。
                if q and q*price<4000:q=0;reason='small_partial'
                orders.append(dict(date=day,symbol=s,buy=True,quantity=quantity,cap=cap,stop=stop,execution=reason))
                if q:
                    fee=commission(q*price,cost);cash-=q*price+fee
                    positions[s]=dict(quantity=q,entry_date=day,entry_price=price,stop=stop,highest_close=price)
                    fills.append(dict(datetime=day+'T09:35:00',symbol=s,buy=True,quantity=q,price=price,fee=fee,reason='monthly_trend' if variant in ('ETF2.0','ETF3.0') else 'weekly_trend'))
        for s in symbols:history[s].append(daily[s][day])
        current={s:feature_fn(history[s]) for s in symbols}
        equity=cash+sum(receivables.values())+sum(p['quantity']*daily[s][day]['close'] for s,p in positions.items())
        peak=max(peak,equity);dd=1-equity/peak;paused=paused or dd>=.12;hard=hard or dd>=.15
        for s,p in positions.items():
            f=current[s];close=daily[s][day]['close']
            if hard:pending[s]='hard_drawdown'
            elif close<=p['stop']:pending[s]='close_stop'
            elif close<f['ma60']:pending[s]='ma200_exit' if variant in ('ETF2.0','ETF3.0') else 'ma60_exit'
            p['highest_close']=max(p['highest_close'],close)
            p['stop']=max(p['stop'],p['highest_close']*.94 if variant in ('ETF2.0','ETF3.0') else p['highest_close']-2*f['atr'])
        for i,e in enumerate(events):
            if e['record_date']==day:
                quantity=positions.get(e['symbol'],{}).get('quantity',0);rights[i]=quantity
                if quantity and e['kind']!='cash':status='BLOCKED_CORPORATE_ACTION';block=dict(date=day,event=e,quantity=quantity)
        if cash<-.000001:raise ValueError('现金透支')
        curve.append(dict(date=day,cash=cash,equity=equity,receivable=sum(receivables.values()),drawdown=dd,paused=paused,hard_halted=hard,positions={s:p['quantity'] for s,p in positions.items()}))
        previous_day=day;previous_features=current
        if block:break
    return dict(version=variant,cost=cost,status=status,block=block,days=len(curve),final=curve[-1],positions=positions,pending_exits=pending,
                metrics=dict(marked_return=curve[-1]['equity']/30000-1,max_close_drawdown=max(r['drawdown'] for r in curve),fees=sum(f['fee'] for f in fills),dividends_paid=paid),fills=fills,orders=orders,daily=curve,
                limitations=['09:35单分钟成交模型；日收盘回撤不等于分钟最大回撤','共用固定标的，不代表全ETF池无生存者偏差','拆分只有无权益时可继续；持有权益时必须中止'])

def main():
    import sys
    out=OUT/'extended_2018_2026' if '--extended' in sys.argv else OUT
    variant='ETF2.0' if '--long' in sys.argv else VERSION
    data=build(out=OUT/'extended_2018_2026' if variant=='ETF2.0' else out);summary=[]
    if variant=='ETF2.0':out=OUT/'long_trend';out.mkdir(exist_ok=True)
    for cost in (1.,1.5):
        r=replay(*data,cost=cost,end=data[0][-1],variant=variant)
        (out/f'cost{cost}.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf8')
        summary.append({k:r[k] for k in ('cost','status','days','final','metrics','block')})
    (out/'run_status.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
