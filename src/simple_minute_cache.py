"""按需分钟缓存：原始包、日线对账、持仓缺口显式返回。"""
import argparse,hashlib,inspect,json,math
from pathlib import Path
from statistics import mean
from import_supermind_minute_probe import decode_packets
from research_portfolio import session_minutes,run_bundle
from s2_strategy_rules import Policy
from simple_corporate_events import build_events
from simple_minute_aliases import apply_aliases
import simple_strategy_rules as rules
ROOT=Path(__file__).resolve().parents[1]

def first_entry_dates(days):
    first={}
    for i in range(1,len(days)):
        prior=days[i-1]
        if prior['route']!='trend_breakout':continue
        for row in prior['candidates']:
            if rules.needs_minutes(row,prior['route']):first.setdefault(row['symbol'],days[i]['date'])
    return first

class MissingMinutes(ValueError):
    def __init__(self,requests):
        self.requests=requests;super().__init__('缺少持仓或候选分钟：'+str(requests))

def rows(packet):
    dates=packet['dates'];d=packet['data']
    if dates!=sorted(set(dates)) or any(len(v)!=len(dates) for v in d.values()):raise ValueError('行日期重复或字段长度不一')
    return [dict(datetime=t,**{k:v[i] for k,v in d.items()}) for i,t in enumerate(dates)]

class Cache:
    def __init__(self,packets):
        self.daily={};self.minutes={};self.checks=[]
        for k,p in packets.items():
            if k.startswith('daily_'):
                self.daily[p['symbol']]={r['datetime'][:10]:r for r in rows(p)}
        for k,p in packets.items():
            if not k.startswith('minute_'):continue
            s,day=p['symbol'],p['date'];data=rows(p);reference=self.daily[s][day]
            if [r['datetime'] for r in data]!=session_minutes(day):raise ValueError('不完整分钟：'+k)
            for r in data:
                for f in ('is_st','is_paused','high_limit','low_limit','factor'):r[f]=reference[f]
                if any(r[f] not in (0,1) for f in ('is_st','is_paused')):raise ValueError('未知历史状态')
                for f in ('is_st','is_paused'):r[f]=bool(r[f])
                if any(v is None or not math.isfinite(v) for f,v in r.items() if f!='datetime'):raise ValueError('分钟无效字段')
                if not 0<r['low']<=min(r['open'],r['close'])<=max(r['open'],r['close'])<=r['high']:raise ValueError('分钟OHLC错误')
                if r['volume']<0 or r['turnover']<0:raise ValueError('分钟量额为负')
            vd=sum(r['volume'] for r in data)-reference['volume'];ad=sum(r['turnover'] for r in data)-reference['turnover']
            if abs(vd)>1 or abs(ad)>max(2,reference['turnover']*1e-7) or abs(data[-1]['close']-reference['close'])>.011:
                raise ValueError('分钟日线量额不一致：'+str((s,day,vd,ad)))
            self.minutes[s,day]=data;self.checks.append(dict(symbol=s,date=day,volume_delta=vd,amount_delta=ad))

    def load(self,day,symbols):
        missing=[dict(symbol=s,date=day) for s in sorted(symbols) if (s,day) not in self.minutes]
        if missing:raise MissingMinutes(missing)
        return [dict(datetime=t,bars={s:dict(self.minutes[s,day][i]) for s in symbols}) for i,t in enumerate(session_minutes(day))]

    def closing(self,day):
        result={}
        for s,history in self.daily.items():
            selected=[v for d,v in sorted(history.items()) if d<=day]
            if len(selected)<21 or selected[-1]['datetime'][:10]!=day:continue
            w=selected[-21:]
            if any(r[k] is None or not math.isfinite(r[k]) or r[k]<=0 for r in w for k in ('close','high','low','factor')):continue
            base=w[-1]['factor'];c=[r['close']*r['factor']/base for r in w];h=[r['high']*r['factor']/base for r in w];l=[r['low']*r['factor']/base for r in w]
            tr=[max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(1,21)]
            result[s]=dict(factor=base,ma10_raw=mean(c[-10:]),atr20_raw=mean(tr),industry_weak=None)
        return dict(date=day,stocks=result)

    def closing_many(self,days,path):
        signature=hashlib.sha256(json.dumps(self.daily,sort_keys=True,separators=(',',':')).encode('utf8')+inspect.getsource(type(self).closing).encode('utf8')).hexdigest()
        if path.exists():
            stored=json.loads(path.read_text(encoding='utf8'))
            if stored.get('input_sha256')==signature and stored.get('dates')==days:
                payload=json.dumps(stored['values'],sort_keys=True,separators=(',',':')).encode('utf8')
                if hashlib.sha256(payload).hexdigest()!=stored['payload_sha256']:raise ValueError('收盘特征缓存损坏')
                return stored['values']
        values=[self.closing(day) for day in days]
        payload=json.dumps(values,sort_keys=True,separators=(',',':')).encode('utf8')
        path.write_text(json.dumps(dict(input_sha256=signature,dates=days,values=values,payload_sha256=hashlib.sha256(payload).hexdigest()),ensure_ascii=False,separators=(',',':')),encoding='utf8')
        return values

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--year',type=int);args=parser.parse_args()
    out=ROOT/'reports/simple_research'
    if args.year:out=out/str(args.year)
    screen=json.loads((out/('screen.json' if args.year else 'quarter_screen.json')).read_text(encoding='utf8'))
    if screen['status'] not in ('PASS_TECH1_QUARTER_SCREEN','PASS_TECH1_HISTORY_SCREEN'):raise ValueError('日线筛选未通过')
    packets={}
    for f in sorted(out.glob('minute_export*.txt')):
        raw=f.read_text(encoding='utf8')
        if 'TECH1_ENTRY_MINUTE_EXPORT_DONE' not in raw:raise ValueError('分钟导出未完成：'+f.name)
        for k,p in decode_packets(raw).items():
            if k in packets and p!=packets[k]:raise ValueError('缓存包冲突')
            packets[k]=p
    cache=Cache(apply_aliases(packets,out));calendar=[d['date'] for d in screen['days']]
    corporate=out/'corporate_export.txt'
    if corporate.exists():
        corporate_text=corporate.read_text(encoding='utf8')
        if 'TECH1_CORPORATE_EXPORT_DONE' not in corporate_text:raise ValueError('公司行动导出未完成')
        cp=decode_packets(corporate_text);cash=[];unsupported=[];unresolved=[];first=first_entry_dates(screen['days'])
        for symbol in sorted(cache.daily):
            try:
                events,other=build_events(cp,[symbol],first.get(symbol,calendar[1]));cash.extend(events);unsupported.extend(other)
            except ValueError as exc:unresolved.append(dict(symbol=symbol,error=str(exc)))
    else:cash,unsupported,unresolved=None,[],[]
    closes=cache.closing_many(calendar[1:],out/'close_features_cache.json')
    bundle=dict(research_version=rules.VERSION,source_kind='HISTORICAL_QUARTER_SCREEN_PLUS_VERIFIED_MINUTES',initial_cash=30000.,calendar=calendar,record_minute_curve=True,
                days=[dict(date=calendar[i],previous_close=dict(date=calendar[i-1],benchmark=screen['days'][i-1]['benchmark'],stocks=screen['days'][i-1]['candidates']),close_features=closes[i-1]) for i in range(1,len(calendar))])
    if cash is not None:bundle['corporate_events']=cash
    bundle['unresolved_corporate_symbols']=sorted({r['symbol'] for r in unresolved})
    bundle['unsupported_corporate_events']=unsupported
    (out/'corporate_events.json').write_text(json.dumps(dict(cash=cash,unsupported=unsupported,unresolved=unresolved),ensure_ascii=False,indent=2),encoding='utf8')
    missing=[]
    for cost in (1.,1.5):
        try:
            result=run_bundle(bundle,Policy(cost_multiplier=cost),rules=rules,minute_loader=cache.load)
            result['scope']=(str(args.year)+' initial annual research; not a concatenated multiyear result') if args.year else '2019Q2 engineering validation; not multiyear or prospective acceptance'
            (out/f'{"annual" if args.year else "quarter"}_cost{cost}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
            print(dict(cost=cost,status='ANNUAL_REPLAY_COMPLETED' if args.year else 'QUARTER_REPLAY_COMPLETED',fills=len(result['fills']),final=result['final']))
        except MissingMinutes as exc:
            missing.extend(exc.requests);print(dict(cost=cost,missing=exc.requests))
    unique=[dict(symbol=s,date=d) for s,d in sorted({(r['symbol'],r['date']) for r in missing})]
    (out/'missing_minutes.json').write_text(json.dumps(unique,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'minute_audit.json').write_text(json.dumps(dict(days=len(cache.checks),rows=240*len(cache.checks),checks=cache.checks),ensure_ascii=False,indent=2),encoding='utf8')

if __name__=='__main__':main()
