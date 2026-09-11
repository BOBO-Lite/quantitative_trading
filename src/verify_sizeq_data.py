"""Recheck stored SIZEQ exports and the known financial-vintage counterexample."""
import json
import re
import hashlib
from pathlib import Path
from import_supermind_minute_probe import decode_packets
from audit_sizeq_pilot import audit, OUT

def frame_rows(frame):
    # Diagnostic all-field queries sometimes repeat the same stat_date column.
    result=[]
    for values in frame['data']:
        if len(values)!=len(frame['columns']): raise ValueError('ragged frame')
        r={}
        for c,v in zip(frame['columns'],values):
            if c in r and r[c]!=v: raise ValueError('conflicting repeated field')
            r[c]=v
        result.append(r)
    return result

def run():
    exports={}; packets={}
    for name in ['feasibility','quarter','revision','previous_period','original_quarters','cutoff','pilot','alias']:
        p=OUT/(name+'_export.txt');t=p.read_text(encoding='utf8')
        if not re.search(r'SIZEQ_[A-Z_]+_DONE',t) or '日志条数超过限制' in t: raise ValueError('incomplete '+name)
        x=decode_packets(t)
        if x!=json.loads((OUT/(name+'_packets.json')).read_text(encoding='utf8')): raise ValueError('packet file mismatch '+name)
        errors={k:v for k,v in x.items() if isinstance(v,dict) and v.get('status')=='ERROR'}
        exports[name]=dict(packets=len(x),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),diagnostic_errors=errors)
        packets[name]=x
    cutoff=packets['cutoff']; vintage={}
    base=next(r for r in frame_rows(packets['original_quarters']['balance_2017q4']['data']) if r['balance_stat_symbol']=='000063.SZ')['balance_stat_total_quity_atsopc']
    for when in ['2018-04-27','2018-05-02','2018-07-30']:
        data={t:frame_rows(cutoff[t+'_'+when]['data']) for t in ['income','balance','cashflow']}
        if when=='2018-04-27':
            assert all(not r for r in data.values());vintage[when]={'report_available':False};continue
        assert all(len(r)==1 for r in data.values())
        i,b,c=(data[t][0] for t in ['income','balance','cashflow'])
        for t,row in [('income',i),('balance',b),('cashflow',c)]:
            assert row[t+'_stat_symbol']=='000063.SZ'
            assert row[t+'_stat_report_date'][:10]<=when
        roe=i['income_stat_np_atsopc']*200/(base+b['balance_stat_total_quity_atsopc'])
        vintage[when]=dict(report_available=True,roe_average_parent_equity_pct=roe,parent_income_ytd=i['income_stat_np_atsopc'],published=b['balance_stat_report_date'][:10],operating_cash=c['cashflow_stat_net_cash_flows_from_opt_act'])
    leaked=[]
    for flag in ['False','True']:
        r=frame_rows(packets['revision']['profit_sq_20180502_'+flag]['data'])[0]
        leaked.append(r['profit_sq_roe_one_season'])
    assert all(abs(v-vintage['2018-07-30']['roe_average_parent_equity_pct'])<.0001 for v in leaked)
    assert abs(vintage['2018-05-02']['roe_average_parent_equity_pct']-4.18883116409739)<1e-10
    result=dict(status='PASS_DATA_STAGE_REPRODUCTION',exports=exports,zte_vintages=vintage,precomputed_roe_on_20180502=leaked,pilot=audit(OUT/'pilot_export.txt'),limitations=['single signal decisions only','missing alias valuation remains absent','not exact JoinQuant field equivalence','not portfolio returns','PE TTM vintage and cross-period accounting restatements require further audit'])
    (OUT/'data_stage_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(status=result['status'],packets=sum(r['packets'] for r in exports.values()),diagnostic_errors={k:len(v['diagnostic_errors']) for k,v in exports.items()},pilot=result['pilot']['status']),ensure_ascii=False))

if __name__=='__main__':run()
