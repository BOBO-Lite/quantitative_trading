"""AKShare日线入口的质量门禁；只产出量价数据，不推断历史状态或交易指令。"""
from datetime import date, datetime, time
from math import isfinite
import re
from zoneinfo import ZoneInfo

CHINA = ZoneInfo('Asia/Shanghai')
SYMBOL = re.compile(r'^(?:000|001|002|003|600|601|603|605)\d{3}\.(?:SH|SZ)$')
FIELD_MAP = {'开盘': 'open', '收盘': 'close', '最高': 'high', '最低': 'low',
             '成交量': 'volume', '成交额': 'amount'}


def normalize_daily(records, symbol, target, observed_at):
    """东方财富日线成交量为手，输出为股；日期来自源日K，不用抓取时刻代替。"""
    if not SYMBOL.fullmatch(symbol):
        raise ValueError('仅接受已登记的主板股票代码')
    if symbol.endswith('.SH') != symbol.startswith('6'):
        raise ValueError('股票代码与交易所不一致')
    day = date.fromisoformat(target)
    observed = datetime.fromisoformat(observed_at)
    if observed.tzinfo is None:
        raise ValueError('抓取时刻必须带时区')
    now = observed.astimezone(CHINA)
    if day > now.date() or (day == now.date() and now.time() < time(15, 10)):
        raise ValueError('目标交易日尚未完成')
    if not isinstance(records, list) or not records:
        raise ValueError('空行情不能当成停牌或沿用昨日价')
    rows, seen = [], set()
    for item in records:
        if not isinstance(item, dict) or any(k not in item for k in ['日期'] + list(FIELD_MAP)):
            raise ValueError('缺少日线字段')
        raw_day = item['日期']
        if not isinstance(raw_day, str) or date.fromisoformat(raw_day).isoformat() != raw_day:
            raise ValueError('源日期必须为YYYY-MM-DD')
        if raw_day in seen:
            raise ValueError('源日线日期重复')
        seen.add(raw_day)
        if raw_day > target:
            raise ValueError('响应越过请求目标日')
        code = item.get('股票代码')
        if code is not None and str(code).zfill(6) != symbol[:6]:
            raise ValueError('响应股票代码不一致')
        if raw_day != target:
            continue
        values = {}
        for original, normalized in FIELD_MAP.items():
            value = item[original]
            if value is None or isinstance(value, bool):
                raise ValueError('行情字段为空或类型错误')
            try:
                value = float(value)
            except (ValueError, TypeError) as exc:
                raise ValueError('行情字段非数值') from exc
            if not isfinite(value):
                raise ValueError('行情字段非有限值')
            values[normalized] = value
        if not 0 < values['low'] <= min(values['open'], values['close']) <= max(values['open'], values['close']) <= values['high']:
            raise ValueError('OHLC关系错误')
        if values['volume'] < 0 or values['amount'] < 0:
            raise ValueError('量额不能为负')
        values['volume'] *= 100
        if values['volume'] > 0:
            vwap = values['amount'] / values['volume']
            if not values['low'] - .011 <= vwap <= values['high'] + .011:
                raise ValueError('量额单位或均价与日内范围不一致')
        elif values['amount'] != 0:
            raise ValueError('零成交量与成交额冲突')
        rows.append(dict(date=target, symbol=symbol, **values, provider='akshare_eastmoney_daily',
                         observed_at=observed_at, adjustment='none', volume_unit='shares',
                         historical_state_verified=False, automatic_trading=False))
    if len(rows) != 1:
        raise ValueError('未返回目标日，禁止将昨日数据伪装为当日或推断停牌')
    return rows[0]


def compare_dated_rows(ak_row, reference):
    """独立源必须显式提供相同日期；允许量价数据源的微小舍入差异。"""
    if (ak_row['date'], ak_row['symbol']) != (reference['date'], reference['symbol']):
        raise ValueError('交叉核对日期或代码不一致')
    deltas = {f: ak_row[f] - float(reference[f]) for f in ('open', 'high', 'low', 'close', 'volume', 'amount')}
    matches = all(abs(deltas[f]) <= .011 for f in ('open', 'high', 'low', 'close'))
    matches = matches and abs(deltas['volume']) <= 100 and abs(deltas['amount']) <= max(2., .0001 * float(reference['amount']))
    return dict(matches=matches, deltas=deltas)


def normalize_tencent_daily(records, symbol, target, observed_at, version):
    """固定版本的显式单位适配；1.18.94将sz000股票误放入无需乘100的分支。"""
    if version != '1.18.94':
        raise ValueError('AKShare版本变化，腾讯单位适配必须重新验收')
    correction = 100 if symbol.startswith('000') and symbol.endswith('.SZ') else 1
    mapped = []
    for row in records:
        mapped.append({'日期': row['date'], '股票代码': symbol[:6],
                       **{cn: row[en] * correction / 100 if en == 'volume' else row[en]
                          for cn, en in FIELD_MAP.items()}})
    result = normalize_daily(mapped, symbol, target, observed_at)
    result['provider'] = 'akshare_tencent_daily'
    result['source_volume_multiplier'] = correction
    result['unit_adapter_version'] = version
    return result
