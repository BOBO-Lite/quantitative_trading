"""隔离AKShare依赖的收盘缺口桥接；只补小缺口，保留正式管道覆盖门禁。"""
from datetime import datetime
import json,subprocess
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]


def adapt_probe(payload,symbols,target,metadata):
    day=pd.Timestamp(target).strftime('%Y-%m-%d'); rows=[]; seen=set()
    if payload['target_date']!=day or payload['provider']!='tencent' or payload['akshare_version']!='1.18.94':
        raise ValueError('行情桥接日期、来源或版本错误')
    for case in payload['cases']:
        s=case['symbol']
        if s not in symbols or s in seen:raise ValueError('返回股票越界或重复')
        seen.add(s)
        if case['status']!='PASS_DATED_PRICE_ROW':continue
        r=case['row']
        if r['symbol']!=s or r['date']!=day or r['volume']<=0:
            raise ValueError('零量不能推断停牌，或量价身份错误')
        security=metadata[s]
        rows.append(dict(date=pd.Timestamp(day),symbol=s,**{k:r[k] for k in ('open','high','low','close','volume','amount')},paused=False,st='ST' in str(security.get('name') or '').upper(),listing_days=max((pd.Timestamp(day)-pd.Timestamp(security['listed_date'])).days,0)))
    return pd.DataFrame(rows)


def fetch_missing(symbols,target,metadata,output_root):
    current=datetime.now(ZoneInfo('Asia/Shanghai'))
    interpreter=ROOT/'.venv-framework/Scripts/python.exe'
    detail=dict(provider='akshare_tencent_daily',requested=len(symbols),accepted=0)
    if not symbols:return pd.DataFrame(),detail
    if len(symbols)>10 or pd.Timestamp(target).date()!=current.date() or current.hour<15 or not interpreter.exists():
        detail['status']='SKIPPED_SCOPE_OR_ENVIRONMENT';return pd.DataFrame(),detail
    output=Path(output_root)/current.strftime('%Y%m%dT%H%M%S%f')
    args=[str(interpreter),'-X','utf8',str(ROOT/'src/probe_akshare_daily.py'),'--date',pd.Timestamp(target).strftime('%Y-%m-%d'),'--provider','tencent','--symbols',*symbols,'--output',str(output)]
    try:
        p=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',timeout=40*len(symbols)+20)
        if p.returncode:raise RuntimeError(p.stderr[-1200:])
        payload=json.loads((output/'probe.json').read_text(encoding='utf-8'))
        frame=adapt_probe(payload,symbols,target,metadata)
        detail.update(status=payload['status'],accepted=len(frame),evidence=str(output/'probe.json'))
        return frame,detail
    except Exception as exc:
        detail.update(status='BLOCKED',error=str(exc));return pd.DataFrame(),detail
