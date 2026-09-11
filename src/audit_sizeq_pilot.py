"""Audit one complete historical SIZEQ input snapshot; never creates orders."""
import json
import hashlib
from collections import Counter
from datetime import date
from pathlib import Path
from import_supermind_minute_probe import decode_packets
from external_size_quality import DataGap, day, number, quarterly_metrics, rank_candidates

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/external_size_quality'


def rows(frame, prefix=''):
    columns = frame['columns']
    if len(columns) != len(set(columns)) or len(frame['index']) != len(frame['data']):
        raise DataGap('invalid frame dimensions')
    result = []
    for values in frame['data']:
        if len(values) != len(columns): raise DataGap('ragged frame')
        if prefix and any(not c.startswith(prefix) for c in columns): raise DataGap('unexpected columns')
        result.append(dict(zip([c[len(prefix):] for c in columns], values)))
    return result


def alias_debt_exclusion(path, asof):
    """Resolve this documented identifier, without inventing missing valuation."""
    if asof != '2017-12-29': raise DataGap('single-date alias evidence only')
    directory = path.parent
    mapping = json.loads((directory/'identifier_resolution.json').read_text(encoding='utf8'))
    if (mapping['historical_symbol'], mapping['provider_financial_symbol'], mapping['effective_date']) != ('000043.SZ','001914.SZ','2019-12-16'):
        raise DataGap('unreviewed identifier mapping')
    if hashlib.sha256((directory/'code_change.pdf').read_bytes()).hexdigest() != mapping['source_sha256']:
        raise DataGap('identifier source hash')
    text = (directory/'alias_export.txt').read_text(encoding='utf8')
    if 'SIZEQ_ALIAS_DONE' not in text: raise DataGap('incomplete alias export')
    packets = decode_packets(text)
    b = rows(packets['balance_2017q3'], 'balance_stat_')
    if len(b) != 1: raise DataGap('alias balance coverage')
    b = b[0]
    if b['symbol'] != mapping['provider_financial_symbol'] or day(b['stat_date']) != '2017-09-30' or not day(b['stat_date']) <= day(b['report_date']) <= asof < mapping['effective_date']:
        raise DataGap('alias balance timing or identity')
    assets, liabilities = number(b['total_assets']), number(b['total_liabilities'])
    if assets <= 0 or liabilities < 0: raise DataGap('alias balance values')
    if liabilities/assets < .7: raise DataGap('missing valuation not resolved by debt exclusion')
    return dict(symbol=mapping['historical_symbol'],provider_symbol=b['symbol'],
                reason='DEBT_70_PERCENT_OR_MORE',debt_ratio=liabilities/assets,
                published=day(b['report_date']),period=day(b['stat_date']),
                missing_field='valuation',resolution='decisive independent exclusion; valuation remains missing',
                source_sha256=hashlib.sha256((directory/'alias_export.txt').read_bytes()).hexdigest())


def audit(path):
    text = path.read_text(encoding='utf8')
    if 'SIZEQ_PILOT_DONE' not in text or '日志条数超过限制' in text:
        raise DataGap('incomplete export')
    x = decode_packets(text)
    config = x['config']; asof = day(config['asof']); members = config['members']
    if members != sorted(set(members)): raise DataGap('duplicate members')
    indices = ['000300.SH','000905.SH','000852.SH','000001.SH','399001.SZ',
               '399006.SZ','000016.SH','000688.SH','399330.SZ']
    union = set()
    for code in indices:
        p = x['index_'+code]
        if day(p['asof']) != asof or p['code'] != code: raise DataGap('index date')
        if len(p['members']) != len(set(p['members'])): raise DataGap('duplicate index members')
        union.update(p['members'])
    mainboard = lambda s: (s.endswith('.SZ') and s.startswith(('000','001','002','003'))) or (s.endswith('.SH') and s.startswith(('600','601','603','605')))
    if sorted(s for s in union if mainboard(s)) != members: raise DataGap('universe union mismatch')
    meta = dict(zip(x['securities']['index'], rows(x['securities'])))
    prices, valuation, finances = {}, {}, {}
    expected = {'config','securities'} | {'index_'+c for c in indices}
    financial_rows = 0
    for offset in range(0, len(members), 200):
        batch = members[offset:offset+200]
        expected.update(['prices_'+str(offset), 'valuation_'+str(offset)])
        pf = x['prices_'+str(offset)]
        if set(pf) != set(batch): raise DataGap('price coverage')
        for s, f in pf.items():
            if len(f['index']) != 1 or day(f['index'][0]) != asof: raise DataGap('price date '+s)
            prices[s] = rows(f)[0]
        for r in rows(x['valuation_'+str(offset)], 'valuation_'):
            if r['symbol'] in valuation or r['symbol'] not in batch or day(r['date']) != asof:
                raise DataGap('valuation duplicate/date/universe')
            valuation[r['symbol']] = r
        for quarter in config['quarters']:
            for table in ('income','balance','cashflow'):
                key = table+'_'+quarter+'_'+str(offset); expected.add(key)
                for r in rows(x[key], table+'_stat_'):
                    period = day(r['stat_date']); published = day(r['report_date'])
                    if r['symbol'] not in batch or not period <= published <= asof:
                        raise DataGap('unavailable financial row')
                    expected_period = quarter[:4]+'-'+{'1':'03-31','2':'06-30','3':'09-30','4':'12-31'}[quarter[-1]]
                    if period != expected_period: raise DataGap('wrong financial period')
                    fk = (r['symbol'], quarter, table)
                    if fk in finances: raise DataGap('duplicate financial row')
                    finances[fk] = r; financial_rows += 1
    if set(x) != expected: raise DataGap('packet coverage')
    excluded, errors, eligible, resolved_gaps = {}, [], [], []
    def exclude(s, reason): excluded[s] = reason
    def statement(s, q):
        i,b,c = (finances[(s,q,t)] for t in ('income','balance','cashflow'))
        return dict(symbol=s,period=day(b['stat_date']),published=max(day(r['report_date']) for r in (i,b,c)),
                    parent_income_ytd=i['np_atsopc'],operating_cash_ytd=c['net_cash_flows_from_opt_act'],
                    parent_equity=b['total_quity_atsopc'],assets=b['total_assets'],liabilities=b['total_liabilities'])
    for s in members:
        try:
            m = meta[s]; listed = day(m['listed_date'])
            if listed > asof: raise DataGap('future listing in pool')
            if (date.fromisoformat(asof)-date.fromisoformat(listed)).days <= 365:
                exclude(s,'LISTED_365_DAYS_OR_LESS'); continue
            p=prices[s]
            if p['is_st'] not in (0,1) or p['is_paused'] not in (0,1): raise DataGap('status')
            if p['is_st']: exclude(s,'ST'); continue
            if p['is_paused']: exclude(s,'PAUSED'); continue
            if s == '000043.SZ' and s not in valuation:
                proof = alias_debt_exclusion(path, asof)
                resolved_gaps.append(proof)
                exclude(s, proof['reason']); continue
            v=valuation[s]
            if number(v['pe_ttm']) <= 0: exclude(s,'PE_NONPOSITIVE'); continue
            current, previous = statement(s,'2017q3'), statement(s,'2017q2')
            if number(current['assets']) <= 0: raise DataGap('nonpositive assets')
            if number(current['liabilities'])/number(current['assets']) >= .7:
                exclude(s,'DEBT_70_PERCENT_OR_MORE');continue
            metrics=quarterly_metrics(current,previous,asof)
            if metrics['roe_quarter_pct'] <= 5: exclude(s,'QUARTER_ROE_5_OR_LESS');continue
            if metrics['operating_cash_quarter'] <= 0: exclude(s,'QUARTER_CASH_NONPOSITIVE');continue
            cap=number(p['close'])*number(v['circulating_cap'])
            eligible.append(dict(metrics,listed=listed,valuation_date=day(v['date']),float_market_cap=cap,
                                 pe_ttm=number(v['pe_ttm']),is_st=p['is_st'],is_paused=p['is_paused']))
        except (KeyError,DataGap) as exc:
            errors.append(dict(symbol=s,error=str(exc)))
    targets = rank_candidates(eligible,asof) if not errors else None
    if len(excluded)+len(errors)+len(eligible) != len(members): raise DataGap('classification coverage')
    return dict(status='PASS_SINGLE_SIGNAL_DECISION_AUDIT' if not errors else 'BLOCKED_SINGLE_SIGNAL_INPUTS',
                source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),asof=asof,
                packets=len(x),members=len(members),financial_rows=financial_rows,
                excluded_counts=dict(Counter(excluded.values())),excluded=excluded,
                errors=errors,resolved_gaps=resolved_gaps,eligible_rows=eligible,targets=targets,
                scope='single historical signal; not portfolio performance or full vintage acceptance')


if __name__ == '__main__':
    result=audit(OUT/'pilot_export.txt')
    (OUT/'pilot_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('excluded','eligible_rows')},ensure_ascii=False))
