"""ETF专用数据审计：原始量价、分红、复权变化及固定执行分钟。"""
import json, math, re
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path
from statistics import mean
from bs4 import BeautifulSoup
from import_supermind_minute_probe import decode_packets
from research_portfolio import session_minutes

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/etf_research'
SYMBOLS=('510300.SH','510500.SH')

def rows(data):
    keys=list(data)
    if not keys: return []
    stamps=sorted(data[keys[0]])
    if any(set(v)!=set(stamps) for v in data.values()):raise ValueError('字段时间不齐')
    return [dict(date=t[:10],datetime=t[:19],**{k:data[k][t] for k in keys}) for t in stamps]

def corporate(packets,end='2022-12-31',symbols=SYMBOLS,corporate_dir=OUT):
    events=[]
    for symbol in symbols:
        soup=BeautifulSoup((corporate_dir/f'dividend_{symbol[:6]}.html').read_text(encoding='utf8'),'html.parser')
        tables=[t for t in soup.find_all('table') if '每10份分红' in t.get_text()]
        if len(tables)!=1:raise ValueError('分红表不唯一')
        for tr in tables[0].select('tr'):
            cells=[c.get_text(strip=True) for c in tr.select('td')]
            if len(cells)!=5 or not cells[0].endswith('年'):continue
            _,record,ex,amount,pay=cells
            if not '2017-01-01'<=ex<=end:continue
            m=re.fullmatch(r'每10份派现金([0-9.]+)元',amount)
            if not m or not record<ex<=pay:raise ValueError('未知分红格式/日期')
            events.append(dict(symbol=symbol,record_date=record,ex_date=ex,pay_date=pay,cash=float(m[1])/10,kind='cash'))
    # 完整比例来自平台，2022-08-26登记/拆分日由另一来源确认；未实现账户份额处理。
    if '510500.SH' in symbols:events.append(dict(symbol='510500.SH',record_date='2022-08-26',ex_date='2022-08-29',kind='unsupported_split',ratio=1.1453900912))
    for symbol in symbols:
        provider=rows(packets['etf_dividend_'+symbol]['data'])
        expected=[e for e in events if e['symbol']==symbol]
        if len(provider)!=len(expected):raise ValueError('公司行动来源覆盖不一致')
        for r in provider:
            match=[e for e in expected if e['ex_date']==r['date']]
            if len(match)!=1:raise ValueError('公司行动日期不一致')
            e=match[0]
            if e['kind']=='cash':
                if abs(r['cash_dividends']-e['cash'])>1e-9 or r['give_stock'] or r['transfer_stock']:raise ValueError('现金分红冲突')
            elif abs(1+r['transfer_stock']-e['ratio'])>1e-10 or r['cash_dividends'] or r['give_stock']:raise ValueError('拆分比例冲突')
    return sorted(events,key=lambda e:(e['ex_date'],e['symbol']))

def features(history):
    if len(history)<120:return None
    w=history[-61:];base=w[-1]['adjustment'];close=[r['close']*r['adjustment']/base for r in w]
    highs=[r['high']*r['adjustment']/base for r in w];lows=[r['low']*r['adjustment']/base for r in w]
    atr=mean(max(highs[i]-lows[i],abs(highs[i]-close[i-1]),abs(lows[i]-close[i-1])) for i in range(41,61))
    return dict(date=w[-1]['date'],close=close[-1],ma20=mean(close[-20:]),ma60=mean(close[-60:]),atr=atr,amount20=mean(r['turnover'] for r in history[-21:-1]),adjustment=base)

def build(include_minutes=True,out=OUT,symbols=SYMBOLS,corporate_dir=OUT):
    packets=decode_packets((out/'probe_export.txt').read_text(encoding='utf8'))
    if any(v.get('status')=='ERROR' for v in packets.values()):raise ValueError('探针含错误')
    calendar=[r['date'] for r in rows(packets['etf_calendar']['data'])]
    events=corporate(packets,calendar[-1],symbols,corporate_dir);daily={};checks=[]
    for symbol in symbols:
        history=rows(packets['etf_daily_'+symbol]['data'])
        if [r['date'] for r in history]!=calendar:raise ValueError('基金交易日缺失')
        base=history[0]['factor'];adjustment=1.
        for i,r in enumerate(history):
            if any(not isinstance(r[k],(int,float)) or not math.isfinite(r[k]) for k in ('open','high','low','close','volume','turnover','factor','is_paused','high_limit','low_limit')):raise ValueError('无效行情数值')
            if not 0<r['low']<=min(r['open'],r['close'])<=max(r['open'],r['close'])<=r['high'] or r['volume']<0 or r['turnover']<0 or r['is_paused'] not in (0,1):raise ValueError('量价/状态错误')
            low_limit=float(Decimal(str(r['low_limit'])).quantize(Decimal('.001'),rounding=ROUND_HALF_UP))
            high_limit=float(Decimal(str(r['high_limit'])).quantize(Decimal('.001'),rounding=ROUND_HALF_UP))
            if not 0<low_limit<=r['low']<=r['high']<=high_limit:raise ValueError('涨跌停区间错误')
            for e in events:
                if e['symbol']==symbol and e['ex_date']==r['date']:
                    adjustment*=history[i-1]['close']/(history[i-1]['close']-e['cash']) if e['kind']=='cash' else e['ratio']
            # 平台因子四位小数有舍入漂移，指标统一以核验事件重建因子。
            if abs(r['factor']/base/adjustment-1)>.0008:raise ValueError('未解释的复权变化')
            r['adjustment']=adjustment
        daily[symbol]={r['date']:r for r in history}
        checks.append(dict(symbol=symbol,days=len(history),factor_max_relative_error=max(abs(r['factor']/base/r['adjustment']-1) for r in history)))
    minutes={};warnings=[]
    if include_minutes:
        mp=decode_packets((out/'minute_export.txt').read_text(encoding='utf8'))
        expected={f'etf_minutes_{s}_{y}' for s in symbols for y in range(2018,int(calendar[-1][:4])+1)}
        if set(mp)!=expected:raise ValueError('分钟请求集合不完整')
        for symbol in symbols:
            all_days=[]
            for year in range(2018,int(calendar[-1][:4])+1):
                p=mp[f'etf_minutes_{symbol}_{year}']
                if p['symbol']!=symbol or p['year']!=year:raise ValueError('分钟身份不符')
                for r in p['days']:
                    day=r['date'];all_days.append(day);d=daily[symbol][day]
                    expected_times=[x[11:16] for x in session_minutes(day)]
                    if r['count']!=240 or r['times']!=expected_times:raise ValueError('分钟覆盖不完整')
                    for k in ('open','high','low','close'):
                        if abs(r[k]-d[k])>.00101:
                            # 仅放行已由独立新浪日线确认的单日极值差；不修改原始分钟。
                            proof=json.loads((OUT/'sina_daily_extrema_check.json').read_text(encoding='utf8'))
                            reference=proof['rows'][0]
                            verified=(symbol=='510500.SH' and day=='2022-12-05' and reference['date']==day
                                      and k in ('high','low') and abs(reference[k]-d[k])<1e-8
                                      and d['low']<=r['low']<=r['high']<=d['high'] and abs(r[k]-d[k])<=.00301)
                            if not verified:raise ValueError('分钟日线价格不一致：'+str((symbol,day,k,r[k],d[k])))
                            warnings.append(dict(symbol=symbol,date=day,field=k,minute_aggregate=r[k],daily=d[k],resolution='独立日线确认日极值；固定09:35原始分钟未改，不能宣称日内极值完全一致'))
                    if abs(r['volume']-d['volume'])>1 or abs(r['turnover']-d['turnover'])>max(2,d['turnover']*1e-7):raise ValueError('分钟日线量额不一致')
                    a=rows(r['minute'])
                    if [m['datetime'] for m in a]!=[day+'T'+t+':00' for t in ('09:34','09:35','15:00')]:raise ValueError('执行/核账分钟缺失')
                    for m in a:
                        if any(not isinstance(m[k],(int,float)) or not math.isfinite(m[k]) or m[k]<0 for k in ('open','high','low','close','volume','turnover')) or not 0<m['low']<=min(m['open'],m['close'])<=max(m['open'],m['close'])<=m['high']:raise ValueError('执行/核账分钟异常')
                        if m['low']<d['low']-.00101 or m['high']>d['high']+.00101:raise ValueError('执行分钟超出日线范围')
                    if abs(a[-1]['close']-d['close'])>.00101:raise ValueError('收盘核账分钟不一致')
                    m=a[1]
                    minutes[symbol,day]=dict(m,validation_bars=a)
            if all_days!=[d for d in calendar if d>='2018-01-01']:raise ValueError('分钟日期集合不符')
    audit=dict(status='PASS_WITH_DOCUMENTED_EXTREMA_EXCEPTION' if warnings else 'PASS',warnings=warnings,daily_checks=checks,events=events,minute_stock_days=len(minutes),minute_rows_aggregated=len(minutes)*240,scope='固定两ETF历史数据及09:35分钟，不是绩效')
    (out/'data_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf8')
    return calendar,daily,events,minutes

if __name__=='__main__':
    import sys
    build('--daily-only' not in sys.argv)
    print((OUT/'data_audit.json').read_text(encoding='utf8'))
