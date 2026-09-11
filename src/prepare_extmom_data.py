"""Build read-only requests from audited monthly candidate union, not current holdings."""
import json
from external_momentum import ROOT,OUT,buy_eligible

TEMPLATE='''import base64,hashlib,json,zlib
SYMBOLS = __SYMBOLS__
DATES = __DATES__
def emit(key,value):
    raw=json.dumps(value,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('utf8')
    encoded=base64.b64encode(zlib.compress(raw)).decode('ascii');parts=[encoded[i:i+3000] for i in range(0,len(encoded),3000)]
    for i,part in enumerate(parts):log.info('MINBUNDLE {} {} {} {} {} {}'.format(key,i,len(parts),len(raw),hashlib.sha256(raw).hexdigest(),part))
def packet(f):return json.loads(f.to_json(date_format='iso'))
def init(context):set_benchmark('000905.SH')
def before_trading(context):
    if get_datetime().strftime('%Y%m%d')!='20260904':raise ValueError('FIXED_CALLBACK')
    fields=['open','high','low','close','volume','turnover','factor','is_st','is_paused','high_limit','low_limit']
    for s in SYMBOLS:
        try:
            f=get_price([s],'20171201','20201231','1d',fields,skip_paused=False,fq=None,is_panel=False)[s]
            emit('daily_'+s,dict(symbol=s,status='RETURNED',data=packet(f)))
        except Exception as exc:emit('daily_'+s,dict(symbol=s,status='ERROR',error=str(exc)))
        for kind in ['dividend','details']:
            try:
                if kind=='dividend':f=get_dividend_information(s,start_date='20180101',end_date='20201231')
                else:f=run_query(query(bonus).filter(bonus.symbol==s,bonus.ex_dividend_date>='2018-01-01',bonus.ex_dividend_date<='2020-12-31'))
                emit(kind+'_'+s,dict(status='RETURNED',symbol=s,data=packet(f)))
            except Exception as exc:emit(kind+'_'+s,dict(status='ERROR',symbol=s,error=str(exc)))
    for day in DATES:
        d=day.replace('-','')
        try:
            frames=get_price(SYMBOLS,d+'0935',d+'0936','1m',['open','high','low','close','volume','turnover'],skip_paused=False,fq=None,is_panel=False)
            selected={}
            for s in SYMBOLS:
                f=frames[s];f=f[[t.strftime('%H:%M')=='09:35' for t in f.index]]
                if len(f)>1:raise ValueError('MINUTE_GRID '+s+' '+day)
                selected[s]=packet(f)
            emit('minute_'+day,dict(status='RETURNED',date=day,data=selected))
        except Exception as exc:emit('minute_'+day,dict(status='ERROR',date=day,error=str(exc)))
    log.info('EXTMOM_DATA_DONE')
def handle_bar(context,bar_dict):pass
'''

def main():
    screen=json.loads((OUT/'screen.json').read_text(encoding='utf8'))
    if screen['months']!=36:raise ValueError('Need all 36 months before account data request')
    symbols=sorted({r['symbol'] for snap in screen['rankings'].values() if snap['market_on'] for r in [x for x in snap['rows'] if buy_eligible(x)][:5]})
    dates=set();calendar=screen['calendar']
    for day in screen['rankings']:
        i=calendar.index(day);dates.update(calendar[i:i+6])
    dates=sorted(d for d in dates if d<='2020-12-31')
    (OUT/'data_probe.py').write_text(TEMPLATE.replace('__SYMBOLS__',repr(symbols)).replace('__DATES__',repr(dates)),encoding='utf8')
    (OUT/'data_requests.json').write_text(json.dumps(dict(symbols=symbols,dates=dates,scope='candidate union only for data retrieval, never a historical ranking universe'),ensure_ascii=False,indent=2),encoding='utf8')
    print('symbols',len(symbols),'minute dates',len(dates))

if __name__=='__main__':main()
