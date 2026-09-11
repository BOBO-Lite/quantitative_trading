"""仅2019-04-17至19历史回测；诊断撮合/费用/量额，禁止模拟或实盘使用。"""

SYMBOLS = ['600036.SH', '000001.SZ']


def init(context):
    set_benchmark('000905.SH')
    set_commission(PerShare(type='stock', cost=0.00021, min_trade_cost=5.0))
    set_slippage(PriceSlippage(0.002))
    set_execution('next_open')
    set_volume_limit(daily=0.25, minute=0.001)
    subscribe(SYMBOLS)
    enable_open_bar()
    g.orders = []
    g.sent = False
    g.exit_sent = False


def before_trading(context):
    day = get_datetime().strftime('%Y%m%d')
    if day not in ('20190417', '20190418', '20190419'):
        raise ValueError('HISTORICAL_PROBE_ONLY_20190417_19')
    g.flow = {s: [0.0, 0.0] for s in SYMBOLS}


def handle_bar(context, bar_dict):
    now = get_datetime()
    day, hm = now.strftime('%Y%m%d'), now.strftime('%H:%M')
    current = get_current(SYMBOLS)
    for symbol in SYMBOLS:
        bar = current[symbol]
        if hm >= '09:31':
            g.flow[symbol][0] += float(bar.volume)
            g.flow[symbol][1] += float(bar.turnover)
        if hm in ('09:30', '09:31', '09:45', '09:46', '09:47'):
            log.info('BAR {} {} open={} close={} vol={} amount={}'.format(
                now, symbol, bar.open, bar.close, bar.volume, bar.turnover))
    if day == '20190417' and hm == '09:45' and not g.sent:
        g.sent = True
        log.info('INTENT {} LIMIT 600036.SH 400 cap38; MARKET 000001.SZ 500'.format(now))
        g.orders.append(order('600036.SH', 400, price=38.0))
        g.orders.append(order('000001.SZ', 500))
    if day == '20190417' and hm == '09:46':
        for oid in g.orders:
            if oid is not None and get_open_orders(order_id=oid):
                cancel_order(oid)
                log.info('CANCEL {} {}'.format(now, oid))
    if day == '20190419' and hm == '09:45' and not g.exit_sent:
        g.exit_sent = True
        for symbol in SYMBOLS:
            order_target(symbol, 0)
    if hm in ('09:46', '09:47'):
        log.info('ACCOUNT {} {}'.format(now, context.portfolio.stock_account))


def on_order(context, odr):
    log.info('ORDER {} {}'.format(get_datetime(), odr))


def on_trade(context, trade):
    log.info('FILL {} {}'.format(get_datetime(), trade))


def after_trading(context):
    for symbol in SYMBOLS:
        daily = history(symbol, ['open', 'close', 'volume', 'turnover'], 1, '1d', False, None, True, False)
        log.info('RECON {} {} minute_flow={} daily={}'.format(get_datetime(), symbol, g.flow[symbol], daily.to_json()))
    log.info('PROBE_END {} {}'.format(get_datetime(), context.portfolio.stock_account))
