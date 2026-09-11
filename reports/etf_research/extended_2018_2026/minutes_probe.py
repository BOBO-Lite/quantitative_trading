"""固定两ETF全研究期09:35原始分钟与完整日内量价摘要，不下单。"""
import base64,hashlib,json,zlib
SYMBOLS=['510300.SH','510500.SH']
def emit(key,value):
    raw=json.dumps(value,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('utf8')
    enc=base64.b64encode(zlib.compress(raw)).decode('ascii');parts=[enc[i:i+3000] for i in range(0,len(enc),3000)]
    for i,p in enumerate(parts):log.info('MINBUNDLE {} {} {} {} {} {}'.format(key,i,len(parts),len(raw),hashlib.sha256(raw).hexdigest(),p))
def init(context):set_benchmark('000300.SH')
def before_trading(context):
    if get_datetime().strftime('%Y%m%d')!='20260904':raise ValueError('FIXED_CALLBACK')
    for s in SYMBOLS:
        for year in range(2018,2027):
            f=get_price([s],str(year)+'01010930',(str(year)+'12311500' if year<2026 else '202609041500'),'1m',['open','high','low','close','volume','turnover'],skip_paused=False,fq=None,is_panel=False)[s]
            out=[]
            for day,a in f.groupby(f.index.strftime('%Y-%m-%d')):
                selected=a[a.index.strftime('%H:%M').isin(['09:34','09:35','15:00'])]
                out.append(dict(date=day,count=len(a),first=a.index[0].strftime('%H:%M'),last=a.index[-1].strftime('%H:%M'),
                    times=[t.strftime('%H:%M') for t in a.index],open=float(a.iloc[0]['open']),high=float(a['high'].max()),low=float(a['low'].min()),close=float(a.iloc[-1]['close']),
                    volume=float(a['volume'].sum()),turnover=float(a['turnover'].sum()),minute=json.loads(selected.to_json(date_format='iso'))))
            emit('etf_minutes_'+s+'_'+str(year),dict(symbol=s,year=year,days=out))
    log.info('ETF1_MINUTES_DONE')
def handle_bar(context,bar_dict):pass
