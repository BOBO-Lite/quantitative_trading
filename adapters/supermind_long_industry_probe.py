"""只读扩展：长期基准与历史行业分母；运行2026-09-04。"""
import base64,hashlib,json,zlib

def emit_packet(key,value):
    raw=json.dumps(value,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('utf8')
    encoded=base64.b64encode(zlib.compress(raw)).decode('ascii')
    parts=[encoded[i:i+3000] for i in range(0,len(encoded),3000)]
    for i,part in enumerate(parts):log.info('MINBUNDLE {} {} {} {} {} {}'.format(key,i,len(parts),len(raw),hashlib.sha256(raw).hexdigest(),part))

def init(context):set_benchmark('000905.SH')

def before_trading(context):
    if get_datetime().strftime('%Y%m%d')!='20260904':raise ValueError('READ_ONLY_FIXED_CALLBACK')
    frame=get_price(['000905.SH'],'20170101','20260903','1d',['close'],skip_paused=False,fq=None,is_panel=False)['000905.SH']
    emit_packet('long_benchmark',{'symbol':'000905.SH','end':'2026-09-03','data':json.loads(frame.to_json(date_format='iso'))})
    mappings={};symbols=set()
    for asof in ['20190228','20190331']:
        univ=get_all_securities('stock',asof)
        stocks=set(s for s in univ.index if str(s).startswith(('000','001','002','003','600','601','603','605')) and str(s).endswith(('.SH','.SZ')))
        inds=get_industry_relate(date=asof,types='industryid1');snapshot={}
        for name,row in inds.iterrows():
            code=str(row['industry_symbol']); members=sorted(stocks & set(get_industry_stocks(code,asof)))
            snapshot[code]={'name':str(name),'members':members};symbols.update(members)
        mappings[asof]=snapshot
    emit_packet('industry_memberships',{'mappings':mappings,'source':'historical_get_all_securities_and_industry_stocks'})
    dates_frame=get_price(['000905.SH'],'20190301','20190418','1d',['close'],skip_paused=False,fq=None,is_panel=False)['000905.SH']
    dates=[t.strftime('%Y-%m-%d') for t in dates_frame.index]
    frames=get_price(sorted(symbols),'20190301','20190418','1d',['close'],skip_paused=False,fq='pre',is_panel=False)
    ordered=sorted(symbols)
    for offset in range(0,len(ordered),100):
        rows=[]
        for symbol in ordered[offset:offset+100]:
            f=frames[symbol];series={t.strftime('%Y-%m-%d'):float(v) for t,v in f['close'].items()}
            rows.append({'symbol':symbol,'close':[series.get(day) for day in dates]})
        emit_packet('industry_prices_'+str(offset),{'dates':dates,'rows':rows,'price_basis':'pre_adjusted_ratio_only_not_execution_price'})
    log.info('LONG_AND_INDUSTRY_EXPORT_DONE')

def handle_bar(context,bar_dict):pass

