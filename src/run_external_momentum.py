"""Audit execution exports, run both costs, preserve missing-data status."""
import json,math,hashlib,copy
from external_momentum import OUT
from external_momentum_replay import replay,MissingData
from import_supermind_minute_probe import decode_packets
from external_momentum_corporate import build as build_events

def frame_rows(data):
    fields=list(data)
    if not fields:raise ValueError('empty schema')
    stamps=set(data[fields[0]])
    if any(set(data[k])!=stamps for k in fields):raise ValueError('unequal frame columns')
    return {t:{k:data[k][t] for k in fields} for t in sorted(stamps)}

def inputs():
    requests=json.loads((OUT/'data_requests.json').read_text(encoding='utf8'));packets={}
    paths=sorted(OUT.glob('data_export*.txt'))
    for path in paths:
        raw=path.read_text(encoding='utf8')
        if 'EXTMOM_DATA_DONE' not in raw or '日志条数超过限制' in raw:raise ValueError('execution export incomplete')
        for key,p in decode_packets(raw).items():
            if key in packets and p!=packets[key] and not (packets[key]['status']=='ERROR' and p['status']=='RETURNED'):raise ValueError('source conflict '+key)
            packets[key]=p
    symbols=requests['symbols'];expected={'daily_'+s for s in symbols}|{'dividend_'+s for s in symbols}|{'details_'+s for s in symbols}|{'minute_'+d for d in requests['dates']}
    if not expected<=set(packets):raise ValueError('missing requested packets')
    daily={};minutes={};invalid_days=[]
    for s in symbols:
        p=packets['daily_'+s]
        if p['status']!='RETURNED':raise ValueError(str(p))
        daily[s]={}
        for stamp,r in frame_rows(p['data']).items():
            day=stamp[:10]
            if any(v is None or not isinstance(v,(int,float)) or not math.isfinite(v) for v in r.values()):
                invalid_days.append(dict(symbol=s,date=day));continue
            if any(r[k]<=0 for k in ('open','high','low','close','factor')):raise ValueError('invalid daily price '+s+' '+day)
            if not r['low']<=min(r['open'],r['close'])<=max(r['open'],r['close'])<=r['high']:raise ValueError('daily OHLC')
            if r['is_st'] not in (0,1) or r['is_paused'] not in (0,1):raise ValueError('daily state')
            daily[s][day]=r
    for key,p in packets.items():
        if not key.startswith('minute_'):continue
        if p['status']!='RETURNED':raise ValueError(str(p))
        day=p['date']
        if set(p['data'])!=set(symbols):raise ValueError('minute symbol coverage')
        for s,f in p['data'].items():
            if not f and (day not in daily[s] or daily[s][day]['is_paused']):continue
            rows=frame_rows(f)
            if not rows and (day not in daily[s] or daily[s][day]['is_paused']):continue
            if len(rows)!=1:raise ValueError('minute count')
            stamp,r=next(iter(rows.items()))
            if stamp[:16]!=day+'T09:35':raise ValueError('minute stamp')
            if any(v is None or not math.isfinite(v) for v in r.values()):
                # A not-yet-listed security is allowed in the retrieval union, not tradable.
                if day not in daily[s]:continue
                raise ValueError('missing minute values '+s+' '+day)
            if not 0<r['low']<=min(r['open'],r['close'])<=max(r['open'],r['close'])<=r['high']:raise ValueError('minute OHLC '+s+' '+day)
            d=daily[s].get(day)
            if d is None:continue
            if r['low']<d['low']-.011 or r['high']>d['high']+.011 or r['volume']>d['volume']+1 or r['turnover']>d['turnover']+2:raise ValueError('minute daily containment '+s+' '+day)
            minutes[s+'|'+day]=r
    # The zero dividend row is a rights issue, confirmed independently; do not erase its economic event.
    adjusted=copy.deepcopy(packets)
    extra=[]
    s='000563.SZ';stamp='2018-07-25T00:00:00.000Z'
    if s in symbols and stamp in adjusted['dividend_'+s]['data']['symbol']:
        d=adjusted['dividend_'+s]['data']
        if any(d[k][stamp]!=0 for k in ('cash_dividends','give_stock','transfer_stock')):raise ValueError('unexpected rights source')
        if not (OUT/'000563_bonus_source.txt').exists():raise ValueError('rights issue evidence absent')
        evidence=(OUT/'000563_bonus_source.txt').read_text(encoding='utf8')
        if '2018-07-16' not in evidence or '2018-07-25' not in evidence or '配股' not in evidence:raise ValueError('rights source mismatch')
        for v in d.values():del v[stamp]
        extra.append(dict(symbol=s,record_date='2018-07-16',ex_date='2018-07-25',kind='rights_issue',source='https://vip.stock.finance.sina.com.cn/corp/go.php/vISSUE_ShareBonus/stockid/000563.phtml'))
    events,unsupported=build_events(adjusted,symbols);unsupported+=extra
    audit=dict(status='PASS_EXTMOM_EXECUTION_INPUTS',symbols=len(symbols),minutes=len(minutes),invalid_daily_not_imputed=invalid_days,cash_events=len(events),unsupported_events=unsupported,source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    (OUT/'input_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf8')
    (OUT/'corporate_events.json').write_text(json.dumps(dict(events=events,unsupported=unsupported),ensure_ascii=False,indent=2),encoding='utf8')
    return daily,minutes,events,unsupported

def main():
    screen=json.loads((OUT/'screen.json').read_text(encoding='utf8'))
    if screen['months']!=36 or screen['days']!=730:raise ValueError('incomplete screen')
    data=inputs();status=[]
    for cost in (1.,1.5):
        try:
            r=replay(screen,*data,cost)
            (OUT/f'M0_cost{cost}.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf8')
            status.append(dict(cost=cost,status=r['status'],metrics=r['metrics'],final=r['final'],fills=len(r['fills'])))
        except MissingData as exc:status.append(dict(cost=cost,status='MISSING_DATA',reason=str(exc)))
    (OUT/'run_status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(status,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
