"""Research-only fundamentals arithmetic. No broker or production entrypoint.

Provider computed ROE is deliberately not an input: the SIZEQ feasibility audit
found a restated value attached to an earlier publication date.
"""
from datetime import date
import math


class DataGap(ValueError):
    pass


def day(value):
    text = str(value)[:10]
    if len(text) == 8 and text.isdigit():
        text = text[:4] + '-' + text[4:6] + '-' + text[6:]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise DataGap('invalid date: ' + str(value)) from exc


def number(value):
    if isinstance(value, bool) or value is None:
        raise DataGap('missing or nonnumeric financial field')
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise DataGap('nonnumeric financial field') from exc
    if not math.isfinite(result):
        raise DataGap('nonfinite financial field')
    return result


def previous_quarter(period):
    period = day(period)
    y, suffix = int(period[:4]), period[5:]
    mapping = {'03-31': f'{y-1}-12-31', '06-30': f'{y}-03-31',
               '09-30': f'{y}-06-30', '12-31': f'{y}-09-30'}
    if suffix not in mapping:
        raise DataGap('not a quarter end')
    return mapping[suffix]


def available_version(records, symbol, period, asof):
    """Pick latest *public* version of an exact period, never latest database row.

    Each record must identify the date this particular version was published.
    Metadata dates alone are not independent proof; provider vintage acceptance
    remains a separate gate before whole-universe research.
    """
    period, asof = day(period), day(asof)
    previous_quarter(period)
    rows = []
    for r in records:
        if r['symbol'] != symbol or day(r['period']) != period:
            continue
        publication = day(r['published'])
        if publication < period:
            raise DataGap('report published before period end')
        if publication <= asof:
            rows.append(r)
    if not rows:
        raise DataGap('no available version: ' + symbol + ' ' + period)
    newest = max(day(r['published']) for r in rows)
    selected = [r for r in rows if day(r['published']) == newest]
    if any(r != selected[0] for r in selected[1:]):
        raise DataGap('conflicting versions with same publication date')
    return selected[0]


def quarterly_metrics(current, previous, asof):
    """Compute single-quarter flows from public YTD statements, ROE in percent.

    Q1 uses its YTD flows directly; Q2-Q4 subtract previous same-year YTD.
    Both balance snapshots and every flow must be available as of the signal.
    Parent equity/parent income must use a consistently registered definition.
    """
    asof = day(asof)
    period = day(current['period'])
    if current['symbol'] != previous['symbol']:
        raise DataGap('cross-symbol quarter subtraction')
    if day(previous['period']) != previous_quarter(period):
        raise DataGap('missing immediately preceding quarter')
    for r in (current, previous):
        if not day(r['period']) <= day(r['published']) <= asof:
            raise DataGap('unavailable report version')
    income = number(current['parent_income_ytd'])
    cash = number(current['operating_cash_ytd'])
    if not period.endswith('03-31'):
        income -= number(previous['parent_income_ytd'])
        cash -= number(previous['operating_cash_ytd'])
    equity0, equity1 = number(previous['parent_equity']), number(current['parent_equity'])
    assets, liabilities = number(current['assets']), number(current['liabilities'])
    if min(equity0, equity1, assets) <= 0 or liabilities < 0:
        raise DataGap('invalid equity/assets/liabilities')
    return dict(symbol=current['symbol'], period=period, asof=asof,
                roe_quarter_pct=income * 200 / (equity0 + equity1),
                operating_cash_quarter=cash, debt_ratio=liabilities / assets)


def rank_candidates(rows, signal):
    """Input must cover the complete, audited historical universe.

    Missing rows are an upstream coverage error, not permission to silently
    replace unknown fundamentals with zero or choose a smaller survivor pool.
    """
    signal = day(signal)
    seen, ranked = set(), []
    for r in rows:
        symbol = r['symbol']
        if symbol in seen:
            raise DataGap('duplicate candidate')
        seen.add(symbol)
        if day(r['asof']) != signal or day(r['valuation_date']) != signal:
            raise DataGap('mixed valuation/signal dates')
        if r['is_st'] not in (0, 1) or r['is_paused'] not in (0, 1):
            raise DataGap('invalid trading status')
        age = (date.fromisoformat(signal) - date.fromisoformat(day(r['listed']))).days
        if age < 0:
            raise DataGap('not yet listed in historical pool')
        values = {k: number(r[k]) for k in ('float_market_cap', 'pe_ttm', 'roe_quarter_pct',
                                           'operating_cash_quarter', 'debt_ratio')}
        if values['float_market_cap'] <= 0 or values['debt_ratio'] < 0:
            raise DataGap('invalid market cap or debt ratio')
        if (r['is_st'] or r['is_paused'] or age <= 365 or values['pe_ttm'] <= 0
                or values['roe_quarter_pct'] <= 5 or values['operating_cash_quarter'] <= 0
                or values['debt_ratio'] >= .7):
            continue
        ranked.append((values['float_market_cap'], symbol))
    return [symbol for _, symbol in sorted(ranked)[:5]] if len(ranked) >= 5 else []
