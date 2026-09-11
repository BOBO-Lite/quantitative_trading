"""对齐平台现金/股数与日期明细；不使用股息率字段推算现金。"""
def build_events(packets,symbols,start='2019-04-01'):
    cash=[];unsupported=[]
    for s in symbols:
        a,b=packets['dividend_'+s],packets['details_'+s]
        if a['status']!='RETURNED' or b['status']!='RETURNED':raise ValueError('公司行动来源失败：'+s)
        d=a['data'];details=b['data'];by_date={};source_counts={}
        for i,stamp in details.get('stock_bonus_ex_dividend_date',{}).items():
            if stamp is None:raise ValueError('公司行动生效日期缺失')
            day=stamp[:10]
            if day<start:continue
            row={k:v[i] for k,v in details.items()}
            if day in by_date:
                # 该比例是统计指标，不是每股现金；不同统计口径的重复行不重复计分红。
                keys=set(row)-{'stock_bonus_cash_dividend_ratio'}
                if any(row[k]!=by_date[day][k] for k in keys):raise ValueError('冲突的重复公司行动日期明细')
                source_counts[day]+=1;continue
            by_date[day]=row;source_counts[day]=1
        stamps=[t for t in d.get('symbol',{}) if t[:10]>=start]
        if set(t[:10] for t in stamps)!=set(by_date):raise ValueError('公司行动两接口事件集合不符：'+s)
        for stamp in stamps:
            day=stamp[:10];r=by_date[day]
            if d['symbol'][stamp]!=s or r['stock_bonus_symbol']!=s:raise ValueError('公司行动股票身份错误')
            if day<start:continue
            shares=d['give_stock'][stamp]+d['transfer_stock'][stamp]
            if shares!=0:
                record=r.get('stock_bonus_date_of_record')
                if not isinstance(record,str) or not record[:10]<day:raise ValueError('送转缺股权登记日：'+s)
                unsupported.append(dict(symbol=s,record_date=record[:10],ex_date=day,shares_per_share=shares));continue
            amount=d['cash_dividends'][stamp]
            if amount<=0:raise ValueError('公司行动缺少现金或股数解释')
            e=dict(symbol=s,ex_date=day,cash_per_share=amount,shares_per_share=0,source_rows_merged=source_counts[day])
            for field,source in [('record_date','stock_bonus_date_of_record'),('pay_date','stock_bonus_date_payable'),('announcement_date','stock_bonus_dividend_announcement_date')]:
                value=r[source]
                if not isinstance(value,str):raise ValueError('公司行动日期字段缺失：'+s)
                e[field]=value[:10]
            cash.append(e)
    return cash,unsupported
