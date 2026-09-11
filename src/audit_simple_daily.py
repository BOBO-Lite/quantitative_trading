"""核验TECH1.0历史全池分区、候选原始窗口与本地规则，生成按需分钟清单。"""
import hashlib,json,math
from pathlib import Path
from statistics import mean
import pandas as pd
from import_supermind_minute_probe import decode_packets
import simple_strategy_rules as rules
ROOT=Path(__file__).resolve().parents[1]

def reconstruct(candidate,benchmark_dates):
    w=candidate['audit_window'];d=w['data'];dates=w['dates'];day=candidate['date']
    if dates!=[x for x in benchmark_dates if x<=day][-61:] or len(dates)!=61:
        raise ValueError('候选窗口缺交易日或含未来日期')
    fields=('close','high','low','volume','turnover','factor','is_st','is_paused')
    if any(len(d[k])!=61 or any(not math.isfinite(v) for v in d[k]) for k in fields):
        raise ValueError('候选字段缺失')
    if any(min(d[k])<=0 for k in ('close','high','low','factor')) or min(d['volume']+d['turnover'])<0:
        raise ValueError('价量因子不合法')
    if any(d['low'][i]>d['close'][i] or d['high'][i]<d['close'][i] for i in range(61)):
        raise ValueError('最高最低与收盘冲突')
    if any(v not in (0,1) for v in d['is_st']+d['is_paused']):raise ValueError('状态不是明确布尔值')
    f=d['factor'];base=f[-1]
    c=[v*x/base for v,x in zip(d['close'],f)];h=[v*x/base for v,x in zip(d['high'],f)];l=[v*x/base for v,x in zip(d['low'],f)]
    tr=[max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(41,61)]
    prior_vol=mean(d['volume'][-21:-1])
    if prior_vol<=0:raise ValueError('量比不可计算')
    result=dict(symbol=candidate['symbol'],date=day,market_state_verified=True,
                listing_bars=candidate['listing_bars'],is_st=bool(d['is_st'][-1]),is_paused=bool(d['is_paused'][-1]),
                amount20=mean(d['turnover'][-21:-1]),close=c[-1],ma20=mean(c[-20:]),ma60=mean(c[-60:]),
                prior_breakout_close=max(c[-21:-1]),volume_ratio=d['volume'][-1]/prior_vol,
                atr20_raw=mean(tr),raw_close=c[-1],raw_high=h[-1],factor=base,target_ma20_raw=mean(c[-20:]))
    for k,v in result.items():
        if isinstance(v,(float,int)) and not isinstance(v,bool):
            if abs(v-candidate[k])>max(1e-7,abs(v)*1e-10):raise ValueError('候选重算不一致：'+k)
        elif candidate[k]!=v:raise ValueError('候选身份或状态不一致')
    if not rules.select_signal(result,'trend_breakout'):raise ValueError('导出候选不符合本地规则')
    return result

def audit(packets,start='2019-03-29',end='2019-06-28'):
    benchmark=packets['benchmark']['data']['close'];dates=sorted(t[:10] for t in benchmark)
    bm={t[:10]:v for t,v in benchmark.items()}
    expected_days=[d for d in dates if start<=d<=end]
    if not expected_days:raise ValueError('历史区间为空')
    if set(packets)!={'benchmark'}|{'tech1_'+d for d in expected_days}:raise ValueError('季度日期或包集合不完整')
    reports=[];requests=[];errors=[]
    for day in expected_days:
        p=packets['tech1_'+day];expected=p['expected_symbols']
        if p['date']!=day or len(expected)!=len(set(expected)):raise ValueError('股票池或日期重复')
        partition=[r['symbol'] for r in p['candidates']]+[s for group in p['excluded'].values() for s in group]+[e[0] for e in p['errors']]
        if len(partition)!=len(set(partition)) or set(partition)!=set(expected):raise ValueError('股票池分区覆盖错误')
        if set(p['excluded'])-{'SHORT_HISTORY','ST','PAUSED','LOW_LIQUIDITY','NO_TECH_SIGNAL','MARKET_CLOSED','RISK_DISTANCE'}:raise ValueError('未登记的排除理由')
        closes=[bm[d] for d in dates if d<=day]
        if len(closes)<120:raise ValueError('基准预热不足')
        values=dict(close=closes[-1],ma20=mean(closes[-20:]),ma60=mean(closes[-60:]))
        if any(abs(values[k]-p['benchmark'][k])>1e-7 for k in values):raise ValueError('基准重算不符')
        route=rules.research_regime(**values)
        if 'MARKET_CLOSED' in p['excluded'] and (route!='defensive_cash' or p['candidates'] or set(p['excluded']['MARKET_CLOSED'])!=set(expected)):
            raise ValueError('大盘关闭的排除理由不成立')
        candidates=[reconstruct(r,dates) for r in p['candidates']]
        errors.extend(dict(date=day,symbol=s,reason=e) for s,e in p['errors'])
        report=dict(date=day,universe_count=len(expected),route=route,candidates=candidates,
                    excluded_counts={k:len(v) for k,v in p['excluded'].items()},errors=p['errors'],benchmark=p['benchmark'])
        reports.append(report)
        i=expected_days.index(day)
        if route=='trend_breakout' and i+1<len(expected_days):
            for row in candidates:
                cap=rules.entry_cap(row,route);dist=rules.stop_distance(row,cap)
                if dist<=.06:
                    requests.append(dict(signal_date=day,entry_date=expected_days[i+1],symbol=row['symbol'],planned_cap=cap,stop_distance=dist))
    return dict(research_version=rules.VERSION,status='BLOCKED_DAILY_SOURCE_ERRORS' if errors else 'PASS_TECH1_QUARTER_SCREEN',
                days=reports,minute_requests=requests,errors=errors,formal_strategy_validated=False,
                source_scope='source code enumerates historical universe; exported candidates independently recomputed; exclusions preserved by symbol, not individually recomputed')

def main():
    out=ROOT/'reports/simple_research';raw=out/'quarter_daily_export.txt'
    text=raw.read_text(encoding='utf8')
    if 'TECH1_Q2_DAILY_EXPORT_DONE' not in text:raise ValueError('导出未完成')
    packets=decode_packets(text);result=audit(packets);result['log_sha256']=hashlib.sha256(raw.read_bytes()).hexdigest()
    reference=ROOT/'reports/s2_research/long_history/research_benchmark.csv'
    full=pd.read_csv(reference)
    expected=full[(full.date>='2019-03-29')&(full.date<='2019-06-28')].date.tolist()
    if [d['date'] for d in result['days']]!=expected:raise ValueError('独立长期基准显示季度存在交易日缺口')
    universe=ROOT/'runtime/industry_history/monthly_universe.csv.gz'
    meta=pd.read_csv(universe,dtype=str).drop_duplicates('symbol').set_index('symbol')['listed_date'].to_dict()
    calendar=sorted(t[:10] for t in packets['benchmark']['data']['close']);short=0
    for k,p in packets.items():
        if not k.startswith('tech1_'):continue
        for symbol in p['excluded'].get('SHORT_HISTORY',[]):
            short+=1
            if symbol not in meta or sum(meta[symbol]<=d<=p['date'] for d in calendar)>=120:
                raise ValueError('上市不足120日的排除理由缺少独立证据：'+symbol)
    result['short_listing_rows_verified']=short
    result['reference_sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (reference,universe)}
    (out/'quarter_screen.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(dict(status=result['status'],days=len(result['days']),candidates=sum(len(d['candidates']) for d in result['days']),minute_requests=len(result['minute_requests']),errors=result['errors'][:20]))

if __name__=='__main__':main()
