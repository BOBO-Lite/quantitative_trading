"""拼接在 v5 源码末尾的历史夹具；固定买入只测试回调，完全不代表策略信号。"""
_lifecycle_init = init
_lifecycle_handle_bar = handle_bar
_lifecycle_after_trading = after_trading


def init(context):
    _lifecycle_init(context)
    subscribe('600036.SH')
    g.subscribed = {'600036.SH'}
    g.harness_sent = False
    log.warn('HISTORICAL_LIFECYCLE_FIXTURE_ONLY; FORCED ENTRY IS NOT A STRATEGY SIGNAL')


def before_trading(context):
    day = get_datetime().strftime('%Y%m%d')
    if day not in ('20190417', '20190418', '20190419'):
        raise ValueError('LIFECYCLE_HARNESS_ONLY_20190417_19')
    g.entry_rejections = {}
    g.minute_flow = {}
    if day == '20190419' and '600036.SH' in g.positions_meta:
        g.pending_open_exit.add('600036.SH')
    log.info('HARNESS_PRE {} meta={} scheduled={}'.format(day, g.positions_meta, g.pending_open_exit))


def handle_bar(context, bar_dict):
    now = get_datetime()
    if now.strftime('%Y%m%d%H%M') == '201904170945' and not g.harness_sent:
        g.harness_sent = True
        candidate = dict(signal_close_raw=35.8, signal_close_adjusted=35.8,
                         structure_low10_adjusted=34.4, atr20_adjusted=.3)
        g.entry_intents['600036.SH'] = {'candidate': candidate}
        log.info('HARNESS_FORCED_BUY {} 600036.SH 500 cap38'.format(now))
        order('600036.SH', 500, price=38.)
    _lifecycle_handle_bar(context, bar_dict)


def after_trading(context):
    _lifecycle_after_trading(context)
    log.info('HARNESS_CLOSE {} meta={} account={}'.format(
        get_datetime(), g.positions_meta, context.portfolio.stock_account))
