"""固定ETF研究的真实RQAlpha事件、品种费用与账户核验；非实盘入口。"""
from datetime import datetime
from decimal import Decimal,ROUND_CEILING,ROUND_FLOOR,ROUND_HALF_UP
import numpy as np
import pandas as pd
from rqalpha.const import INSTRUMENT_TYPE,TRADING_CALENDAR_TYPE,SIDE
from rqalpha.core.events import EVENT
from rqalpha.interface import AbstractMod,AbstractTransactionCostDecider,TransactionCost
from rqalpha.model.instrument import Instrument
from rqalpha.mod.rqalpha_mod_sys_simulation.matcher.base import OrderCancelled
from adapters.rqalpha_sample_mod import SampleSource,SampleEvents,ResearchMatcher,rq_symbol

class ETFSource(SampleSource):
    def __init__(self,dataset):
        self.dataset=dataset;self.daily=dataset['daily'];self.names={rq_symbol(s):s for s in self.daily}
        self.days=[datetime.fromisoformat(d).date() for d in dataset['calendar'] if d>='2018-01-01']
        self.rows={}
        for (s,day),m in dataset['minutes'].items():
            for r in m['validation_bars']:
                d=self.daily[s][day]
                bounds={k:float(Decimal(str(d[k])).quantize(Decimal('.001'),rounding=ROUND_HALF_UP)) for k in ('high_limit','low_limit')}
                self.rows[rq_symbol(s),datetime.fromisoformat(r['datetime'])]=dict(r,is_st=False,is_paused=bool(d['is_paused']),**bounds,factor=d['adjustment'])
        self.stamps=sorted({t for s,t in self.rows})
        # 仅需证明2018起点前已上市；首个已核验行情日作为保守可用日期，不冒充真实上市日。
        self.instruments=[Instrument(dict(order_book_id=s,symbol=s,type='ETF',round_lot=100,listed_date='2017-01-03',de_listed_date='2999-12-31',exchange='XSHG',market_tplus=dataset.get('market_tplus',{}).get(self.names[s],1))) for s in self.names]
    def get_trading_calendars(self):return {TRADING_CALENDAR_TYPE.CN_STOCK:pd.DatetimeIndex(self.dataset['calendar'])}
    def get_bar(self,instrument,dt,frequency):
        if frequency=='1m':return super().get_bar(instrument,dt,frequency)
        d=self.daily[self.names[instrument.order_book_id]][dt.strftime('%Y-%m-%d')]
        return dict(d,datetime=dt,limit_up=d['high_limit'],limit_down=d['low_limit'],total_turnover=d['turnover'])
    def history_bars(self,instrument,bar_count,frequency,fields,dt,**kwargs):
        if frequency!='1d' or fields!='close':raise ValueError('仅核账历史收盘')
        return np.array([v['close'] for day,v in self.daily[self.names[instrument.order_book_id]].items() if day<=dt.strftime('%Y-%m-%d')][-bar_count:])
    def _daily_state(self,symbol,dates,field):
        if field=='is_st':return [False for _ in dates]
        return [bool(self.daily[self.names[symbol]][pd.Timestamp(d).strftime('%Y-%m-%d')][field]) for d in dates]
    def get_dividend(self,instrument):
        fields=[('book_closure_date','i8'),('announcement_date','i8'),('dividend_cash_before_tax','f8'),('ex_dividend_date','i8'),('payable_date','i8'),('round_lot','f8')]
        def num(d):return int(d.replace('-',''))
        return np.array([(num(e['record_date']),num(e['record_date']),e['cash'],num(e['ex_date']),num(e['pay_date']),1.) for e in self.dataset['events'] if e['kind']=='cash' and rq_symbol(e['symbol'])==instrument.order_book_id],dtype=fields)

class ETFCosts(AbstractTransactionCostDecider):
    def __init__(self,multiplier):self.multiplier=multiplier
    def calc(self,args):
        value=max(5.,args.price*args.quantity*.0002)*self.multiplier
        return TransactionCost(float(Decimal(str(value)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)),0.,0.)

class ETFMatcher(ResearchMatcher):
    def _get_deal_price(self,order,instrument,open_auction=False):
        r=self.source.rows[order.order_book_id,self._env.calendar_dt];buy=order.side==SIDE.BUY
        if open_auction or r['is_paused'] or r['volume']<=0:raise OrderCancelled('无可交易分钟')
        if buy and r['open']>=r['high_limit'] or not buy and r['open']<=r['low_limit']:raise OrderCancelled('涨跌停不可成交')
        px=self._get_execution_price(order,r['open'],False)
        if px>r['high_limit'] or px<r['low_limit'] or buy and px>order.price:raise OrderCancelled('价格边界')
        return r['open']
    def _get_execution_price(self,order,deal_price,open_auction):
        buy=order.side==SIDE.BUY
        px=deal_price*(1+(.001 if buy else -.001)*self.multiplier)
        return float(Decimal(str(px)).quantize(Decimal('.001'),rounding=ROUND_CEILING if buy else ROUND_FLOOR))
    def _get_liquidity_limited_fill(self,order,instrument,open_auction=False):
        r=self.source.rows[order.order_book_id,self._env.calendar_dt]
        q=min(order.unfilled_quantity,int(r['volume']*.01/100)*100)
        if q<=0 or order.side==SIDE.BUY and q*self._get_execution_price(order,r['open'],False)<4000:raise OrderCancelled('参与率/最小金额')
        return q

class ETFMod(AbstractMod):
    def start_up(self,env,config):
        self.env=env;self.source=ETFSource(config.dataset);self.fills=[];self.curve=[]
        env.set_data_source(self.source);env.set_event_source(SampleEvents(self.source))
        env.set_transaction_cost_decider(INSTRUMENT_TYPE.ETF,ETFCosts(config.cost_multiplier))
        env.broker.register_matcher(INSTRUMENT_TYPE.ETF,ETFMatcher(env,env.config.mod.sys_simulation,self.source,config.cost_multiplier))
        env.event_bus.add_listener(EVENT.POST_SYSTEM_INIT,self.attach)
    def attach(self,event):
        self.env.event_bus.add_listener(EVENT.TRADE,self.trade)
        self.env.event_bus.add_listener(EVENT.POST_BAR,self.snapshot)
    def trade(self,event):
        t=event.trade
        self.fills.append(dict(datetime=self.env.calendar_dt.isoformat(),symbol=t.order_book_id,buy=t.side==SIDE.BUY,quantity=t.last_quantity,price=t.last_price,fee=t.transaction_cost))
    def snapshot(self,event):
        if self.env.calendar_dt.strftime('%H:%M')!='15:00':return
        p=self.env.portfolio
        self.curve.append(dict(date=self.env.calendar_dt.strftime('%Y-%m-%d'),cash=p.cash+p.frozen_cash,equity=p.total_value,positions={x.order_book_id:x.quantity for x in p.get_positions() if x.quantity}))
        for e in self.source.dataset['events']:
            if e['kind']!='cash' and e['record_date']==self.env.calendar_dt.strftime('%Y-%m-%d') and self.curve[-1]['positions'].get(rq_symbol(e['symbol']),0):raise ValueError('RQ账户持有未支持拆分权益')
    def tear_down(self,*args):return dict(fills=self.fills,curve=self.curve)

def load_mod():return ETFMod()
