"""TECH1固定季度的真实RQAlpha账户核验，消费已核验缓存和确定的交易意图。"""
from datetime import datetime
import numpy as np
import pandas as pd
from rqalpha.const import TRADING_CALENDAR_TYPE
from rqalpha.model.instrument import Instrument
from adapters.rqalpha_sample_mod import SampleSource,rq_symbol
from adapters.rqalpha_corporate_mod import CorporateMod
from research_portfolio import session_minutes

class QuarterSource(SampleSource):
    def __init__(self,dataset):
        self.cache=dataset['cache'];self.dataset=dataset
        self.names={rq_symbol(s):s for s in dataset['symbols']}
        self.days=[datetime.fromisoformat(d).date() for d in dataset['calendar'][1:]]
        self.stamps=[datetime.fromisoformat(t) for d in dataset['calendar'][1:] for t in session_minutes(d)]
        self.rows={(rq_symbol(s),datetime.fromisoformat(r['datetime'])):r for (s,d),rows in self.cache.minutes.items() if s in dataset['symbols'] for r in rows}
        self.instruments=[]
        for s in dataset['symbols']:
            code=rq_symbol(s);m=dataset['metadata'][s]
            self.instruments.append(Instrument(dict(order_book_id=code,symbol=code,type='CS',round_lot=100,board_type='MainBoard',listed_date=m['listed_date'],de_listed_date=m['de_listed_date'],exchange='XSHE' if s.endswith('.SZ') else 'XSHG',market_tplus=1)))
    def get_trading_calendars(self):return {TRADING_CALENDAR_TYPE.CN_STOCK:pd.DatetimeIndex(self.dataset['calendar'])}
    def get_bar(self,instrument,dt,frequency):
        if frequency=='1m':return super().get_bar(instrument,dt,frequency)
        if frequency!='1d':raise ValueError('未验收的行情频率')
        r=self.cache.daily[self.names[instrument.order_book_id]][dt.strftime('%Y-%m-%d')]
        return dict(r,datetime=dt,limit_up=r['high_limit'],limit_down=r['low_limit'],total_turnover=r['turnover'])
    def history_bars(self,instrument,bar_count,frequency,fields,dt,**kwargs):
        if fields!='close' or frequency!='1d':raise ValueError('本核验源只提供历史收盘')
        h=self.cache.daily[self.names[instrument.order_book_id]]
        return np.array([r['close'] for d,r in sorted(h.items()) if d<=dt.strftime('%Y-%m-%d')][-bar_count:])
    def _daily_state(self,symbol,dates,field):
        h=self.cache.daily[self.names[symbol]]
        values=[h[pd.Timestamp(d).strftime('%Y-%m-%d')][field] for d in dates]
        if any(v not in (0,1) for v in values):raise ValueError('历史状态不明确')
        return [bool(v) for v in values]
    def get_dividend(self,instrument):
        fields=[('book_closure_date','i8'),('announcement_date','i8'),('dividend_cash_before_tax','f8'),('ex_dividend_date','i8'),('payable_date','i8'),('round_lot','f8')]
        values=[]
        for e in self.dataset['events']:
            if rq_symbol(e['symbol'])!=instrument.order_book_id:continue
            values.append((int(e['record_date'].replace('-','')),int(e['announcement_date'].replace('-','')),e['cash_per_share'],int(e['ex_date'].replace('-','')),int(e['pay_date'].replace('-','')),1.))
        return np.array(values,dtype=fields)

class QuarterMod(CorporateMod):
    def build_source(self,config):return QuarterSource(config.dataset)

def load_mod():return QuarterMod()
