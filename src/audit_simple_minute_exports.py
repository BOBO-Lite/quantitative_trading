"""核对年度入场分钟包集合，避免页面只加载部分完整包而误认为全量。"""
import argparse,ast,json
from pathlib import Path
from import_supermind_minute_probe import decode_packets
ROOT=Path(__file__).resolve().parents[1]

def audit(folder):
    result=[]
    for source in sorted(folder.glob('minute_probe_[0-9][0-9].py')):
        number=source.stem[-2:];raw=folder/f'minute_export_entry{number}.txt'
        tree=ast.parse(source.read_text(encoding='utf8'))
        wanted=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='REQUESTS' for t in n.targets))
        text=raw.read_text(encoding='utf8')
        if 'TECH1_ENTRY_MINUTE_EXPORT_DONE' not in text:raise ValueError('无分钟导出结束标记')
        packets=decode_packets(text)
        actual={(p['symbol'],p['date']) for k,p in packets.items() if k.startswith('minute_')}
        missing=set(wanted)-actual;extra=actual-set(wanted)
        result.append(dict(batch=number,requested=len(wanted),received=len(actual),missing=sorted(missing),extra=sorted(extra)))
    if not result:raise ValueError('没有入场请求批次')
    report=dict(status='FAIL' if any(r['missing'] or r['extra'] for r in result) else 'PASS_REQUEST_SET',batches=result)
    (folder/'entry_request_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--year',type=int,required=True);a=p.parse_args()
    r=audit(ROOT/'reports/simple_research'/str(a.year));print(dict(status=r['status'],batches=[{k:v for k,v in x.items() if k not in ('missing','extra')} for x in r['batches']]))
    if r['status']!='PASS_REQUEST_SET':raise SystemExit(1)
