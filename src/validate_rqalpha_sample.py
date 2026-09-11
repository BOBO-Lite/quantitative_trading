"""运行真实RQAlpha事件循环，和独立本地账本比较固定意图。"""
import argparse, hashlib, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rqalpha import run_func
from rqalpha.api import order_shares, update_universe
from replay_historical_minute_probe import replay
from adapters.rqalpha_sample_mod import submit_intent


def run_case(dataset, participation=.25, cost_multiplier=1., callback=None):
    if not 0 < participation <= .25 or cost_multiplier not in (1., 1.5):
        raise ValueError('仅接受已登记的参与率和成本情景')
    orders = []
    def init(context): update_universe(['000001.XSHE','600036.XSHG'])
    def handle_bar(context, bars):
        if callback is not None:
            callback(context, bars, orders)
            return
        stamp = context.now.isoformat()
        if stamp == '2019-04-17T09:45:00':
            orders.extend([submit_intent(context,'000001.XSHE',500,True,14.5),submit_intent(context,'600036.XSHG',600,True,36.)])
        if stamp == '2019-04-19T09:45:00':
            for symbol in ['000001.XSHE','600036.XSHG']:
                q = context.portfolio.positions[symbol].quantity
                if q: orders.append(submit_intent(context,symbol,q,False))
    config = dict(base=dict(start_date='2019-04-17',end_date='2019-04-19',frequency='1m',accounts={'stock':30000},capital_gain_tax_rate=0,rqdatac_uri='disabled',run_type='b'),extra=dict(log_level='error'),mod=dict(sys_analyser=dict(enabled=False),sys_progress=dict(enabled=False),sys_transaction_cost=dict(enabled=False),sys_simulation=dict(enabled=True,matching_type='next_bar',volume_percent=participation,price_limit=True,volume_limit=True),sample=dict(enabled=True,lib='adapters.rqalpha_sample_mod',priority=200,dataset=dataset,cost_multiplier=cost_multiplier)))
    result = run_func(config=config, init=init, handle_bar=handle_bar)['sample']
    result['orders'] = [dict(quantity=o.quantity, filled_quantity=o.filled_quantity,status=str(o.status)) if o is not None else None for o in orders]
    return result


def main():
    p = argparse.ArgumentParser(); p.add_argument('--output',required=True); args = p.parse_args()
    path = ROOT/'reports/s2_research/portfolio_replay/historical_minute_sample.json'
    raw = path.read_bytes(); dataset = json.loads(raw)
    cases = []
    for participation, multiplier in ((.25,1.),(.001,1.),(.25,1.5),(.001,1.5)):
        result = run_case(dataset, participation, multiplier)
        local = replay(dataset,participation,multiplier)
        assert len(result['fills']) == len(local['fills']) == 4
        for rq, own in zip(result['fills'],local['fills']):
            for key in ('price','quantity','fees','cash_after'):
                assert abs(rq[key]-own[key]) < 1e-7, (key,rq,own)
            assert rq['fill_time'] == own['fill_time']
        assert abs(result['cash'] - local['snapshot']['cash']) < 1e-7
        cases.append(dict(participation=participation,cost_multiplier=multiplier,status='PASS',rqalpha=result,local=local))
    report = dict(status='PASS_RQALPHA_FIXED_SAMPLE_PARITY',input_sha256=hashlib.sha256(raw).hexdigest(),cases=cases,formal_strategy_validated=False,automatic_trading=False)
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(status=report['status'],cases=len(cases))))
if __name__ == '__main__': main()

