# READ ONLY: no order functions
def init(context):
    set_benchmark('000905.SH')
    subscribe('600036.SH')
    enable_open_bar()

def handle_bar(context, bar_dict):
    now = get_datetime()
    if now.strftime('%H:%M') not in ('09:30', '09:31', '09:45', '10:00', '14:59'):
        return
    current = get_current('600036.SH')['600036.SH']
    log.info('CURRENT {} open={} high={} low={} close={} avg={}'.format(now, current.open, current.high, current.low, current.close, current.avg_price))
    log.info('FLOW {} volume={} turnover={}'.format(now, current.volume, current.turnover))
    bars = history('600036.SH', ['open', 'high', 'low', 'close', 'volume', 'turnover'], 2, '1m', False, None, True, False)
    log.info('MINUTES {} {}'.format(now, bars.to_json()))

def after_trading(context):
    log.info('READONLY_DONE {}'.format(get_datetime()))
