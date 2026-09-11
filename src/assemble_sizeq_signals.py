"""Merge audited exports; preserve unresolved signals and never turn gaps into cash."""
import hashlib
import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from audit_sizeq_signals import OUT, independent
from import_supermind_minute_probe import decode_packets
from sizeq_signals import select, SignalGap


def dump(name, value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')


def public_cash_exclusion(asof, source):
    # Annual report directly publishes Q4 cash: no cross-vintage subtraction.
    if asof not in ('2018-02-05','2018-02-12'):
        raise SignalGap('public evidence not registered for this signal date')
    required=['2018-02-02','601313','2017 年年度报告','-14,784,241.27',
              '经营活动产生的现金','（10-12 月份）']
    if not all(x in source for x in required):
        raise SignalGap('annual source identity or exact cash evidence absent')
    value=Decimal('-14784241.27')
    if value>0:raise SignalGap('not a decisive exclusion')
    return dict(symbol='601313.SH',reason='QUARTER_CASH_NONPOSITIVE',
                period='2017-12-31',published='2018-02-02',quarter_cash=str(value),
                method='direct published quarterly cash, annual report quarterly table',
                source='601313_2017annual_source.txt',
                source_sha256=hashlib.sha256(source.encode('utf8')).hexdigest())


def run():
    combined={};sources={};raw18=None;calendar=None
    for name in ['signals_2018','signals_2019','signals_2020','signals_2019_repair']:
        p=OUT/(name+'_export.txt');raw=p.read_bytes()
        a=json.loads((OUT/(name+'_audit.json')).read_text(encoding='utf8'))
        if hashlib.sha256(raw).hexdigest()!=a['source_sha256']:raise SignalGap('stale audit')
        packets=decode_packets(raw.decode('utf8'));schedule=packets['schedule']
        if calendar is not None and calendar!=schedule['all_days']:raise SignalGap('calendar changed')
        calendar=schedule['all_days'];sources[name]=a['source_sha256']
        audited={s['asof']:s for s in a['signals']}
        for asof,trade in schedule['schedule']:
            s=audited.get(asof,dict(asof=asof,trade=trade,status='BLOCKED',targets=None,
                                   errors=[x for x in a['errors'] if x['asof']==asof]))
            if asof in combined and (name!='signals_2019_repair' or combined[asof]['status']!='BLOCKED'):
                raise SignalGap('unexpected duplicate or replacement')
            combined[asof]=dict(s,export=name)
        if name=='signals_2018':raw18=packets
    source=(OUT/'601313_2017annual_source.txt').read_text(encoding='utf8')
    overrides=[]
    for asof in ['2018-02-05','2018-02-12']:
        proof=public_cash_exclusion(asof,source);snapshot=deepcopy(raw18['signal_'+asof])
        if {e['symbol'] for e in snapshot['decision']['errors']}!={'601313.SH'}:
            raise SignalGap('unexpected errors before evidence repair')
        original_count=len(snapshot['pool'])
        snapshot['pool']=[r for r in snapshot['pool'] if r['symbol']!='601313.SH']
        if len(snapshot['pool'])!=original_count-1:raise SignalGap('missing public exclusion identity')
        local=select(snapshot['pool'],snapshot['financial'],asof)
        targets,_,unknown=independent(snapshot)
        if unknown or local['errors'] or targets!=local['targets']:raise SignalGap('public exclusion failed independent replay')
        combined[asof].update(status='PASS',targets=targets,errors=[],public_exclusion=proof)
        overrides.append(dict(asof=asof,targets=targets,proof=proof,original_members=original_count))
    signals=[combined[k] for k in sorted(combined)]
    expected=[(calendar[i-1],calendar[i]) for i in range(1,len(calendar)) if (i-1)%5==0]
    if [(s['asof'],s['trade']) for s in signals]!=expected or len(signals)!=146:raise SignalGap('merged schedule gap')
    blocked=[s['asof'] for s in signals if s['status']!='PASS']
    requests=[dict(asof=s['asof'],trade=s['trade'],targets=s['targets']) for s in signals if s['status']=='PASS']
    symbols=sorted({v for r in requests for v in r['targets']})
    result=dict(status='BLOCKED_SIGNALS' if blocked else 'PASS_SIGNAL_RECONSTRUCTION',
                expected_signals=146,passed_signals=len(requests),blocked_dates=blocked,
                sources=sources,signals=signals,public_exclusions=overrides,performance_completed=False)
    dump('combined_signals.json',result)
    dump('execution_data_requirements.json',dict(status='PARTIAL_SIGNAL_REQUIREMENTS' if blocked else 'READY_FOR_DATA_COLLECTION',
         portfolio_replay_allowed=not blocked,blocked_dates=blocked,start='2018-01-02',end='2020-12-31',
         calendar=calendar,known_targets=symbols,requests=requests,
         required=['unadjusted daily OHLC, ST, suspension, price limits, volume',
                   'minute OHLCV after 10:00 with independently verified bar timestamp meaning',
                   'cash dividends, record/ex/pay dates, tax basis, share distributions, tradable date, rights issues',
                   'continuous data for unsold previous holdings; do not assume target exit was filled',
                   'historical commissions, stamp tax and transfer charges; consistent E1 comparison'],
         warning='Missing signals must not be skipped, converted to no-trade or treated as empty targets.'))
    print(json.dumps(dict(passed=len(requests),blocked=blocked,known_target_symbols=len(symbols)),ensure_ascii=False))


if __name__=='__main__':run()
