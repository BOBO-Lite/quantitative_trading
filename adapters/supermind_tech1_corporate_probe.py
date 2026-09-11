"""TECH1.0只读全池日线筛选；固定2019Q2，运行回调2026-09-04，不下单。"""
import base64,hashlib,json,zlib,math
import numpy as np

def emit_packet(key,value):
    raw=json.dumps(value,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('utf8')
    encoded=base64.b64encode(zlib.compress(raw)).decode('ascii')
    parts=[encoded[i:i+3000] for i in range(0,len(encoded),3000)]
    for i,part in enumerate(parts):log.info('MINBUNDLE {} {} {} {} {} {}'.format(key,i,len(parts),len(raw),hashlib.sha256(raw).hexdigest(),part))

SYMBOLS = ['000001.SZ', '000039.SZ', '000042.SZ', '000069.SZ', '000333.SZ', '000402.SZ', '000403.SZ', '000417.SZ', '000418.SZ', '000423.SZ', '000429.SZ', '000525.SZ', '000538.SZ', '000541.SZ', '000544.SZ', '000552.SZ', '000589.SZ', '000598.SZ', '000623.SZ', '000651.SZ', '000667.SZ', '000685.SZ', '000709.SZ', '000726.SZ', '000729.SZ', '000778.SZ', '000825.SZ', '000848.SZ', '000885.SZ', '000898.SZ', '000937.SZ', '000952.SZ', '000959.SZ', '000983.SZ', '002003.SZ', '002024.SZ', '002033.SZ', '002101.SZ', '002128.SZ', '002132.SZ', '002203.SZ', '002233.SZ', '002237.SZ', '002254.SZ', '002277.SZ', '002283.SZ', '002352.SZ', '002486.SZ', '002506.SZ', '002521.SZ', '002536.SZ', '002541.SZ', '002588.SZ', '002697.SZ', '002701.SZ', '002706.SZ', '002739.SZ', '002756.SZ', '002757.SZ', '002822.SZ', '002882.SZ', '600000.SH', '600009.SH', '600015.SH', '600016.SH', '600019.SH', '600021.SH', '600022.SH', '600025.SH', '600036.SH', '600050.SH', '600057.SH', '600059.SH', '600068.SH', '600083.SH', '600085.SH', '600089.SH', '600103.SH', '600123.SH', '600126.SH', '600161.SH', '600168.SH', '600176.SH', '600188.SH', '600256.SH', '600269.SH', '600276.SH', '600277.SH', '600282.SH', '600295.SH', '600307.SH', '600327.SH', '600332.SH', '600348.SH', '600362.SH', '600389.SH', '600395.SH', '600398.SH', '600461.SH', '600467.SH', '600483.SH', '600489.SH', '600500.SH', '600507.SH', '600508.SH', '600519.SH', '600522.SH', '600528.SH', '600548.SH', '600567.SH', '600569.SH', '600585.SH', '600587.SH', '600612.SH', '600660.SH', '600668.SH', '600688.SH', '600704.SH', '600713.SH', '600750.SH', '600753.SH', '600782.SH', '600790.SH', '600795.SH', '600808.SH', '600835.SH', '600859.SH', '600863.SH', '600886.SH', '600887.SH', '600897.SH', '600917.SH', '600919.SH', '600926.SH', '600988.SH', '600997.SH', '601001.SH', '601005.SH', '601009.SH', '601012.SH', '601015.SH', '601069.SH', '601101.SH', '601166.SH', '601168.SH', '601169.SH', '601186.SH', '601225.SH', '601229.SH', '601288.SH', '601318.SH', '601328.SH', '601390.SH', '601398.SH', '601566.SH', '601579.SH', '601600.SH', '601601.SH', '601636.SH', '601666.SH', '601668.SH', '601669.SH', '601699.SH', '601727.SH', '601808.SH', '601818.SH', '601838.SH', '601888.SH', '601898.SH', '601899.SH', '601918.SH', '601933.SH', '601939.SH', '601958.SH', '601966.SH', '601988.SH', '601991.SH', '601997.SH', '601998.SH', '603035.SH', '603059.SH', '603179.SH', '603278.SH', '603368.SH', '603458.SH', '603596.SH', '603639.SH', '603680.SH', '603693.SH', '603808.SH', '603810.SH', '603839.SH', '603890.SH', '603968.SH']

def init(context):set_benchmark('000905.SH')
def before_trading(context):
    if get_datetime().strftime('%Y%m%d')!='20260904':raise ValueError('FIXED_CALLBACK')
    for s in SYMBOLS:
        for kind in ['dividend','details']:
            try:
                if kind=='dividend':f=get_dividend_information(s,start_date='20190301',end_date='20190628')
                else:f=run_query(query(bonus).filter(bonus.symbol==s,bonus.ex_dividend_date>='2019-03-01',bonus.ex_dividend_date<='2019-06-28'))
                emit_packet(kind+'_'+s,dict(status='RETURNED',symbol=s,data=json.loads(f.to_json(date_format='iso'))))
            except Exception as exc:emit_packet(kind+'_'+s,dict(status='ERROR',symbol=s,error=str(exc)))
    log.info('TECH1_CORPORATE_EXPORT_DONE')
def handle_bar(context,bar_dict):pass
