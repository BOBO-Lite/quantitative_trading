"""两档季度交易意图在RQAlpha真实事件/账户中重放，逐分钟核对现金与权益。"""
import argparse,json,sys
from pathlib import Path
from collections import defaultdict
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from rqalpha import run_func
from rqalpha.api import update_universe,get_positions
from adapters.rqalpha_sample_mod import submit_intent,rq_symbol
from simple_minute_cache import Cache
from simple_minute_aliases import apply_aliases
from import_supermind_minute_probe import decode_packets
from validate_corporate_execution import require_native_tax_parity

def validate(cost,cache,metadata,events,out=None,annual=False,expected=None,calendar=None):
    out=out or ROOT/'reports/simple_research'
    if expected is None:expected=json.loads((out/f'{"annual" if annual else "quarter"}_cost{cost}.json').read_text(encoding='utf8'))
    if calendar is None:
        screen=json.loads((out/('screen.json' if annual else 'quarter_screen.json')).read_text(encoding='utf8'))
        calendar=[d['date'] for d in screen['days']]
    symbols=sorted({o['symbol'] for o in expected['orders']})
    active={};intents=defaultdict(list);by_day=defaultdict(set)
    for f in expected['fills']:
        if f['buy']:active[f['symbol']]=f['fill_time'][:10]
        else:require_native_tax_parity(active[f['symbol']],f['fill_time'][:10])
    for o in expected['orders']:
        intents[o['intent_time']].append(o);by_day[o['intent_time'][:10]].add(rq_symbol(o['symbol']))
    dataset=dict(cache=cache,symbols=symbols,calendar=calendar,metadata=metadata,events=events)
    allowed={rq_symbol(s) for s in symbols}
    def init(context):pass
    def before_trading(context):
        held={p.order_book_id for p in get_positions() if p.quantity}
        update_universe(by_day[context.now.strftime('%Y-%m-%d')]|held)
    def handle_bar(context,bars):
        for o in intents[context.now.isoformat()]:submit_intent(context,rq_symbol(o['symbol']),o['quantity'],o['buy'],o['limit'],allowed_symbols=allowed)
    config=dict(base=dict(start_date=calendar[1],end_date=calendar[-1],frequency='1m',accounts={'stock':30000},capital_gain_tax_rate=0,rqdatac_uri='disabled',run_type='b'),extra=dict(log_level='error'),mod=dict(sys_accounts=dict(dividend_tax_enabled=True,dividend_reinvestment=False),sys_analyser=dict(enabled=False),sys_progress=dict(enabled=False),sys_transaction_cost=dict(enabled=False),sys_simulation=dict(enabled=True,matching_type='next_bar',volume_percent=.25,price_limit=True,volume_limit=True),quarter=dict(enabled=True,lib='adapters.rqalpha_tech1_quarter_mod',priority=200,dataset=dataset,cost_multiplier=cost)))
    rq=run_func(config=config,init=init,before_trading=before_trading,handle_bar=handle_bar)['quarter']
    if len(rq['curve'])!=len(expected['minute_curve']):raise ValueError('分钟权益长度不一致')
    maximum=0.
    for a,b in zip(rq['curve'],expected['minute_curve']):
        if a['datetime']!=b['datetime']:raise ValueError('分钟时点不一致')
        for field in ('cash','equity'):
            delta=abs(a[field]-b[field]);maximum=max(maximum,delta)
            if delta>1e-6:raise ValueError(str((field,a,b)))
    if len(rq['fills'])!=len(expected['fills']):raise ValueError('成交数不同')
    for a,b in zip(rq['fills'],expected['fills']):
        if a['symbol']!=rq_symbol(b['symbol']) or a['fill_time']!=b['fill_time'] or a['buy']!=b['buy']:raise ValueError('成交身份不一致')
        for field in ('price','quantity','fees','cash_after'):
            if abs(a[field]-b[field])>1e-6:raise ValueError('逐笔对账失败：'+field)
    return dict(cost=cost,status='PASS_ANNUAL_EXECUTION_PARITY' if annual else 'PASS_QUARTER_EXECUTION_PARITY',minute_comparisons=len(rq['curve']),fills=len(rq['fills']),maximum_cash_or_equity_difference=maximum,final_cash=rq['cash'],final_equity=rq['equity'],taxes=rq['taxes'],scope='same intents, independent account execution; not independent strategy selection')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--year',type=int);parser.add_argument('--end-year',type=int);args=parser.parse_args()
    out=ROOT/'reports/simple_research';packets={}
    if args.end_year:
        from simple_history_replay import load_inputs
        out=out/f'continuous_2018_{args.end_year}';cache,days=load_inputs(args.end_year)
        metadata=pd.read_csv(ROOT/'runtime/industry_history/monthly_universe.csv.gz',dtype=str).drop_duplicates('symbol').set_index('symbol').to_dict('index')
        events=json.loads((out/'corporate_events.json').read_text(encoding='utf8'))['cash']
        results=[]
        for cost in (1.,1.5):
            expected=json.loads((out/f'cost{cost}.json').read_text(encoding='utf8'))
            result=validate(cost,cache,metadata,events,out,expected=expected,calendar=[d['date'] for d in days])
            result['status']='PASS_CONTINUOUS_EXECUTION_PARITY';results.append(result)
        (out/'rqalpha_parity.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(results,ensure_ascii=False));return
    if args.year:out=out/str(args.year)
    for f in out.glob('minute_export*.txt'):
        for k,p in decode_packets(f.read_text(encoding='utf8')).items():
            if k in packets and p!=packets[k]:raise ValueError('行情缓存冲突')
            packets[k]=p
    cache=Cache(apply_aliases(packets,out))
    metadata=pd.read_csv(ROOT/'runtime/industry_history/monthly_universe.csv.gz',dtype=str).drop_duplicates('symbol').set_index('symbol').to_dict('index')
    events=json.loads((out/'corporate_events.json').read_text(encoding='utf8'))['cash']
    results=[validate(cost,cache,metadata,events,out,bool(args.year)) for cost in (1.,1.5)]
    (out/('rqalpha_annual_parity.json' if args.year else 'rqalpha_quarter_parity.json')).write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(results,ensure_ascii=False))

if __name__=='__main__':main()
