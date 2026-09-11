"""离线分钟撮合与资金持仓账本；用于研究，不连接任何券商或平台订单接口。

消费调用方逐分钟提供的原始价与历史状态。只撮合上一分钟的意图；买入余量
立即取消，卖出未完成的部分由策略在之后重新提交。缺失分钟使意图失效。
不实现盘口队列；可选现金分红账本要求登记资格及因子桥接核对，其他公司行动停止。
"""
from dataclasses import dataclass
from datetime import datetime
from math import floor, isfinite

from s2_strategy_rules import Policy, fee, next_open_fill


@dataclass
class Holding:
    quantity: int
    entry_day: str
    factor: float
    cost: float  # 剩余数量对应的含费成本
    last_price: float


class ReplayBroker:
    def __init__(self, cash=30000., participation=.25, policy=Policy(), corporate_events=None):
        if not isfinite(cash) or cash <= 0 or not 0 < participation <= .25:
            raise ValueError('初始资金和成交参与率不合法')
        self.cash = float(cash)
        self.initial_cash = float(cash)
        self.participation = participation
        self.policy = policy
        self.positions = {}
        self.orders = []
        self.fills = []
        self.realized_pnl = 0.
        self.last_stamp = None
        from corporate_actions import CashDividendBook
        self.corporate = CashDividendBook(corporate_events) if corporate_events is not None else None
        self.dividend_adjustments = []

    @property
    def equity(self):
        return self.cash + sum(p.quantity * p.last_price for p in self.positions.values()) + (self.corporate.receivable if self.corporate else 0.)

    def close_day(self, day):
        if self.last_stamp is None or self.last_stamp.isoformat() != day + 'T15:00:00':
            raise ValueError('必须在真实收盘分钟后确认登记日持仓')
        if self.corporate:
            self.corporate.close_day(day, self.positions)

    @property
    def reserved_cash(self):
        return sum(o['reserve'] for o in self.orders if o['status'] == 'PENDING')

    def submit(self, symbol, quantity, stamp, buy, factor, limit=None):
        """收盘确认后提交；同标的一次只允许一笔意图，不允许加仓合并T+1批次。"""
        when = datetime.fromisoformat(stamp)
        if self.last_stamp is None or when != self.last_stamp:
            raise ValueError('只能在刚处理的分钟收盘时提交，不能倒填或提前委托')
        if isinstance(quantity, bool) or int(quantity) != quantity or quantity <= 0:
            raise ValueError('委托数量必须是正整数')
        if not isfinite(factor) or factor <= 0:
            raise ValueError('缺少复权因子')
        if any(o['symbol'] == symbol and o['status'] == 'PENDING' for o in self.orders):
            raise ValueError('同标的存在未处理意图')
        if buy:
            if quantity % 100 or symbol in self.positions:
                raise ValueError('买入必须整百股且不能重复加仓')
            if limit is None or not isfinite(limit) or limit <= 0:
                raise ValueError('买入必须有事前价格上限')
            reserve = limit * quantity + fee(limit * quantity, multiplier=self.policy.cost_multiplier)
            if reserve > self.cash - self.reserved_cash + 1e-8:
                raise ValueError('含费用的可用资金不足')
        else:
            holding = self.positions.get(symbol)
            if holding is None or quantity > holding.quantity:
                raise ValueError('可卖持仓不足')
            if holding.entry_day >= when.date().isoformat():
                raise ValueError('T+1禁止当日卖出')
            reserve = 0.
        order = dict(order_id=len(self.orders) + 1, symbol=symbol, quantity=int(quantity),
                     intent_time=stamp, buy=buy, factor=factor, limit=limit,
                     reserve=reserve, status='PENDING', filled_quantity=0)
        self.orders.append(order)
        return order['order_id']

    def on_minute(self, stamp, bars):
        """同一时刻的股票一起处理；不以本分钟收盘净值给本分钟开盘下单。"""
        now = datetime.fromisoformat(stamp)
        if self.last_stamp is not None and now <= self.last_stamp:
            raise ValueError('分钟必须严格递增，重复与倒序不能重复成交')
        if set(self.positions) - set(bars):
            raise ValueError('持仓缺少分钟估值；停牌也必须提供明确的状态与估值')
        if self.corporate and (self.last_stamp is None or self.last_stamp.date() != now.date()):
            self.cash += self.corporate.open_day(now.date().isoformat())
        for symbol, bar in bars.items():
            if bar.get('datetime') != stamp:
                raise ValueError('批内分钟时间不一致')
            for key in ('open', 'close', 'low', 'high_limit', 'low_limit', 'factor'):
                value = bar.get(key)
                if value is None or not isfinite(value) or value <= 0:
                    raise ValueError('缺少有效分钟字段：' + key)
            if bar.get('is_paused') is not True and bar.get('is_paused') is not False:
                raise ValueError('缺少历史停牌状态')
            if bar.get('volume') is None or not isfinite(bar['volume']) or bar['volume'] < 0:
                raise ValueError('成交量非法')
            dividend = self.corporate.adjustment(symbol, now.date().isoformat()) if self.corporate else None
            adjusted = any(x['symbol']==symbol and x['date']==now.date().isoformat() for x in self.dividend_adjustments)
            if symbol in self.positions and (bar['factor'] != self.positions[symbol].factor or (dividend is not None and not adjusted)):
                holding = self.positions[symbol]
                if adjusted or dividend is None or abs(holding.last_price * holding.factor / bar['factor'] - (holding.last_price - dividend)) > .011:
                    raise ValueError('持仓发生公司行动，必须先对账再继续回放：' + symbol)
                holding.factor = bar['factor']
                holding.last_price -= dividend
                self.dividend_adjustments.append(dict(symbol=symbol,date=now.date().isoformat(),cash_per_share=dividend))
        self.last_stamp = now
        for order in self.orders:
            if order['status'] != 'PENDING':
                continue
            elapsed = (now - datetime.fromisoformat(order['intent_time'])).total_seconds()
            if elapsed <= 0:
                continue
            symbol, buy = order['symbol'], order['buy']
            bar = bars.get(symbol)
            if elapsed != 60 or bar is None:
                order['status'] = 'EXPIRED_MISSING_MINUTE'
                continue
            if bar['factor'] != order['factor']:
                order['status'] = 'REJECTED_FACTOR_CHANGE'
                continue
            price = next_open_fill(order['intent_time'], bar, buy, order['limit'], self.policy)
            if price is None:
                order['status'] = 'UNFILLED_MARKET_GATE'
                continue
            volume_cap = floor(bar['volume'] * self.participation)
            if buy:
                volume_cap = volume_cap // 100 * 100
            quantity = min(order['quantity'], volume_cap)
            if quantity <= 0:
                order['status'] = 'UNFILLED_LIQUIDITY'
                continue
            value = quantity * price
            costs = fee(value, sell=not buy, multiplier=self.policy.cost_multiplier)
            if buy:
                if value + costs > order['reserve'] + 1e-8:
                    raise ValueError('成交超过预留资金')
                self.cash -= value + costs
                self.positions[symbol] = Holding(quantity, now.date().isoformat(), bar['factor'], value + costs, price)
                pnl = None
            else:
                holding = self.positions[symbol]
                dividend_tax = self.corporate.sell(symbol,holding.entry_day,quantity,now.date().isoformat()) if self.corporate else 0.
                self.cash -= dividend_tax
                allocated_cost = holding.cost * quantity / holding.quantity
                self.cash += value - costs
                pnl = value - costs - allocated_cost
                self.realized_pnl += pnl
                holding.quantity -= quantity
                holding.cost -= allocated_cost
                if holding.quantity == 0:
                    del self.positions[symbol]
            order['filled_quantity'] = quantity
            order['status'] = 'FILLED' if quantity == order['quantity'] else 'PARTIAL_REMAINDER_CANCELLED'
            self.fills.append(dict(order_id=order['order_id'], symbol=symbol, buy=buy,
                                   intent_time=order['intent_time'], fill_time=stamp,
                                   price=price, quantity=quantity, fees=costs,
                                   net_pnl=pnl, cash_after=self.cash))
        for symbol, holding in self.positions.items():
            if symbol in bars:
                holding.last_price = bars[symbol]['close']
        if self.cash < -1e-7:
            raise AssertionError('资金账本透支')

    def snapshot(self):
        return dict(cash=self.cash, equity=self.equity, reserved_cash=self.reserved_cash,
                    dividend_receivable=self.corporate.receivable if self.corporate else 0.,
                    dividend_income=self.corporate.gross_income if self.corporate else 0.,
                    dividend_tax=self.corporate.tax_paid if self.corporate else 0.,
                    realized_pnl=self.realized_pnl,
                    unrealized_pnl=sum(p.quantity * p.last_price - p.cost for p in self.positions.values()),
                    status='EXECUTION_REPLAY_ONLY', formal_strategy_validated=False)
