"""SuperMind 原生分钟回测适配器（S1.1 冻结参数）。

用途仅限 SuperMind 股票分钟回测。它不会被本地每日流水线调用，也不得直接
切换为模拟/实盘交易。正式结论仍需平台实际运行、保存报告并通过
BACKTEST_ACCEPTANCE.md；本文件存在不等于策略已经通过回测。

平台设置要求：
1. 股票策略，运行频率选择“分钟”；
2. 基准 000905.SH；
3. 回测区间按训练/验证/样本外分段运行；
4. 初始资金与本文件 CAPITAL 一致；
5. 保存源码、参数、订单/成交日志和报告。

已知平台限制：set_commission 只能设置对称比例佣金，印花税由平台引擎
自动计算，无法在策略代码中单独锁定为卖出 0.05%。因此交易税率必须在
平台报告中复核；不一致时只能标记为保守敏感性结果，不能算正式成本验收。
"""

from __future__ import division

import math

import numpy as np
import pandas as pd

try:  # 本地测试环境没有 mindgo_api；平台会走正常导入。
    from mindgo_api import *  # noqa: F401,F403
except ImportError:
    pass


STRATEGY_VERSION = "S1.1-supermind-minute-draft"
BENCHMARK = "000905.SH"
CAPITAL = 36574.55

MIN_LISTING_BARS = 120
MIN_AVG_TURNOVER_20 = 50000000.0
EXCLUDED_PREFIXES = ("300", "301", "688", "689")

BREAKOUT_DAYS = 20
RS_TOP_FRACTION = 0.35
VOLUME_RATIO_MIN = 1.3
VOLUME_RATIO_MAX = 3.0
CLOSE_LOCATION_MIN = 0.65
COMPRESSION_MAX = 0.15

ENTRY_START = (9, 45)
ENTRY_END = (10, 30)
OPEN_GAP_MIN = -0.015
OPEN_GAP_MAX = 0.03
MAX_PRICE_ABOVE_SIGNAL_CLOSE = 0.04

RISK_FRACTION = 0.0125
MAX_TOTAL_EXPOSURE = 0.70
MAX_SINGLE_EXPOSURE = 0.35
MAX_POSITIONS = 3
ATR_MULTIPLE = 1.6
MIN_STOP_DISTANCE = 0.03
MAX_STOP_DISTANCE = 0.06
GAP_STRESS_FRACTION = 0.08
MAX_GAP_LOSS_FRACTION = 0.02

BREAKEVEN_AT_R = 1.0
TRAILING_AT_R = 2.0
TRAILING_ATR_MULTIPLE = 2.0
TIME_STOP_DAYS = 8
TIME_STOP_MIN_R = 0.75
MAX_HOLDING_DAYS = 20

COMMISSION_RATE = 0.0002
TRANSFER_FEE_EACH_SIDE = 0.00001
MINIMUM_COMMISSION = 5.0
SLIPPAGE_ROUND_TRIP = 0.002  # PriceSlippage 将该值的一半用于每一边。
DAILY_VOLUME_LIMIT = 0.25
MINUTE_VOLUME_LIMIT = 0.25

HISTORY_BARS = 130
HISTORY_FIELDS = [
    "high", "low", "close", "volume", "turnover", "is_st", "is_paused"
]


def _finite_array(frame, field):
    return pd.to_numeric(frame[field], errors="coerce").values.astype(float)


def _true_range(high, low, close):
    previous = np.r_[np.nan, close[:-1]]
    return np.nanmax(
        np.vstack([high - low, np.abs(high - previous), np.abs(low - previous)]),
        axis=0,
    )


def _feature_row(symbol, frame):
    """由截至信号日的前复权日线生成一行特征；所有前置窗口均排除信号日。"""
    if frame is None or len(frame) < 61:
        return None
    frame = frame.sort_index().copy()
    high = _finite_array(frame, "high")
    low = _finite_array(frame, "low")
    close = _finite_array(frame, "close")
    volume = _finite_array(frame, "volume")
    turnover = _finite_array(frame, "turnover")
    valid_close = int(np.isfinite(close).sum())
    if valid_close < MIN_LISTING_BARS:
        return None
    required = np.r_[high[-21:], low[-21:], close[-61:], volume[-21:], turnover[-21:]]
    if not np.isfinite(required).all() or close[-1] <= 0 or low[-11:-1].min() <= 0:
        return None

    prior_volume20 = float(volume[-21:-1].mean())
    avg_turnover20 = float(turnover[-21:-1].mean())
    if prior_volume20 <= 0:
        return None
    tr = _true_range(high, low, close)
    atr20 = float(np.nanmean(tr[-20:]))
    day_range = high[-1] - low[-1]
    ma20 = float(close[-20:].mean())
    ma60 = float(close[-60:].mean())
    ma20_prev = float(close[-25:-5].mean())
    structure_low10 = float(low[-11:-1].min())
    prior_high10 = float(high[-11:-1].max())
    st_value = bool(frame["is_st"].iloc[-1])
    paused_value = bool(frame["is_paused"].iloc[-1])
    return {
        "symbol": str(symbol),
        "close_adjusted": float(close[-1]),
        "high_adjusted": float(high[-1]),
        "low_adjusted": float(low[-1]),
        "ma20": ma20,
        "ma60": ma60,
        "ma20_prev": ma20_prev,
        "prior_high_close20": float(close[-21:-1].max()),
        "volume_ratio": float(volume[-1] / prior_volume20),
        "avg_turnover20": avg_turnover20,
        "close_location": float((close[-1] - low[-1]) / day_range) if day_range > 0 else np.nan,
        "compression10": float(prior_high10 / structure_low10 - 1.0),
        "structure_low10_adjusted": structure_low10,
        "atr20_adjusted": atr20,
        "ret20": float(close[-1] / close[-21] - 1.0),
        "ret60": float(close[-1] / close[-61] - 1.0),
        "ma20_slope": float(ma20 / ma20_prev - 1.0),
        "atr_fraction": float(atr20 / close[-1]),
        "st": st_value,
        "paused": paused_value,
    }


def _benchmark_context(benchmark_frame):
    benchmark = benchmark_frame.sort_index().copy()
    benchmark_close = _finite_array(benchmark, "close")
    if len(benchmark_close) < 61 or not np.isfinite(benchmark_close[-61:]).all():
        return False, np.nan, np.nan
    benchmark_ma20 = float(benchmark_close[-20:].mean())
    benchmark_ma60 = float(benchmark_close[-60:].mean())
    benchmark_gate = bool(
        benchmark_close[-1] > benchmark_ma20 > benchmark_ma60
    )
    benchmark_ret20 = float(benchmark_close[-1] / benchmark_close[-21] - 1.0)
    benchmark_ret60 = float(benchmark_close[-1] / benchmark_close[-61] - 1.0)
    return benchmark_gate, benchmark_ret20, benchmark_ret60


def build_signal_table(history_by_symbol, benchmark_frame):
    """纯计算入口，供本地单测和平台 before_trading 共用。"""
    benchmark_gate, benchmark_ret20, benchmark_ret60 = _benchmark_context(benchmark_frame)
    if not np.isfinite(benchmark_ret20) or not np.isfinite(benchmark_ret60):
        return pd.DataFrame(), False

    rows = []
    for symbol, frame in history_by_symbol.items():
        if str(symbol).startswith(EXCLUDED_PREFIXES) or str(symbol).upper().endswith(".BJ"):
            continue
        row = _feature_row(symbol, frame)
        if row is not None:
            rows.append(row)
    table = pd.DataFrame(rows)
    if table.empty:
        return table, benchmark_gate
    table["excess20"] = table["ret20"] - benchmark_ret20
    table["excess60"] = table["ret60"] - benchmark_ret60
    table["eligible"] = (
        (~table["st"])
        & (~table["paused"])
        & (table["avg_turnover20"] >= MIN_AVG_TURNOVER_20)
    )
    for source, target in [
        ("excess20", "excess20_pct"),
        ("excess60", "excess60_pct"),
        ("volume_ratio", "volume_ratio_pct"),
        ("ma20_slope", "ma20_slope_pct"),
        ("atr_fraction", "atr_fraction_pct"),
    ]:
        table[target] = table[source].where(table["eligible"]).rank(pct=True)
    table["score"] = (
        35.0 * table["excess20_pct"]
        + 20.0 * table["excess60_pct"]
        + 20.0 * table["volume_ratio_pct"]
        + 15.0 * table["ma20_slope_pct"]
        + 10.0 * (1.0 - table["atr_fraction_pct"])
    )
    table["signal"] = (
        table["eligible"]
        & benchmark_gate
        & (table["close_adjusted"] > table["ma20"])
        & (table["ma20"] > table["ma60"])
        & (table["ma20"] > table["ma20_prev"])
        & (table["excess20_pct"] >= 1.0 - RS_TOP_FRACTION)
        & (table["close_adjusted"] > table["prior_high_close20"])
        & table["volume_ratio"].between(VOLUME_RATIO_MIN, VOLUME_RATIO_MAX)
        & (table["close_location"] >= CLOSE_LOCATION_MIN)
        & (table["compression10"] <= COMPRESSION_MAX)
    )
    return table.sort_values("score", ascending=False).reset_index(drop=True), benchmark_gate


def _portfolio_values(context):
    # 按官方stock_account对象直接读取，兼容平台沙箱静态检查。
    account = context.portfolio.stock_account
    return float(account.total_value), float(account.available_cash), account.positions


def _position_quantity(positions, symbol, available=False):
    if symbol not in positions:
        return 0
    position = positions[symbol]
    if available:
        return int(position.available_amount)
    return int(position.amount)


def _size_for_entry(candidate, reference_price, equity, cash, current_exposure):
    adjusted_to_raw = reference_price / candidate["signal_close_adjusted"]
    atr = candidate["atr20_adjusted"] * adjusted_to_raw
    structure_low = candidate["structure_low10_adjusted"] * adjusted_to_raw
    stop_distance = max(
        (reference_price - structure_low) / reference_price,
        ATR_MULTIPLE * atr / reference_price,
        MIN_STOP_DISTANCE,
    )
    if not np.isfinite(stop_distance) or stop_distance > MAX_STOP_DISTANCE:
        return None
    stop_price = reference_price * (1.0 - stop_distance)
    risk_budget = equity * RISK_FRACTION
    per_share_risk = reference_price - stop_price
    risk_qty = int(math.floor(risk_budget / per_share_risk / 100.0) * 100)
    gap_qty = int(math.floor(
        equity * MAX_GAP_LOSS_FRACTION / (reference_price * GAP_STRESS_FRACTION) / 100.0
    ) * 100)
    single_qty = int(math.floor(equity * MAX_SINGLE_EXPOSURE / reference_price / 100.0) * 100)
    total_room = max(0.0, equity * MAX_TOTAL_EXPOSURE - current_exposure)
    total_qty = int(math.floor(total_room / reference_price / 100.0) * 100)
    cash_qty = int(math.floor(cash / reference_price / 100.0) * 100)
    qty = min(risk_qty, gap_qty, single_qty, total_qty, cash_qty)
    if qty < 100 or qty * reference_price < 4000.0:
        return None
    return {
        "quantity": qty,
        "planned_stop": stop_price,
        "stop_distance": stop_distance,
        "atr_raw": atr,
        "structure_low_raw": structure_low,
    }


def _merge_entry_fill(candidate, fill_price, fill_quantity, existing, entry_date):
    """按每次成交回报合并部分成交，并据加权成交价重算初始风险。"""
    old_quantity = int(existing["filled_quantity"]) if existing is not None else 0
    old_value = float(existing["entry_price"]) * old_quantity if existing is not None else 0.0
    total_quantity = old_quantity + int(fill_quantity)
    if fill_quantity <= 0 or total_quantity <= 0:
        return existing
    average_fill = (old_value + float(fill_price) * int(fill_quantity)) / total_quantity
    ratio = average_fill / candidate["signal_close_adjusted"]
    atr = candidate["atr20_adjusted"] * ratio
    structure_low = candidate["structure_low10_adjusted"] * ratio
    stop_distance = max(
        (average_fill - structure_low) / average_fill,
        ATR_MULTIPLE * atr / average_fill,
        MIN_STOP_DISTANCE,
    )
    initial_stop = average_fill * (1.0 - stop_distance)
    return {
        "entry_date": entry_date,
        "entry_price": average_fill,
        "filled_quantity": total_quantity,
        "initial_stop": initial_stop,
        "effective_stop": initial_stop,
        "initial_r": average_fill * stop_distance,
        "atr20": atr,
        "highest_close": average_fill,
        "holding_days": 0,
    }


def init(context):
    set_benchmark(BENCHMARK)
    set_commission(PerShare(
        type="stock",
        cost=COMMISSION_RATE + TRANSFER_FEE_EACH_SIDE,
        min_trade_cost=MINIMUM_COMMISSION,
    ))
    set_slippage(PriceSlippage(SLIPPAGE_ROUND_TRIP))
    set_volume_limit(daily=DAILY_VOLUME_LIMIT, minute=MINUTE_VOLUME_LIMIT)
    set_execution("next_open")
    enable_open_bar()
    g.candidates = {}
    g.open_prices = {}
    g.entry_orders = {}
    g.entry_intents = {}
    g.triggered_symbols = set()
    g.exit_orders = {}
    g.exit_intents = {}
    g.exit_pending_symbols = set()
    g.positions_meta = {}
    g.pending_open_exit = set()
    g.subscribed = set()
    log.info("{} INIT; MINUTE BACKTEST ONLY; automatic live trading disabled".format(STRATEGY_VERSION))
    log.warn("Platform stamp tax is engine-controlled; verify it against frozen sell tax 0.05%")


def before_trading(context):
    today = get_datetime().strftime("%Y%m%d")
    securities = get_all_securities("stock", today)
    symbols = [
        str(symbol) for symbol in securities.index
        if not str(symbol).startswith(EXCLUDED_PREFIXES)
        and not str(symbol).upper().endswith(".BJ")
    ]
    benchmark_frame = history(
        BENCHMARK, ["close"], 65, "1d", False, "pre", True, False
    )
    market_gate, _, _ = _benchmark_context(benchmark_frame)
    if not market_gate:
        for symbol in list(g.subscribed):
            unsubscribe(symbol)
        g.subscribed = set()
        g.candidates = {}
        g.open_prices = {}
        g.entry_orders = {}
        g.entry_intents = {}
        g.triggered_symbols = set()
        log.info("PRETRADE {} gate=False universe={} eligible=SKIPPED candidates=0".format(
            today, len(symbols)
        ))
        return
    history_by_symbol = history(
        symbols, HISTORY_FIELDS, HISTORY_BARS, "1d", False, "pre", True, False
    )
    table, market_gate = build_signal_table(history_by_symbol, benchmark_frame)
    selected = table.loc[table["signal"]].head(20) if not table.empty else table
    candidate_symbols = selected["symbol"].tolist() if not selected.empty else []
    raw = history(
        candidate_symbols, ["high", "low", "close", "high_limit"], 1,
        "1d", False, None, True, False
    ) if candidate_symbols else {}
    candidates = {}
    for _, row in selected.iterrows():
        symbol = row["symbol"]
        raw_frame = raw.get(symbol)
        if raw_frame is None or raw_frame.empty:
            continue
        last = raw_frame.sort_index().iloc[-1]
        if float(last["high"]) == float(last["low"]) == float(last["high_limit"]):
            continue
        item = row.to_dict()
        item["signal_close_adjusted"] = float(row["close_adjusted"])
        item["signal_high_raw"] = float(last["high"])
        item["signal_close_raw"] = float(last["close"])
        candidates[symbol] = item

    for symbol in list(g.subscribed - set(candidates)):
        unsubscribe(symbol)
    for symbol in list(set(candidates) - g.subscribed):
        subscribe(symbol)
    g.subscribed = set(candidates)
    g.candidates = candidates
    g.open_prices = {}
    g.entry_orders = {}
    g.entry_intents = {}
    g.triggered_symbols = set()
    log.info("PRETRADE {} gate={} universe={} eligible={} candidates={}".format(
        today, market_gate, len(table), int(table["eligible"].sum()) if not table.empty else 0,
        len(candidates),
    ))


def open_auction(context, bar_dict):
    """只执行前一收盘已确认的次日开盘退出。"""
    _, _, positions = _portfolio_values(context)
    for symbol in list(g.pending_open_exit):
        qty = _position_quantity(positions, symbol, available=True)
        if qty > 0:
            _submit_exit(symbol, qty, "scheduled_next_open", get_datetime())
        g.pending_open_exit.discard(symbol)


def _submit_exit(symbol, quantity, reason, now):
    """每只股票同一时刻最多保留一笔退出委托。"""
    if quantity <= 0 or symbol in g.exit_pending_symbols:
        return False
    # SuperMind回测的order()会在返回订单号前同步触发on_order/on_trade。
    # 所以必须先登记股票级退出意图，不能只依赖返回后的订单号映射。
    g.exit_pending_symbols.add(symbol)
    g.exit_intents[symbol] = {"symbol": symbol, "reason": reason}
    oid = order(symbol, -quantity)
    if oid is None:
        g.exit_pending_symbols.discard(symbol)
        g.exit_intents.pop(symbol, None)
        log.info("EXIT_REJECTED {} {} qty={} reason={}".format(
            now, symbol, quantity, reason
        ))
        return False
    g.exit_orders[oid] = {"symbol": symbol, "reason": reason}
    log.info("EXIT_SUBMIT {} {} qty={} reason={}".format(
        now, symbol, quantity, reason
    ))
    return True


def _cancel_entry_remainders(now):
    for oid, info in list(g.entry_orders.items()):
        if info.get("cancel_after") == now.strftime("%Y%m%d%H%M"):
            opened = get_open_orders(order_id=oid)
            if opened:
                cancel_order(oid)
                log.info("ENTRY_REMAINDER_CANCEL {} {} order={}".format(now, info["symbol"], oid))
            info["cancel_after"] = None


def handle_bar(context, bar_dict):
    now = get_datetime()
    _cancel_entry_remainders(now)
    equity, cash, positions = _portfolio_values(context)

    # 已持仓的分钟止损；买入当日不卖，市价单由 next_open 在下一分钟开盘撮合。
    for symbol, meta in list(g.positions_meta.items()):
        qty = _position_quantity(positions, symbol, available=True)
        if qty <= 0 or now.strftime("%Y%m%d") == meta.get("entry_date"):
            continue
        current = get_current(symbol).get(symbol)
        if current is None or bool(current.is_paused):
            continue
        if float(current.low) <= float(meta["effective_stop"]):
            if float(current.close) <= float(current.low_limit):
                log.info("EXIT_BLOCKED_LIMIT_DOWN {} {} stop={}".format(
                    now, symbol, meta["effective_stop"]
                ))
                continue
            _submit_exit(symbol, qty, "protective_stop", now)

    if not g.candidates:
        return
    current_map = get_current(list(g.candidates.keys()))
    # enable_open_bar 后从当天首个可见bar保存真正开盘价，不能拿09:45分钟开盘冒充。
    for symbol, bar in current_map.items():
        if bar is not None and symbol not in g.open_prices:
            g.open_prices[symbol] = float(bar.open)
    if not (ENTRY_START <= (now.hour, now.minute) <= ENTRY_END):
        return
    current_exposure = sum(
        float(position.market_value) for position in positions.values()
    )
    position_count = sum(1 for position in positions.values() if int(position.amount) > 0)
    for symbol, candidate in sorted(g.candidates.items(), key=lambda item: item[1]["score"], reverse=True):
        if symbol in g.triggered_symbols or _position_quantity(positions, symbol) > 0:
            continue
        if position_count >= MAX_POSITIONS:
            break
        bar = current_map.get(symbol)
        if bar is None or bool(bar.is_st) or bool(bar.is_paused):
            continue
        if symbol not in g.open_prices:
            g.open_prices[symbol] = float(bar.open)
        gap = g.open_prices[symbol] / candidate["signal_close_raw"] - 1.0
        if not OPEN_GAP_MIN <= gap <= OPEN_GAP_MAX:
            continue
        if float(bar.close) >= float(bar.high_limit):
            continue
        if not (
            float(bar.close) > candidate["signal_high_raw"]
            and float(bar.close) > float(bar.avg_price)
        ):
            continue
        max_price = candidate["signal_close_raw"] * (1.0 + MAX_PRICE_ABOVE_SIGNAL_CLOSE)
        reference_price = max(float(bar.close), max_price)
        plan = _size_for_entry(candidate, reference_price, equity, cash, current_exposure)
        if plan is None:
            continue
        next_minute = (pd.Timestamp(now) + pd.Timedelta(minutes=1)).strftime("%Y%m%d%H%M")
        intent = {
            "symbol": symbol,
            "candidate": candidate,
            "plan": plan,
            "cancel_after": next_minute,
        }
        # 同步回调可能发生在order()返回前，必须提前登记意图。
        g.entry_intents[symbol] = intent
        g.triggered_symbols.add(symbol)
        oid = order(symbol, plan["quantity"], price=max_price)
        if oid is None:
            g.entry_intents.pop(symbol, None)
            g.triggered_symbols.discard(symbol)
            log.info("ENTRY_REJECTED {} {} qty={}".format(now, symbol, plan["quantity"]))
            continue
        g.entry_orders[oid] = intent
        current_exposure += plan["quantity"] * max_price
        cash -= plan["quantity"] * max_price
        position_count += 1
        log.info("ENTRY_SUBMIT {} {} qty={} cap={} confirm_close={}".format(
            now, symbol, plan["quantity"], max_price, bar.close
        ))


def on_order(context, odr):
    log.info("ORDER_EVENT {}".format(odr))
    oid = odr.order_id
    if (
        odr.symbol in g.exit_pending_symbols
        and odr.order_type == "SHORT"
        and odr.status in (ORDER_STATUS.FILLED, ORDER_STATUS.REJECTED, ORDER_STATUS.CANCELLED)
    ):
        g.exit_pending_symbols.discard(odr.symbol)


def on_trade(context, trade):
    log.info("TRADE_EVENT {}".format(trade))
    oid = trade.order_id
    symbol = trade.order_book_id
    if trade.side == SIDE.BUY and symbol in g.entry_intents:
        info = g.entry_intents[symbol]
        fill = float(trade.last_price)
        fill_quantity = int(trade.last_quantity)
        candidate = info["candidate"]
        existing = g.positions_meta.get(symbol)
        g.positions_meta[symbol] = _merge_entry_fill(
            candidate,
            fill,
            fill_quantity,
            existing,
            get_datetime().strftime("%Y%m%d"),
        )
    elif trade.side == SIDE.SELL and symbol in g.exit_intents:
        _, _, positions = _portfolio_values(context)
        if _position_quantity(positions, symbol) <= 0:
            g.positions_meta.pop(symbol, None)
            g.exit_pending_symbols.discard(symbol)
            g.exit_intents.pop(symbol, None)


def after_trading(context):
    _, _, positions = _portfolio_values(context)
    current_map = get_current(list(g.positions_meta.keys())) if g.positions_meta else {}
    for symbol, meta in list(g.positions_meta.items()):
        if _position_quantity(positions, symbol) <= 0:
            g.positions_meta.pop(symbol, None)
            continue
        bar = current_map.get(symbol)
        if bar is None or bool(bar.is_paused):
            continue
        if get_datetime().strftime("%Y%m%d") == meta["entry_date"]:
            continue
        meta["holding_days"] += 1
        close = float(bar.close)
        meta["highest_close"] = max(float(meta["highest_close"]), close)
        close_r = (close - meta["entry_price"]) / meta["initial_r"]
        if close_r >= TRAILING_AT_R:
            daily = history(symbol, ["close"], 10, "1d", False, "pre", True, False)
            ma10 = float(pd.to_numeric(daily["close"], errors="coerce").mean())
            trailing = max(ma10, meta["highest_close"] - TRAILING_ATR_MULTIPLE * meta["atr20"])
            meta["effective_stop"] = max(meta["effective_stop"], trailing)
        elif close_r >= BREAKEVEN_AT_R:
            # 平台实际费用由成交回调记录；这里用冻结费率的保守近似抬到成本上方。
            qty = max(100, _position_quantity(positions, symbol))
            commission_per_share = max(
                MINIMUM_COMMISSION / qty,
                meta["entry_price"] * (COMMISSION_RATE + TRANSFER_FEE_EACH_SIDE),
            )
            meta["effective_stop"] = max(
                meta["effective_stop"],
                meta["entry_price"] + 2.0 * commission_per_share,
            )
        if meta["holding_days"] >= MAX_HOLDING_DAYS:
            g.pending_open_exit.add(symbol)
        elif meta["holding_days"] >= TIME_STOP_DAYS and close_r < TIME_STOP_MIN_R:
            g.pending_open_exit.add(symbol)
    log.info("DAY_END {} positions={} pending_open_exit={}".format(
        get_datetime(), len(g.positions_meta), sorted(g.pending_open_exit)
    ))
