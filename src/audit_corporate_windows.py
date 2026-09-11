"""核验分红窗口原始分钟与日线，重建同日固定元数据。"""
import hashlib,json,math
from pathlib import Path
from import_supermind_minute_probe import decode_packets
from research_portfolio import session_minutes
ROOT=Path(__file__).resolve().parents[1]

def build(packets,events):
    cases=[]
    for key,p in sorted(packets.items()):
        if not key.endswith('_1m'):continue
        if p['status']!='RETURNED':raise ValueError(p)
        d=packets[key[:-2]+'1d']['data']; m=p['data']
        days=sorted(t[:10] for t in d['close']); rows=[]; checks=[]
        for day in days:
            stamps=sorted(t for t in m['close'] if t.startswith(day))
            if [t[:19] for t in stamps]!=session_minutes(day):raise ValueError('不完整分钟覆盖')
            daily_stamp=next(t for t in d['close'] if t.startswith(day))
            reference={f:v[daily_stamp] for f,v in d.items()}
            for stamp in stamps:
                row={f:v[stamp] for f,v in m.items()}
                for f in ('is_st','is_paused','high_limit','low_limit','factor'):row[f]=reference[f]
                for f in ('is_st','is_paused'):
                    if row[f] not in (0,1,True,False):raise ValueError('缺历史状态')
                    row[f]=bool(row[f])
                if any(not math.isfinite(v) for v in row.values()):raise ValueError('非有限行情')
                if not 0<row['low']<=min(row['open'],row['close'])<=max(row['open'],row['close'])<=row['high']:raise ValueError('OHLC错误')
                if row['volume']<0 or row['turnover']<0 or row['factor']<=0:raise ValueError('量额因子错误')
                rows.append(dict(row,symbol=p['symbol'],datetime=stamp[:19]))
            same=[r for r in rows if r['datetime'].startswith(day)]
            vd=sum(r['volume'] for r in same)-reference['volume']; ad=sum(r['turnover'] for r in same)-reference['turnover']
            if abs(vd)>1e-6 or abs(ad)>2 or abs(same[-1]['close']-reference['close'])>.011:raise ValueError('日线核账失败')
            checks.append(dict(date=day,volume_delta=vd,amount_delta=ad))
        actions=[e for e in events if e['symbol']==p['symbol'] and e['record_date'] in days and e['ex_date'] in days]
        if len(actions)!=1:raise ValueError('需恰好一个已核验现金分红事件')
        cases.append(dict(status='PASS_CORPORATE_WINDOW_DATA',symbol=p['symbol'],dates=days,rows=rows,events=actions,checks=checks,daily=[dict({f:v[t] for f,v in d.items()},date=t[:10]) for t in sorted(d['close'])]))
    if len(cases)!=4:raise ValueError('分红窗口不完整')
    return cases

def main():
    out=ROOT/'reports/s2_research/corporate_actions'; raw=(out/'platform_export.txt').read_bytes()
    events=json.loads((ROOT/'reports/s2_research/data_feasibility/platform_capability_audit.json').read_text(encoding='utf-8'))['dividend_events']
    cases=build(decode_packets(raw.decode('utf-8')),events)
    payload=dict(status='PASS_FOUR_CORPORATE_WINDOWS',log_sha256=hashlib.sha256(raw).hexdigest(),cases=cases,formal_strategy_validated=False)
    (out/'verified_windows.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print([(c['symbol'],c['dates'],len(c['rows'])) for c in cases])
if __name__=='__main__':main()
