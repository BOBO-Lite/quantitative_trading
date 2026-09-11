"""RQAlpha 6.3离线样本Mod：使用其事件循环、订单、撮合主流程和组合账户。
仅支持已核验的两股三日固定行情；不是通用数据源或实盘接口。
"""
from datetime import datetime, timedelta
from math import floor, isfinite
import numpy as np
import pandas as pd
from rqalpha.const import INSTRUMENT_TYPE, TRADING_CALENDAR_TYPE, SIDE
from rqalpha.core.events import EVENT, Event
from rqalpha.interface import AbstractMod, AbstractDataSource, AbstractEventSource, AbstractTransactionCostDecider, TransactionCost
from rqalpha.model.instrument import Instrument
from rqalpha.mod.rqalpha_mod_sys_simulation.matcher.bar_matcher import DefaultBarMatcher
from rqalpha.mod.rqalpha_mod_sys_simulation.matcher.base import OrderCancelled


def rq_symbol(symbol):
    return symbol.replace('.SZ', '.XSHE').replace('.SH', '.XSHG')


def submit_intent(context, symbol, quantity, buy, limit=None, allowed_symbols=None):
    """策略侧入口：限制为单持仓批次、事前限价、整百买入和T+1退出。"""
    from rqalpha.api import order_shares, get_open_orders
    if isinstance(quantity, bool) or int(quantity) != quantity or quantity <= 0:
        raise ValueError('委托数量必须是正整数')
    if symbol not in (allowed_symbols if allowed_symbols is not None else ('000001.XSHE', '600036.XSHG')):
        raise ValueError('标的不在样本范围')
    if any(o.order_book_id == symbol for o in get_open_orders()):
        raise ValueError('同标的已有未处理意图')
    position = context.portfolio.positions[symbol]
    if buy:
        if quantity % 100 or position.quantity:
            raise ValueError('买入须整百股且不得加仓')
        if limit is None or not isfinite(limit) or limit <= 0:
            raise ValueError('缺少事前买入价格上限')
        return order_shares(symbol, quantity, limit)
    if quantity > position.sellable:
        raise ValueError('T+1或可卖持仓不足')
    return order_shares(symbol, -quantity)


class SampleSource(AbstractDataSource):
    def __init__(self, dataset):
        if dataset['status'] != 'PASS_FIXED_SAMPLE_MINUTE_DATA':
            raise ValueError('分钟样本未核验')
        self.rows = {}
        for row in dataset['rows']:
            key = (rq_symbol(row['symbol']), datetime.fromisoformat(row['datetime']))
            if key in self.rows:
                raise ValueError('重复分钟')
            if type(row['is_paused']) is not bool or type(row['is_st']) is not bool:
                raise ValueError('缺历史停牌状态')
            for field in ('open','close','high','low','high_limit','low_limit','factor','volume'):
                if not isfinite(row[field]) or (row[field] < 0 if field == 'volume' else row[field] <= 0):
                    raise ValueError('非法行情字段：' + field)
            self.rows[key] = row
        self.stamps = sorted({k[1] for k in self.rows})
        self.days = sorted({t.date() for t in self.stamps})
        if self.days != [datetime(2019,4,d).date() for d in (17,18,19)]:
            raise ValueError('此数据源仅验收2019-04-17至19固定窗口')
        symbols = sorted({k[0] for k in self.rows})
        if symbols != ['000001.XSHE','600036.XSHG']:
            raise ValueError('仅验收固定两股')
        # 样本仅接受因子恒定窗口；公司行动接入前不得借用空事件表跨除权回放。
        for symbol in symbols:
            factors = {r['factor'] for (s,t), r in self.rows.items() if s == symbol}
            if len(factors) != 1:
                raise ValueError('公司行动未验收，禁止因子变化窗口')
        self.instruments = [Instrument(dict(order_book_id=s, symbol=s, type='CS', round_lot=100, board_type='MainBoard', listed_date='1991-04-03' if s.startswith('000') else '2002-04-09', de_listed_date='2999-12-31', exchange='XSHE' if s.endswith('XSHE') else 'XSHG', market_tplus=1)) for s in symbols]

    def get_instruments(self, id_or_syms=None, types=None):
        return [i for i in self.instruments if (id_or_syms is None or i.order_book_id in id_or_syms) and (not types or i.type in types)]

    def get_trading_calendars(self):
        return {TRADING_CALENDAR_TYPE.CN_STOCK: pd.DatetimeIndex(['2019-04-16','2019-04-17','2019-04-18','2019-04-19','2019-04-22'])}

    def available_data_range(self, frequency):
        return self.days[0], self.days[-1]

    def get_bar(self, instrument, dt, frequency):
        if frequency != '1m':
            raise NotImplementedError('固定源仅提供分钟，不拼造日K')
        r = self.rows.get((instrument.order_book_id, dt))
        if r is None:
            raise ValueError('缺少估值分钟')
        return dict(r, datetime=dt, limit_up=r['high_limit'], limit_down=r['low_limit'], total_turnover=r.get('turnover',0))

    def history_bars(self, instrument, bar_count, frequency, fields, dt, **kwargs):
        if fields != 'close' or frequency != '1d':
            raise NotImplementedError('不提供未经核验的历史特征')
        values = [r['close'] for (s,t),r in sorted(self.rows.items()) if s == instrument.order_book_id and t.date() <= dt.date() and t.hour == 15]
        return np.array(values[-bar_count:])

    def get_dividend(self, instrument):
        return None  # 仅允许上述固定无因子变化窗口；分红适配尚未验收

    def get_split(self, instrument):
        return None

    def is_suspended(self, order_book_id, dates):
        return self._daily_state(order_book_id, dates, 'is_paused')

    def is_st_stock(self, order_book_id, dates):
        return self._daily_state(order_book_id, dates, 'is_st')

    def _daily_state(self, symbol, dates, field):
        result = []
        for day in dates:
            rows = [r for (s,t),r in self.rows.items() if s == symbol and t.date() == pd.Timestamp(day).date()]
            if not rows:
                raise ValueError('缺历史状态，不得推断正常交易')
            result.append(any(r[field] for r in rows))
        return result


class SampleEvents(AbstractEventSource):
    def __init__(self, source): self.source = source
    def events(self, start_date, end_date, frequency):
        for day in self.source.days:
            before = datetime.combine(day, datetime.min.time()) + timedelta(hours=9)
            yield Event(EVENT.BEFORE_TRADING, calendar_dt=before, trading_dt=before)
            for stamp in self.source.stamps:
                if stamp.date() == day:
                    yield Event(EVENT.BAR, calendar_dt=stamp, trading_dt=stamp)
            after = before.replace(hour=15, minute=1)
            yield Event(EVENT.AFTER_TRADING, calendar_dt=after, trading_dt=after)


class ResearchCosts(AbstractTransactionCostDecider):
    def __init__(self, multiplier): self.multiplier = multiplier
    def calc(self, args):
        value = args.price * args.quantity
        return TransactionCost(max(5.,value*.0002)*self.multiplier, (value*.0005 if args.side == SIDE.SELL else 0)*self.multiplier, value*.00001*self.multiplier)


class ResearchMatcher(DefaultBarMatcher):
    def __init__(self, env, config, source, multiplier):
        super().__init__(env, config)
        self.source, self.multiplier = source, multiplier

    def _get_deal_price(self, order, instrument, open_auction=False):
        r = self.source.rows.get((order.order_book_id, self._env.calendar_dt))
        if open_auction or r is None or r['is_paused'] or r['volume'] <= 0:
            raise OrderCancelled('缺行情、停牌或无成交量')
        buy = order.side == SIDE.BUY
        price = r['open'] * (1 + (.001 if buy else -.001) * self.multiplier)
        if (buy and (price >= r['high_limit'] or price > order.price)) or (not buy and price <= r['low_limit']):
            raise OrderCancelled('滑点后价格越过限价或涨跌停')
        return r['open']

    def _get_execution_price(self, order, deal_price, open_auction):
        return deal_price * (1 + (.001 if order.side == SIDE.BUY else -.001) * self.multiplier)

    def _get_liquidity_limited_fill(self, order, instrument, open_auction=False):
        row = self.source.rows[order.order_book_id, self._env.calendar_dt]
        cap = floor(row['volume'] * self._volume_percent) - self._turnover[order.order_book_id]
        if order.side == SIDE.BUY: cap = cap // 100 * 100
        if cap <= 0: raise OrderCancelled('成交参与率不足')
        return min(cap, order.unfilled_quantity)

    def _handle_unfilled_order(self, account, order, open_auction):
        raise OrderCancelled('首个下一分钟撮合后取消余量')

    def match(self, account, order, open_auction):
        elapsed = (self._env.calendar_dt - order.datetime).total_seconds()
        if elapsed <= 0: return
        if elapsed != 60:
            order.mark_cancelled('缺少恰好下一分钟，意图过期')
            return
        super().match(account, order, open_auction)
        if not order.is_final(): order.mark_cancelled('首次撮合未成交，意图终止')


class ResearchMod(AbstractMod):
    def build_source(self, config):
        return SampleSource(config.dataset)

    def start_up(self, env, config):
        self.env, self.fills = env, []
        self.source = self.build_source(config)
        env.set_data_source(self.source)
        env.set_event_source(SampleEvents(self.source))
        env.set_transaction_cost_decider(INSTRUMENT_TYPE.CS, ResearchCosts(config.cost_multiplier))
        env.broker.register_matcher(INSTRUMENT_TYPE.CS, ResearchMatcher(env, env.config.mod.sys_simulation, self.source, config.cost_multiplier))
        env.event_bus.add_listener(EVENT.POST_SYSTEM_INIT, lambda event: env.event_bus.add_listener(EVENT.TRADE, self.on_trade))

    def on_trade(self, event):
        t = event.trade
        self.fills.append(dict(symbol=t.order_book_id, buy=t.side == SIDE.BUY, fill_time=self.env.calendar_dt.isoformat(), price=t.last_price, quantity=t.last_quantity, fees=t.transaction_cost, cash_after=self.env.portfolio.cash + self.env.portfolio.frozen_cash))

    def tear_down(self, *args):
        return dict(fills=self.fills, cash=self.env.portfolio.cash, equity=self.env.portfolio.total_value)


def load_mod(): return ResearchMod()



