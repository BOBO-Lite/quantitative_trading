"""Reproduce the provider PE vintage counterexample from retained public-profit rows."""
import json
from decimal import Decimal
from assemble_sizeq_signals import OUT,dump
from import_supermind_minute_probe import decode_packets
from sizeq_signals import records_index,latest_period,ttm_income,SignalGap


def run():
    text=(OUT/'ttm_export.txt').read_text(encoding='utf8')
    if 'SIZEQ_TTM_DONE' not in text:raise SignalGap('missing TTM completion')
    packets=decode_packets(text)
    if packets!=json.loads((OUT/'ttm_packets.json').read_text(encoding='utf8')):raise SignalGap('TTM packets differ')
    results=[]
    for when in ['2017-12-29','2018-05-02','2018-07-27','2018-07-30']:
        records=[]
        for key,f in packets.items():
            if not key.startswith('income_'+when+'_'):continue
            for row in f['data']:
                r=dict(zip(f['columns'],row))
                records.append(dict(symbol=r['income_stat_symbol'],table='income',
                     period=r['income_stat_stat_date'][:10],published=r['income_stat_report_date'][:10],
                     income=r['income_stat_np_atsopc']))
        fin=records_index(records,when);frame=packets['valuation_'+when]
        for row in frame['data']:
            r=dict(zip(frame['columns'],row));sym=r['valuation_symbol'];period=latest_period(fin,sym)
            periods=[period] if period.endswith('12-31') else [period,str(int(period[:4])-1)+'-12-31',str(int(period[:4])-1)+period[4:]]
            legs=[fin[sym,'income',p] for p in periods]
            value=Decimal(str(legs[0]['income']))
            if len(legs)==3:value+=Decimal(str(legs[1]['income']))-Decimal(str(legs[2]['income']))
            if abs(float(value)-ttm_income(fin,sym,period))>0.0001:raise SignalGap('independent TTM mismatch')
            pe=r['valuation_pe_ttm'];ratio=Decimal(str(r['valuation_market_cap']))/value
            if r['valuation_date'][:10]!=when:raise SignalGap('valuation date mismatch')
            results.append(dict(asof=when,symbol=sym,period=period,legs=legs,public_ttm=str(value),
                           provider_pe=pe,diagnostic_cap_over_ttm=float(ratio),sign_match=(pe>0)==(value>0)))
    mismatches=[r for r in results if not r['sign_match']]
    controls=[r for r in results if r['symbol']!='000063.SZ']
    if len(results)!=24 or len(controls)!=20:raise SignalGap('sample coverage')
    if not all(abs(r['diagnostic_cap_over_ttm']-r['provider_pe'])<=.0051 for r in controls):raise SignalGap('control PE mismatch')
    if {(r['symbol'],r['asof']) for r in mismatches}!={('000063.SZ',d) for d in ['2018-05-02','2018-07-27']}:raise SignalGap('counterexample changed')
    dump('ttm_audit.json',dict(status='PASS_COUNTEREXAMPLE_REPRODUCTION',comparisons=24,
         ordinary_controls_matching_two_decimals=20,sign_mismatches=len(mismatches),results=results,
         limits=['24 comparisons only; not a market-wide vintage certification',
                 'capitalization divided by profit is diagnostic; A/H equity scope prevents exact PE equivalence',
                 'SQ1 uses public TTM sign only; provider PE is not a screening gate']))
    print('TTM: 24 comparisons, 20 controls, 2 sign mismatches reproduced')


if __name__=='__main__':run()
