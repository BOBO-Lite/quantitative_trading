"""按公告与原始日线对账桥接历史证券代码；不覆盖原始证据文件。"""
import copy,hashlib,json
from import_supermind_minute_probe import decode_packets

ALIASES={'000043.SZ':('001914.SZ','2019-12-16')}
SOURCE='https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=5798742'

def apply_aliases(packets,folder):
    result=dict(packets);audit=[]
    for f in sorted(folder.glob('alias_export*.txt')):
        raw=f.read_text(encoding='utf8')
        if 'TECH1_ENTRY_MINUTE_EXPORT_DONE' not in raw:raise ValueError('旧代码导出未完成')
        source=decode_packets(raw)
        for key,p in source.items():
            if not key.startswith('minute_'):continue
            old=p['symbol'];day=p['date']
            if old not in ALIASES:raise ValueError('无公告依据的代码映射')
            new,effective=ALIASES[old]
            if day>=effective:raise ValueError('旧代码使用日期超出公告范围')
            target='minute_'+day+'_'+new
            if target not in result or result[target]['dates']:raise ValueError('代码桥接只允许补已有明确空缺')
            a=source['daily_'+old];b=result['daily_'+new]
            i=[d[:10] for d in a['dates']].index(day);j=[d[:10] for d in b['dates']].index(day)
            fields=('open','high','low','close','volume','turnover','is_st','is_paused')
            if any(a['data'][k][i]!=b['data'][k][j] for k in fields):raise ValueError('代码桥接原始日线不一致')
            replacement=copy.deepcopy(p);replacement['symbol']=new;result[target]=replacement
            audit.append(dict(date=day,old_symbol=old,canonical_symbol=new,announcement=SOURCE,
                raw_price_volume_amount_state_exact=True,rows=len(p['dates']),
                provider_factor_delta=a['data']['factor'][i]-b['data']['factor'][j],
                old_high_limit=a['data']['high_limit'][i],canonical_high_limit=b['data']['high_limit'][j],
                note='原始分钟桥接后，以标准日线提供复权因子及涨跌停价；两者不是新生成价格',sha256=hashlib.sha256(f.read_bytes()).hexdigest()))
    if audit:(folder/'alias_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf8')
    return result
