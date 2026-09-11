"""按已登记区间核验历史导出，不产生绩效结论。"""
import argparse,hashlib,json
from pathlib import Path
import pandas as pd
from audit_simple_daily import audit
from import_supermind_minute_probe import decode_packets
ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument('--year',type=int,required=True);args=p.parse_args()
    if args.year not in range(2018,2027):raise ValueError('未登记年份')
    out=ROOT/'reports/simple_research'/str(args.year)
    sources=sorted(out.glob('daily_export_h*.txt')) or [out/'daily_export.txt']
    packets={};hashes={}
    for raw in sources:
        text=raw.read_text(encoding='utf8')
        if 'TECH1_HISTORY_DAILY_EXPORT_DONE' not in text:raise ValueError('历史导出未完成')
        for k,v in decode_packets(text).items():
            if k=='benchmark' and k in packets:
                old=packets[k]['data']['close'];new=v['data']['close']
                if any(old[d]!=new[d] for d in set(old)&set(new)):raise ValueError('分段基准冲突')
                old.update(new)
            elif k in packets and packets[k]!=v:raise ValueError('分段边界股票数据冲突')
            else:packets[k]=v
        hashes[raw.name]=hashlib.sha256(raw.read_bytes()).hexdigest()
    reference=ROOT/'reports/s2_research/long_history/research_benchmark.csv';full=pd.read_csv(reference)
    before=full[full.date<str(args.year)].date.tolist()[-1]
    days=[before]+full[full.date.str.startswith(str(args.year))].date.tolist()
    result=audit(packets,days[0],days[-1])
    if [r['date'] for r in result['days']]!=days:raise ValueError('独立基准日历缺口')
    result['status']=result['status'].replace('QUARTER','HISTORY')
    result['log_sha256']=hashes
    result['reference_sha256']=hashlib.sha256(reference.read_bytes()).hexdigest()
    result['scope']='historical daily screen only; not a portfolio replay'
    (out/'screen.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(dict(status=result['status'],days=len(days),market_on=sum(d['route']=='trend_breakout' for d in result['days']),candidates=sum(len(d['candidates']) for d in result['days']),minute_requests=len(result['minute_requests']),errors=result['errors'][:20]))

if __name__=='__main__':main()
