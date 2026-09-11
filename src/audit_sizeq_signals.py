"""Audit yearly SQ1 bundles and independently reconstruct each consumed decision."""
import argparse,json,hashlib
from collections import Counter
from decimal import Decimal
from pathlib import Path
from import_supermind_minute_probe import decode_packets
from sizeq_signals import select,records_index,prepare_pool,SignalGap,prev
OUT=Path(__file__).resolve().parents[1]/'reports/external_size_quality/continuation'
INDEXES={'000300.SH','000905.SH','000852.SH','000001.SH','399001.SZ','399006.SZ','000016.SH','000688.SH','399330.SZ'}

def independent(snapshot):
    """Decimal implementation, not the exported selector's arithmetic."""
    records={(r['symbol'],r['table'],r['period']):r for r in snapshot['financial']}
    ranked,base,missing=prepare_pool(snapshot['pool'],snapshot['asof'])
    evidence={};selected=[];unresolved=[]
    def evaluate(s):
        period=max(p for sym,t,p in records if sym==s and t=='income')
        def get(t,p,f):return Decimal(str(records[s,t,p][f]))
        debt=get('balance',period,'liabilities')/get('balance',period,'assets')
        if debt>=Decimal('.7'):return False,{'reason':'DEBT_GE_70','period':period,'debt_ratio':float(debt)}
        ttm=get('income',period,'income')
        if not period.endswith('12-31'):
            y=str(int(period[:4])-1);ttm+=get('income',y+'-12-31','income')-get('income',y+period[4:],'income')
        if ttm<=0:return False,{'reason':'TTM_NONPOSITIVE','period':period,'ttm_income':float(ttm)}
        before=prev(period);profit=get('income',period,'income');cash=get('cashflow',period,'cash')
        if not period.endswith('03-31'):profit-=get('income',before,'income');cash-=get('cashflow',before,'cash')
        roe=profit*200/(get('balance',before,'equity')+get('balance',period,'equity'))
        reason='QUARTER_ROE_LE_5' if roe<=5 else 'QUARTER_CASH_NONPOSITIVE' if cash<=0 else 'ELIGIBLE'
        return reason=='ELIGIBLE',dict(reason=reason,period=period,ttm_income=float(ttm),roe_quarter_pct=float(roe),operating_cash_quarter=float(cash),debt_ratio=float(debt))
    for s in missing:
        try:
            eligible,evidence[s]=evaluate(s)
            if eligible:unresolved.append(s)
        except (KeyError,ValueError,ArithmeticError):unresolved.append(s)
    for cap,s in ranked:
        if len(selected)==5:break
        try:
            eligible,evidence[s]=evaluate(s)
            if eligible:selected.append(s)
        except (KeyError,ValueError,ArithmeticError):unresolved.append(s)
    return (None if unresolved else selected if len(selected)==5 else []),evidence,unresolved

def audit(path):
    text=path.read_text(encoding='utf8')
    if 'SIZEQ_SIGNALS_DONE' not in text or '日志条数超过限制' in text:raise SignalGap('incomplete yearly export')
    packets=decode_packets(text);config=packets['schedule'];days=config['all_days']
    if days!=sorted(set(days)) or len(days)!=731 or days[0]!='2017-12-29' or days[-1]!='2020-12-31':raise SignalGap('calendar coverage')
    schedule=[(days[i-1],days[i]) for i in range(1,len(days)) if (i-1)%5==0]
    schedule=schedule[:1] if config['pilot'] else [(s,t) for s,t in schedule if t.startswith(str(config['year']))]
    if 'repair_dates' in config:
        prior=json.loads((OUT/'signals_2019_audit.json').read_text(encoding='utf8'))
        if config['year']!=2019 or sorted(config['repair_dates'])!=sorted(e['asof'] for e in prior['errors']):raise SignalGap('unregistered repair schedule')
        schedule=[(s,t) for s,t in schedule if s in config['repair_dates']]
    if config['schedule']!=[list(v) for v in schedule]:raise SignalGap('schedule mismatch')
    if set(packets)!={'schedule'}|{'signal_'+s for s,t in schedule}:raise SignalGap('signal coverage')
    out=[];errors=[];warnings=Counter();total_rows=0;consumed=0
    for asof,trade in schedule:
        s=packets['signal_'+asof]
        if 'error' in s:errors.append(dict(asof=asof,error=s['error']));continue
        if s['asof']!=asof or s['trade']!=trade or asof>=trade:raise SignalGap('signal timing')
        if set(s['indexes'])!=INDEXES:raise SignalGap('index coverage')
        union=set()
        for values in s['indexes'].values():
            if len(values)!=len(set(values)):raise SignalGap('duplicate index member')
            union.update(values)
        main=lambda sym:(sym.endswith('.SZ') and sym.startswith(('000','001','002','003'))) or (sym.endswith('.SH') and sym.startswith(('600','601','603','605')))
        members=sorted(sym for sym in union if main(sym))
        if s.get('retired'):
            registered=json.loads((OUT/'retired_members.json').read_text(encoding='utf8'))
            for sym,deadline in s['retired'].items():
                if sym not in members or sym not in registered or deadline!=registered[sym]['effective'] or not registered[sym]['published']<=deadline<=asof:raise SignalGap('invalid retirement exclusion')
            members=[sym for sym in members if sym not in s['retired']]
        if [r['symbol'] for r in s['pool']]!=members:raise SignalGap('universe union')
        ranked,_,missing=prepare_pool(s['pool'],asof)
        if s['fetched']!=[sym for cap,sym in ranked[:len(s['fetched'])]]:raise SignalGap('non-prefix financial sample')
        for r in s['financial']:
            if r['symbol'] not in set(s['fetched'])|set(missing):raise SignalGap('extra financial identity')
            expected='001914.SZ' if r['symbol']=='000043.SZ' and asof<'2019-12-16' else r['symbol']
            if r['source_symbol']!=expected:raise SignalGap('unreviewed alias')
            if r['report_type'] not in ['HB','HBTZ']:raise SignalGap('unknown financial report type')
        local=select(s['pool'],s['financial'],asof)
        if local!=s['decision']:raise SignalGap('platform/local selector mismatch')
        targets,evidence,unknown=independent(s)
        if targets!=local['targets']:raise SignalGap('independent targets differ')
        for sym,values in evidence.items():
            actual=local['tested'][sym]
            for key,value in values.items():
                if isinstance(value,(int,float)):
                    if abs(actual[key]-value)>max(1e-5,abs(value)*1e-10):raise SignalGap('independent metric differs')
                elif actual[key]!=value:raise SignalGap('independent reason differs')
        used=set(local['tested'])
        for r in s['financial']:
            if r['symbol'] in used:
                if r['report_type']=='HBTZ':warnings['adjusted_report_rows']+=1
                if r.get('change_id') not in (0,None):warnings['version_change_rows']+=1
                if r.get('other_equity_instrument') not in (0,None):warnings['other_equity_rows']+=1
        consumed+=len(used);total_rows+=len(s['financial'])
        if local['errors']:errors.append(dict(asof=asof,errors=local['errors']))
        out.append(dict(asof=asof,trade=trade,status=local['status'],members=len(members),financial_rows=len(s['financial']),consumed_decisions=len(used),targets=targets,missing_float_shares=missing,errors=local['errors']))
    result=dict(status='PASS_SIGNAL_RECONSTRUCTION' if not errors else 'BLOCKED_SIGNALS',year=config['year'],pilot=config['pilot'],source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),expected_signals=len(schedule),audited_signals=len(out),financial_rows=total_rows,independently_checked_decisions=consumed,accounting_flags=dict(warnings),signals=out,errors=errors,performance_completed=False)
    path.with_name(path.stem.replace('_export','')+'_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k not in ['signals']},ensure_ascii=False))
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('path');args=parser.parse_args();audit(Path(args.path))
