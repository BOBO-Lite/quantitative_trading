"""S2.1 独立研究规则；输入必须是已收盘、同一复权口径的时点快照。

不连接每日交易入口。财报日历、原始分钟价和历史状态缺失时失败关闭。
四个分支共用执行约束，不将单元测试等同于盈利验证。
"""
from dataclasses import dataclass
from datetime import datetime, time
from math import floor, isfinite


ROUTES = ('trend_breakout', 'range_mean_reversion', 'industry_rotation', 'defensive_cash')


@dataclass(frozen=True)
class Policy:
    breakout_volume: float = 1.3
    range_discount: float = .025
    industry_top_fraction: float = .2
    risk_fraction: float = .0125
    max_positions: int = 3
    hard_drawdown: float = .15
    reduce_drawdown: float = .12
    cost_multiplier: float = 1.

    def __post_init__(self):
        if not (0 < self.risk_fraction <= .0125 and self.max_positions in (1, 2, 3)
                and 0 < self.reduce_drawdown < self.hard_drawdown <= .15
                and isfinite(self.cost_multiplier) and 1 <= self.cost_multiplier <= 2):
            raise ValueError('研究参数不得放大风险或降低成本压力')


def research_regime(close, ma20, ma60, slope5, ret20):
    """独立于现有S2.0路由；弱势优先，避免缓慢下跌被判为可低吸。"""
    if not all(isfinite(x) for x in (close, ma20, ma60, slope5, ret20)) or min(close, ma20, ma60) <= 0:
        return 'defensive_cash'
    if close < ma60 and ma20 < ma60 and slope5 < 0 and ret20 < 0:
        return 'defensive_cash'
    if close > ma20 > ma60 and slope5 > 0:
        return 'trend_breakout'
    if (abs(close / ma20 - 1) <= .035 and abs(close / ma60 - 1) <= .04
            and abs(ma20 / ma60 - 1) <= .04 and abs(slope5) <= .02 and ret20 >= -.03):
        return 'range_mean_reversion'
    if close > ma60 and ret20 >= -.03:
        return 'industry_rotation'
    return 'defensive_cash'


def eligible(row):
    """缺少可信时点状态或财报禁止跨期核验时不选股。"""
    symbol = str(row.get('symbol', ''))
    if not (symbol.endswith('.SH') or symbol.endswith('.SZ')):
        return False
    if symbol.startswith(('300', '301', '688', '689')):
        return False
    if row.get('is_st') is not False or row.get('is_paused') is not False:
        return False
    if row.get('event_clear') is not True or row.get('pit_verified') is not True:
        return False
    return row.get('listing_bars', 0) >= 120 and row.get('amount20', 0) >= 50_000_000


def select_signal(row, route, policy=Policy()):
    if route not in ROUTES:
        raise ValueError('未知研究分支')
    if route == 'defensive_cash' or not eligible(row):
        return False
    fields = ('close', 'ma20', 'ma60', 'ma20_previous', 'previous_close',
              'prior_breakout_close', 'volume_ratio', 'close_location', 'compression10',
              'rs_percentile', 'rsi14')
    if any(not isfinite(float(row.get(k, float('nan')))) for k in fields):
        return False
    c, m20, m60 = row['close'], row['ma20'], row['ma60']
    if min(c, m20, m60) <= 0:
        return False
    if route == 'trend_breakout':
        return (c > m20 > m60 and m20 > row['ma20_previous'] and row['rs_percentile'] >= .65
                and c > row['prior_breakout_close']
                and policy.breakout_volume <= row['volume_ratio'] <= 3
                and row['close_location'] >= .65 and row['compression10'] <= .15)
    if route == 'range_mean_reversion':
        return (.94 * m20 <= c <= (1 - policy.range_discount) * m20
                and abs(m20 / m60 - 1) <= .04 and 25 <= row['rsi14'] <= 45
                and c > row['previous_close'] and row['close_location'] >= .6
                and row['volume_ratio'] <= 1.5)
    asof = row.get('industry_asof')
    if not asof or str(asof)[:10] >= str(row['date'])[:10]:
        return False
    strength = row.get('industry_percentile', float('nan'))
    industry_return = row.get('industry_return20', float('nan'))
    return (isfinite(strength) and strength >= 1 - policy.industry_top_fraction
            and isfinite(industry_return) and industry_return > 0
            and row['rs_percentile'] >= .65 and c > m20 > m60
            and c <= 1.05 * m20 and c > row['previous_close']
            and row['close_location'] >= .6 and .8 <= row['volume_ratio'] <= 2.5)


def fee(value, sell=False, multiplier=1.):
    return (max(5., value * .0002) + value * (.00001 + (.0005 if sell else 0))) * multiplier


def planned_loss(price, stop, quantity, policy=Policy()):
    """price已含买入滑点；止损侧再计卖出滑点及往返税费。不是跳空损失上限。"""
    proceeds_price = stop * (1 - .001 * policy.cost_multiplier)
    return ((price - proceeds_price) * quantity
            + fee(price * quantity, multiplier=policy.cost_multiplier)
            + fee(proceeds_price * quantity, sell=True, multiplier=policy.cost_multiplier))


def size_entry(price, stop, equity, cash, exposure, route, drawdown, count, policy=Policy()):
    if route not in ROUTES:
        raise ValueError('未知研究分支')
    if route == 'defensive_cash' or drawdown >= policy.reduce_drawdown or count >= policy.max_positions:
        return 0
    if not all(isfinite(v) for v in (price, stop, equity, cash, exposure, drawdown)):
        return 0
    if min(price, equity, cash) <= 0 or stop >= price or stop <= 0 or min(exposure, drawdown, count) < 0:
        return 0
    distance = (price - stop) / price
    if not .03 - 1e-12 <= distance <= .06 + 1e-12:
        return 0
    cap = {'trend_breakout': .9, 'range_mean_reversion': .7, 'industry_rotation': .85}[route]
    single = .4 if route == 'trend_breakout' else .35
    value = min(equity * policy.risk_fraction / distance, equity * .02 / .08,
                equity * single, max(0., equity * cap - exposure), cash)
    qty = max(0, floor(value / price / 100) * 100)
    while qty and (price * qty + fee(price * qty, multiplier=policy.cost_multiplier) > cash
                   or planned_loss(price, stop, qty, policy) > equity * policy.risk_fraction):
        qty -= 100
    return qty if qty * price >= 4000 else 0


def entry_confirmed(signal, minute, route, day_open, day_vwap):
    """分钟收盘确认，函数只生成意图；撮合必须另用下一分钟开盘。"""
    now = datetime.fromisoformat(str(minute['datetime']))
    if now.date().isoformat() <= str(signal['date'])[:10] or not time(9, 45) <= now.time() <= time(10, 30):
        return False
    if route not in ROUTES or route == 'defensive_cash' or minute.get('is_paused') is not False:
        return False
    if minute.get('factor') != signal.get('factor') or signal.get('factor') is None:
        return False  # 跨除权信号拒绝；不猜测平台factor方向。
    if minute['close'] >= minute['high_limit']:
        return False
    reference = signal['raw_close']
    if not all(isfinite(float(v)) and float(v) > 0 for v in
               (reference, signal['raw_high'], day_open, day_vwap, minute['close'], minute['high_limit'])):
        return False
    if not -.015 <= day_open / reference - 1 <= .03:
        return False
    cap = reference * (1.02 if route == 'range_mean_reversion' else 1.04)
    threshold = signal['raw_high'] if route == 'trend_breakout' else reference
    return threshold < minute['close'] <= cap and minute['close'] > day_vwap


def next_open_fill(intent_time, minute, buy, limit=None, policy=Policy()):
    """不使用触发分钟成交；只接受下一分钟，拒绝过期意图及涨跌停成交。"""
    now = datetime.fromisoformat(str(minute['datetime']))
    before = datetime.fromisoformat(str(intent_time))
    if (now - before).total_seconds() != 60 or minute.get('is_paused') is not False:
        return None
    if not all(isfinite(float(minute.get(k, float('nan')))) and float(minute[k]) > 0
               for k in ('open', 'volume', 'high_limit', 'low_limit')):
        return None
    price = minute['open'] * (1 + (.001 if buy else -.001) * policy.cost_multiplier)
    if buy and (minute['open'] >= minute['high_limit'] or price >= minute['high_limit']):
        return None
    if not buy and (minute['open'] <= minute['low_limit'] or price <= minute['low_limit']):
        return None
    if buy and limit is not None and price > limit:
        return None
    return price


def exit_reason(position, minute, route, drawdown, holding_days, close_signal=False, industry_weak=False):
    """盘中保护优先；日线退出须在收盘确认，下一交易日再执行。"""
    day = str(minute['datetime'])[:10]
    if (day < position['entry_date'] or (day == position['entry_date'] and not close_signal)
            or minute.get('is_paused') is not False):
        return None
    if drawdown >= .15:
        return 'drawdown_hard_stop'
    if route == 'defensive_cash':
        return 'cash_defense'
    if minute['low'] <= position['stop']:
        return 'protective_stop'
    if close_signal:
        if position['route'] == 'industry_rotation' and industry_weak:
            return 'industry_strength_lost'
        if position['route'] == 'range_mean_reversion' and minute['close'] >= position['target_ma20']:
            return 'mean_reversion_target'
        if holding_days >= (8 if position['route'] == 'range_mean_reversion' else 20):
            return 'time_exit'
        if holding_days >= 8 and minute['close'] < position['entry_price'] + .75 * position['initial_r']:
            return 'stalled_trade'
    return None


def close_protection(position, close, ma10, atr20, policy=Policy()):
    """仅收盘后更新次日保护价；输入须已统一到当前可交易原始价格口径。"""
    result = dict(position)
    if not all(isfinite(v) and v > 0 for v in (close, ma10, atr20)):
        raise ValueError('保护价输入不可缺失')
    entry, risk, qty = position['entry_price'], position['initial_r'], position['quantity']
    if risk <= 0 or qty <= 0:
        raise ValueError('持仓风险与数量必须为正')
    result['highest_close'] = max(position.get('highest_close', entry), close)
    r = (close - entry) / risk
    if r >= 1:
        total = position.get('breakeven_cost', entry * qty + fee(entry * qty, multiplier=policy.cost_multiplier))
        if not isfinite(total) or total <= 0:
            raise ValueError('持仓含费保本成本无效')
        rate = policy.cost_multiplier
        sell_proportional = total / (qty * (1 - .00071 * rate))
        sell_minimum = (total + 5 * rate) / (qty * (1 - .00051 * rate))
        # 预留一边设定滑点；跳空与跌停仍可能使成交低于保本价。
        breakeven_trigger = max(sell_proportional, sell_minimum) / (1 - .001 * rate)
        result['stop'] = max(result['stop'], breakeven_trigger)
    if r >= 2 and position['route'] != 'range_mean_reversion':
        result['stop'] = max(result['stop'], ma10, result['highest_close'] - 2 * atr20)
    return result
