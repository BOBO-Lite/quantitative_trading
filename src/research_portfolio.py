"""S2 多标的事件回放研究入口；只消费外部已计算的时点特征。

历史特征须外部核验；现金分红支持登记资格与保护价调整，其他公司行动停止。每个交易日要求
09:31--11:30、13:01--15:00 完整分钟批；日特征只能在收盘后生效。
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timedelta
import hashlib
import json
from math import isfinite
from pathlib import Path

from research_execution import ReplayBroker
from s2_strategy_rules import (Policy, research_regime, select_signal, entry_confirmed,
                               size_entry, planned_loss, exit_reason, close_protection)


def session_minutes(day):
    result = []
    for start, count in [('09:31:00', 120), ('13:01:00', 120)]:
        base = datetime.fromisoformat(day + 'T' + start)
        result.extend((base + timedelta(minutes=i)).isoformat() for i in range(count))
    return result


def run_bundle(bundle, policy=Policy(), rules=None, minute_loader=None):
    """显式日历、前日特征、原始分钟量额。来源声明不等于已经核验。"""
    import s2_strategy_rules as default_rules
    backend = rules or default_rules
    if rules is not None and bundle.get('research_version') != getattr(rules,'VERSION',None):
        raise ValueError('独立研究版本与规则不匹配')
    research_regime,select_signal,entry_confirmed,size_entry,exit_reason,close_protection = (
        getattr(backend,k) for k in ('research_regime','select_signal','entry_confirmed','size_entry','exit_reason','close_protection'))
    uses_industry=getattr(backend,'uses_industry',True)
    def distance_for(row,price):
        return backend.stop_distance(row,price) if hasattr(backend,'stop_distance') else max((price-row['structure_low_raw'])/price,1.6*row['atr20_raw']/price,.03)
    calendar = bundle['calendar']
    if len(calendar) < 2 or calendar != sorted(set(calendar)):
        raise ValueError('必须提供含前置信号日的唯一递增交易日历')
    for day in calendar:
        if datetime.fromisoformat(day).date().isoformat() != day:
            raise ValueError('交易日必须使用 YYYY-MM-DD')
    days = bundle['days']
    if [d['date'] for d in days] != calendar[1:]:
        raise ValueError('交易日回放不完整')
    for event in bundle.get('unsupported_corporate_events',[]):
        record,ex=event['record_date'],event['ex_date']
        if datetime.fromisoformat(record).date().isoformat()!=record or datetime.fromisoformat(ex).date().isoformat()!=ex or record>=ex:
            raise ValueError('未支持公司行动日期错误')
        if calendar[1]<=record<=calendar[-1] and record not in calendar:raise ValueError('股权登记日不在交易日历')
    broker = ReplayBroker(bundle.get('initial_cash', 30000.),
                          bundle.get('participation', .25), policy, bundle.get('corporate_events'))
    if broker.corporate:
        # 本入口固定现金起步、无初始持仓；开始前登记而开始后除息的权利明确为零。
        for record in sorted({e['record_date'] for e in broker.corporate.events.values()
                              if e['record_date']<calendar[1]<=e['ex_date']}):
            broker.corporate.close_day(record,{})
    metadata, scheduled, attempted = {}, set(), set()
    peak, halted = broker.equity, False
    max_drawdown, peak_time, trough_time, drawdown_peak_time = 0., None, None, None
    curves, decisions, minute_curve = [], [], []
    order_meta, seen_fills = {}, 0
    seen_adjustments, corporate_routes = 0, {}

    for index, day in enumerate(days, 1):
        date, prior = day['date'], calendar[index - 1]
        pre = day['previous_close']
        if pre['date'] != prior:
            raise ValueError('必须使用紧邻前一交易日收盘特征')
        regime = pre['benchmark']
        route = research_regime(*(regime[k] for k in ('close', 'ma20', 'ma60', 'slope5', 'ret20')))
        rows = pre['stocks']
        if len({r['symbol'] for r in rows}) != len(rows) or any(r['date'] != prior for r in rows):
            raise ValueError('前日股票特征日期错误或重复')
        candidates = {r['symbol']: r for r in rows if select_signal(r, route, policy)
                      and (not hasattr(backend,'needs_minutes') or backend.needs_minutes(r,route))}
        minutes = minute_loader(date,set(candidates)|set(broker.positions)) if minute_loader else day['minutes']
        if [batch['datetime'] for batch in minutes] != session_minutes(date):
            raise ValueError('缺失、重复或错序交易分钟')
        attempted.clear()
        flow = {}
        for batch in minutes:
            stamp, bars = batch['datetime'], batch['bars']
            # 候选缺分钟将破坏累计 VWAP，直接停止整次研究。
            if (set(candidates) | set(broker.positions)) - set(bars):
                raise ValueError('缺少候选或持仓分钟')
            broker.on_minute(stamp, bars)
            if bundle.get('record_minute_curve'):
                minute_curve.append(dict(datetime=stamp,cash=broker.cash,equity=broker.equity))
            for adjustment in broker.dividend_adjustments[seen_adjustments:]:
                position = metadata[adjustment['symbol']]
                cash = adjustment['cash_per_share']
                # 原始结构价格随除息减去税前分红；保本成本只减保守税后分红。
                for field in ('stop','target_ma20','highest_close'):
                    if field in position:
                        position[field] -= cash
                        if position[field] <= 0: raise ValueError('分红后保护价格无效')
                position['entry_price'] -= cash * .8
                position['breakeven_cost'] -= cash * .8 * position['quantity']
                if position['entry_price'] <= 0: raise ValueError('分红后入场参考无效')
            seen_adjustments = len(broker.dividend_adjustments)
            for fill in broker.fills[seen_fills:]:
                symbol = fill['symbol']
                info = order_meta[fill['order_id']]
                fill['route'] = info['route']
                fill['reason'] = info['reason']
                if fill['buy']:
                    holding = broker.positions[symbol]
                    row = info['signal']
                    price = fill['price']
                    distance = distance_for(row,price)
                    metadata[symbol] = dict(entry_date=date, entry_price=price,
                        breakeven_cost=holding.cost,
                        initial_r=price * distance, stop=price * (1 - distance),
                        quantity=holding.quantity, route=info['route'],
                        target_ma20=row['target_ma20_raw'], highest_close=price,
                        holding_days=0, industry=row.get('industry'))
                elif symbol not in broker.positions:
                    metadata.pop(symbol, None)
                    scheduled.discard(symbol)
                else:
                    metadata[symbol]['breakeven_cost'] *= broker.positions[symbol].quantity / metadata[symbol]['quantity']
                    metadata[symbol]['quantity'] = broker.positions[symbol].quantity
            seen_fills = len(broker.fills)
            if broker.equity > peak:
                peak, peak_time = broker.equity, stamp
            drawdown = 1 - broker.equity / peak
            if drawdown > max_drawdown:
                max_drawdown, trough_time, drawdown_peak_time = drawdown, stamp, peak_time
            halted = halted or drawdown >= policy.hard_drawdown

            # 先管理退出；收盘计划在次日第一分钟确认、第二分钟撮合。
            # 本入口不伪称支持开盘集合竞价成交。
            for symbol, holding in list(broker.positions.items()):
                position = metadata[symbol]
                if holding.entry_day == date:
                    continue
                reason = 'scheduled_exit' if symbol in scheduled else exit_reason(
                    position, bars[symbol], route, drawdown, position['holding_days'])
                if halted:
                    reason = 'drawdown_hard_stop'
                if reason:
                    scheduled.add(symbol)
                    if not bars[symbol]['is_paused']:
                        oid = broker.submit(symbol, holding.quantity, stamp, False, holding.factor)
                        order_meta[oid] = dict(route=position['route'], reason=reason)

            for symbol in candidates:
                bar = bars[symbol]
                amount = bar.get('turnover')
                if amount is None or not isfinite(amount) or amount < 0:
                    raise ValueError('累计 VWAP 缺少真实分钟成交额')
                state = flow.setdefault(symbol, dict(open=bar['open'], volume=0., amount=0.))
                state['volume'] += bar['volume']
                state['amount'] += amount
            for symbol in sorted(candidates, key=lambda s: backend.sort_key(candidates[s]) if hasattr(backend,'sort_key') else (-candidates[s]['rs_percentile'], s)):
                if symbol in attempted or symbol in broker.positions or halted or scheduled:
                    continue
                row, bar, state = candidates[symbol], bars[symbol], flow[symbol]
                if not state['volume'] or not entry_confirmed(row, bar, route, state['open'],
                                                             state['amount'] / state['volume']):
                    continue
                for field in (('structure_low_raw', 'atr20_raw', 'target_ma20_raw') if uses_industry else ('atr20_raw','target_ma20_raw')):
                    if not isfinite(row[field]) or row[field] <= 0:
                        raise ValueError('缺少原始价口径风险特征：' + field)
                if uses_industry and not row.get('industry'):
                    raise ValueError('缺少时点行业，无法计算行业暴露')
                cap = backend.entry_cap(row,route) if hasattr(backend,'entry_cap') else min(row['raw_close'] * (1.02 if route == 'range_mean_reversion' else 1.04),row['structure_low_raw']/.94)
                cap = int((cap + 1e-10) * 100) / 100
                stop = cap * (1-distance_for(row,cap))
                pending = [o for o in broker.orders if o['status'] == 'PENDING' and o['buy']]
                exposure = broker.equity - broker.cash + sum(o['quantity'] * o['limit'] for o in pending)
                qty = size_entry(cap, stop, broker.equity, broker.cash - broker.reserved_cash,
                                 exposure, route, drawdown, len(broker.positions) + len(pending), policy)
                held_risk = sum(max(0., planned_loss(p['entry_price'], p['stop'],
                    broker.positions[s].quantity, policy)) for s, p in metadata.items())
                pending_risk = sum(order_meta[o['order_id']]['risk'] for o in pending)
                industry_value = sum(broker.positions[s].quantity * broker.positions[s].last_price
                    for s, p in metadata.items() if uses_industry and p['industry'] == row.get('industry'))
                industry_value += sum(o['quantity'] * o['limit'] for o in pending
                    if uses_industry and order_meta[o['order_id']]['signal']['industry'] == row.get('industry'))
                while qty and (held_risk + pending_risk + planned_loss(cap, stop, qty, policy) > .03 * broker.equity
                               or (exposure + cap * qty) * .08 > .06 * broker.equity
                               or (uses_industry and industry_value + cap * qty > .4 * broker.equity)):
                    qty -= 100
                attempted.add(symbol)
                if qty * cap < 4000:
                    decisions.append(dict(datetime=stamp, symbol=symbol, reason='portfolio_risk_or_minimum'))
                    continue
                if symbol in bundle.get('unresolved_corporate_symbols',[]):
                    raise ValueError('拟成交股票公司行动未完成核验，停止而非剔除股票：'+symbol)
                oid = broker.submit(symbol, qty, stamp, True, row['factor'], cap)
                order_meta[oid] = dict(route=route, reason='entry_confirmation', signal=row,
                                      risk=planned_loss(cap, stop, qty, policy))

        # 收盘特征到此才允许访问，避免提前泄漏日内最终指标。
        closing = day['close_features']
        if closing['date'] != date:
            raise ValueError('收盘特征日期不匹配')
        for symbol, position in metadata.items():
            position['holding_days'] += 1
            values = closing['stocks'][symbol]
            if values['factor'] != broker.positions[symbol].factor:
                raise ValueError('收盘特征复权口径改变')
            bar = minutes[-1]['bars'][symbol]
            reason = exit_reason(position, bar, route, drawdown, position['holding_days'],
                                 close_signal=True, industry_weak=values['industry_weak'])
            if reason:
                scheduled.add(symbol)
            if not bar['is_paused']:
                metadata[symbol] = close_protection(position, bar['close'], values['ma10_raw'],
                                                    values['atr20_raw'], policy)
        # 已知送转日期只在实际登记持仓时构成未支持的权益，不能用未来事件否决先前交易。
        for event in bundle.get('unsupported_corporate_events',[]):
            if event['record_date']==date and event['symbol'] in broker.positions:
                raise ValueError('实际持仓跨越未支持公司行动登记日，停止：'+str(event))
        if broker.corporate:
            for key,event in broker.corporate.events.items():
                if event['record_date'] == date and event['symbol'] in metadata:
                    corporate_routes[key] = metadata[event['symbol']]['route']
            broker.close_day(date)
        curves.append(dict(date=date, route=route, drawdown=drawdown, halted=halted, **broker.snapshot()))

    # 终点不虚构强平，取消尚未撮合意图，保留真实末端持仓和估值。
    for order in broker.orders:
        if order['status'] == 'PENDING':
            order['status'] = 'EXPIRED_END_OF_SAMPLE'
    routes = ('trend_breakout', 'range_mean_reversion', 'industry_rotation', 'defensive_cash')
    attribution = {}
    corporate_ledger = broker.corporate.ledger if broker.corporate else []
    for item in corporate_ledger:
        item['route'] = corporate_routes.get((item['symbol'],item['ex_date']))
    for route in routes:
        realized = sum(f['net_pnl'] or 0 for f in broker.fills if f['route'] == route)
        unrealized = sum(p.quantity * p.last_price - p.cost for symbol, p in broker.positions.items()
                         if metadata[symbol]['route'] == route)
        dividends = sum(x['cash'] for x in corporate_ledger if x['route']==route and x['event'] in ('accrue','tax'))
        attribution[route] = dict(realized=realized, unrealized=unrealized, dividends_net=dividends, total=realized + unrealized + dividends)
    if abs(sum(r['total'] for r in attribution.values()) - (broker.equity - broker.initial_cash)) > 1e-7:
        raise AssertionError('分支归因与组合权益变化不一致')
    return dict(status='RESEARCH_PORTFOLIO_REPLAY_ONLY', formal_strategy_validated=False,
                research_version=getattr(backend,'VERSION','S2.1'),
                source_kind=bundle.get('source_kind', 'unspecified'), policy=asdict(policy),
                execution_convention='next_minute; scheduled exits earliest 09:32; no auction',
                final=broker.snapshot(), positions={s: asdict(p) for s, p in broker.positions.items()},
                fills=broker.fills, orders=broker.orders, daily=curves, decisions=decisions,
                minute_curve=minute_curve,
                corporate_ledger=corporate_ledger,
                metrics=dict(marked_return=broker.equity / broker.initial_cash - 1,
                             max_minute_close_drawdown=max_drawdown,
                             drawdown_peak_time=drawdown_peak_time, drawdown_trough_time=trough_time,
                             drawdown_initial_peak_is_starting_cash=drawdown_peak_time is None,
                             fees_paid=sum(f['fees'] for f in broker.fills)),
                pnl_by_route=attribution,
                realized_by_route={r: sum(f['net_pnl'] or 0 for f in broker.fills if f['route'] == r)
                                   for r in ('trend_breakout', 'range_mean_reversion',
                                             'industry_rotation', 'defensive_cash')})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--cost-multiplier', type=float, default=1.)
    args = parser.parse_args()
    raw = Path(args.bundle).read_bytes()
    result = run_bundle(json.loads(raw), Policy(cost_multiplier=args.cost_multiplier))
    result['input_sha256'] = hashlib.sha256(raw).hexdigest()
    dest = Path(args.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('status', 'formal_strategy_validated', 'final')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
