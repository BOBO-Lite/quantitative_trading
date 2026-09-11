"""真实现金分红窗口的数据扩展；使用RQAlpha原生分红应收、派息与红利税。"""
from datetime import datetime
import numpy as np
import pandas as pd
from rqalpha.const import TRADING_CALENDAR_TYPE
from rqalpha.core.events import EVENT
from rqalpha.model.instrument import Instrument
from adapters.rqalpha_sample_mod import SampleSource, ResearchMod, rq_symbol

class CorporateSource(SampleSource):
    def __init__(self,dataset):
        if dataset['status']!='PASS_CORPORATE_WINDOW_DATA':raise ValueError('公司行动窗口未核验')
        self.dataset=dataset
        self.rows={(rq_symbol(r['symbol']),datetime.fromisoformat(r['datetime'])):r for r in dataset['rows']}
        if len(self.rows)!=len(dataset['rows']):raise ValueError('重复分钟')
        self.stamps=sorted({t for s,t in self.rows})
        self.days=[datetime.fromisoformat(d).date() for d in dataset['dates']]
        symbol=rq_symbol(dataset['symbol'])
        self.instruments=[Instrument(dict(order_book_id=symbol,symbol=symbol,type='CS',round_lot=100,board_type='MainBoard',listed_date='1991-04-03' if symbol.startswith('000') else '2002-04-09',de_listed_date='2999-12-31',exchange='XSHE' if symbol.endswith('XSHE') else 'XSHG',market_tplus=1))]
    def get_trading_calendars(self):
        return {TRADING_CALENDAR_TYPE.CN_STOCK:pd.DatetimeIndex(self.days)}
    def get_dividend(self,instrument):
        fields=[('book_closure_date','i8'),('announcement_date','i8'),('dividend_cash_before_tax','f8'),('ex_dividend_date','i8'),('payable_date','i8'),('round_lot','f8')]
        values=[]
        for e in self.dataset['events']:
            values.append((int(e['record_date'].replace('-','')),int(e['announcement_date'].replace('-','')),e['cash_per_share'],int(e['ex_date'].replace('-','')),int(e['pay_date'].replace('-','')),1.))
        return np.array(values,dtype=fields)

class CorporateMod(ResearchMod):
    def build_source(self,config):return CorporateSource(config.dataset)
    def start_up(self,env,config):
        super().start_up(env,config)
        self.curve=[]; self.taxes=[]
        env.event_bus.add_listener(EVENT.POST_SYSTEM_INIT,self.attach)
    def attach(self,event):
        self.env.event_bus.add_listener(EVENT.POST_BAR,self.snapshot)
        self.env.event_bus.add_listener(EVENT.PAY_TAXES,self.tax)
    def snapshot(self,event):
        p=self.env.portfolio
        self.curve.append(dict(datetime=self.env.calendar_dt.isoformat(),cash=p.cash+p.frozen_cash,equity=p.total_value))
    def tax(self,event):
        self.taxes.append(dict(datetime=self.env.calendar_dt.isoformat(),amount=event.delta_amount))
    def tear_down(self,*args):
        result=super().tear_down(*args)
        result.update(curve=self.curve,taxes=self.taxes)
        return result

def load_mod():return CorporateMod()
