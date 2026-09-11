"""固定真实分红窗口的双引擎逐分钟核账；不产生策略收益结论。"""
import json,sys
import pandas as pd
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from rqalpha import run_func
from rqalpha.api import update_universe
from adapters.rqalpha_sample_mod import submit_intent,rq_symbol
from research_execution import ReplayBroker
from s2_strategy_rules import Policy
from corporate_actions import dividend_tax_rate

def require_native_tax_parity(buy_day,sell_day):
    buy,sell=pd.Timestamp(buy_day),pd.Timestamp(sell_day)
    native=.2 if buy>=sell-pd.DateOffset(months=1) else .1 if buy>=sell-pd.DateOffset(years=1) else 0.
    if native!=dividend_tax_rate(buy_day,sell_day):
        raise ValueError('RQAlpha原生红利税自然月边界不一致，禁止把本窗口标为验收通过')

def run_window(dataset,multiplier=1.,sell_day=None):
    symbol=dataset['symbol']; rqid=rq_symbol(symbol); days=dataset['dates']
    sell_day=sell_day or days[-1]
    require_native_tax_parity(days[0],sell_day)
    # 固定500股，登记日上午买入，窗口最后一天退出；既不按收益选时也不作策略信号。
    qty=500
    cap=round(next(r['open'] for r in dataset['rows'] if r['datetime']==days[0]+'T09:46:00')*1.02,2)
    broker=ReplayBroker(30000.,.25,Policy(cost_multiplier=multiplier),dataset['events'])
    local=[]
    for row in dataset['rows']:
        stamp=row['datetime'];broker.on_minute(stamp,{symbol:row})
        if stamp==days[0]+'T09:45:00':broker.submit(symbol,qty,stamp,True,row['factor'],cap)
        if stamp==sell_day+'T09:45:00':broker.submit(symbol,broker.positions[symbol].quantity,stamp,False,row['factor'])
        local.append(dict(datetime=stamp,cash=broker.cash,equity=broker.equity))
        if stamp.endswith('T15:00:00'):broker.close_day(stamp[:10])
    def init(context):update_universe([rqid])
    def handle_bar(context,bars):
        stamp=context.now.isoformat()
        if stamp==days[0]+'T09:45:00':submit_intent(context,rqid,qty,True,cap)
        if stamp==sell_day+'T09:45:00':submit_intent(context,rqid,qty,False)
    config=dict(base=dict(start_date=days[0],end_date=days[-1],frequency='1m',accounts={'stock':30000},capital_gain_tax_rate=0,rqdatac_uri='disabled',run_type='b'),extra=dict(log_level='error'),mod=dict(sys_accounts=dict(dividend_tax_enabled=True,dividend_reinvestment=False),sys_analyser=dict(enabled=False),sys_progress=dict(enabled=False),sys_transaction_cost=dict(enabled=False),sys_simulation=dict(enabled=True,matching_type='next_bar',volume_percent=.25,price_limit=True,volume_limit=True),corporate=dict(enabled=True,lib='adapters.rqalpha_corporate_mod',priority=200,dataset=dataset,cost_multiplier=multiplier)))
    rq=run_func(config=config,init=init,handle_bar=handle_bar)['corporate']
    assert len(rq['curve'])==len(local)
    for a,b in zip(rq['curve'],local):
        assert a['datetime']==b['datetime']
        for f in ('cash','equity'):assert abs(a[f]-b[f])<1e-7,(f,a,b)
    assert len(rq['fills'])==len(broker.fills)==2
    for a,b in zip(rq['fills'],broker.fills):
        for f in ('price','quantity','fees','cash_after'):assert abs(a[f]-b[f])<1e-7,(f,a,b)
    expected=qty*dataset['events'][0]['cash_per_share']
    assert abs(broker.corporate.gross_income-expected)<1e-7
    assert abs(broker.corporate.tax_paid-expected*.2)<1e-7
    assert abs(sum(t['amount'] for t in rq['taxes'])-expected*.2)<1e-7
    assert abs(broker.equity-30000-broker.realized_pnl-broker.corporate.gross_income+broker.corporate.tax_paid)<1e-7
    return dict(status='PASS',symbol=symbol,dates=days,cost_multiplier=multiplier,minute_comparisons=len(local),snapshot=broker.snapshot(),corporate_ledger=broker.corporate.ledger,rqalpha=rq)

def main():
    out=ROOT/'reports/s2_research/corporate_actions'
    data=json.loads((out/'verified_windows.json').read_text(encoding='utf-8'))
    cases=[run_window(d,m) for d in data['cases'] for m in (1.,1.5)]
    report=dict(status='PASS_REAL_CASH_DIVIDEND_PARITY',cases=cases,formal_strategy_validated=False,automatic_trading=False)
    (out/'execution_parity.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print([(c['symbol'],c['dates'][0],c['cost_multiplier'],c['snapshot']) for c in cases])
if __name__=='__main__':main()
