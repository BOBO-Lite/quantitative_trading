"""固定ETF交易意图在真实RQAlpha引擎独立执行，核对成交及每日账户。"""
import json,sys
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from rqalpha import run_func
from rqalpha.api import update_universe
from adapters.rqalpha_sample_mod import submit_intent,rq_symbol
from etf_dataset import build,OUT,SYMBOLS

def main():
    out=OUT/'extended_2018_2026' if '--extended' in sys.argv else OUT
    if '--multi' in sys.argv:
        from multiasset_research import inputs,OUT as multi_out
        calendar,daily,events,minutes=inputs();out=multi_out
    else:calendar,daily,events,minutes=build(out=OUT/'extended_2018_2026' if '--long' in sys.argv else out)
    dataset=dict(calendar=calendar,daily=daily,events=events,minutes=minutes);results=[]
    if '--multi' in sys.argv:dataset['market_tplus']={'511010.SH':0,'518880.SH':0,'510300.SH':1}
    if '--long' in sys.argv:out=OUT/'long_trend'
    allowed={rq_symbol(s) for s in daily}
    for cost in (1.,1.5):
        expected=json.loads((out/f'cost{cost}.json').read_text(encoding='utf8'))
        if expected['status']!='COMPLETED':raise ValueError('本地回放未完整完成')
        intents=defaultdict(list)
        for o in expected['orders']:intents[o['date']].append(o)
        def init(context):update_universe(allowed)
        def handle_bar(context,bars):
            if context.now.strftime('%H:%M')!='09:34':return
            for o in intents[context.now.strftime('%Y-%m-%d')]:submit_intent(context,rq_symbol(o['symbol']),o['quantity'],o['buy'],o.get('cap'),allowed_symbols=allowed)
        config=dict(base=dict(start_date='2018-01-02',end_date=calendar[-1],frequency='1m',accounts={'stock':30000},capital_gain_tax_rate=0,rqdatac_uri='disabled',run_type='b'),extra=dict(log_level='error'),mod=dict(sys_accounts=dict(dividend_tax_enabled=False,dividend_reinvestment=False),sys_analyser=dict(enabled=False),sys_progress=dict(enabled=False),sys_transaction_cost=dict(enabled=False),sys_simulation=dict(enabled=True,matching_type='next_bar',volume_percent=.01,price_limit=True,volume_limit=True),etf=dict(enabled=True,lib='adapters.rqalpha_etf_mod',priority=200,dataset=dataset,cost_multiplier=cost)))
        rq=run_func(config=config,init=init,handle_bar=handle_bar)['etf']
        (out/f'rqalpha_raw_cost{cost}.json').write_text(json.dumps(rq,ensure_ascii=False,indent=2),encoding='utf8')
        if len(rq['curve'])!=len(expected['daily']) or len(rq['fills'])!=len(expected['fills']):raise ValueError('账户/成交长度不一')
        maximum=0.
        for a,b in zip(rq['curve'],expected['daily']):
            if a['date']!=b['date'] or a['positions']!={rq_symbol(s):q for s,q in b['positions'].items()}:raise ValueError('账户身份或持仓不同')
            for k in ('cash','equity'):
                delta=abs(a[k]-b[k]);maximum=max(maximum,delta)
                if delta>1e-6:raise ValueError(str((k,a,b)))
        for a,b in zip(rq['fills'],expected['fills']):
            if a['symbol']!=rq_symbol(b['symbol']) or any(a[k]!=b[k] for k in ('datetime','buy','quantity')):raise ValueError('逐笔成交身份不同')
            if any(abs(a[k]-b[k])>1e-6 for k in ('price','fee')):raise ValueError('成交价格/费用不同')
        results.append(dict(cost=cost,status='PASS_ETF_EXECUTION_ACCOUNT_PARITY',daily_comparisons=len(rq['curve']),fills=len(rq['fills']),max_cash_equity_difference=maximum,scope='相同订单意图，独立ETF成交及账户；每天三个真实分钟驱动，只核对日收盘账户，不是逐分钟全路径或独立选股验证'))
    (out/'rqalpha_parity.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(results,ensure_ascii=False))

if __name__=='__main__':main()
