"""固定历史分钟样本的离线执行核验，不产生选股或实盘指令。"""
import argparse
import hashlib
import json
from pathlib import Path

from research_execution import ReplayBroker
from s2_strategy_rules import Policy


def replay(dataset, participation, cost_multiplier=1.):
    if dataset['status'] != 'PASS_FIXED_SAMPLE_MINUTE_DATA':
        raise ValueError('输入未通过分钟数据核账')
    broker = ReplayBroker(30000., participation, Policy(cost_multiplier=cost_multiplier))
    batches = {}
    for row in dataset['rows']:
        batches.setdefault(row['datetime'], {})[row['symbol']] = row
    for stamp, bars in sorted(batches.items()):
        broker.on_minute(stamp, bars)
        if stamp == '2019-04-17T09:45:00':
            # 同时预留两笔委托的最高含费金额；不得借用尚未发生的低价成交释放现金。
            for symbol, qty, cap in [('000001.SZ', 500, 14.5), ('600036.SH', 600, 36.)]:
                broker.submit(symbol, qty, stamp, True, bars[symbol]['factor'], cap)
        if stamp == '2019-04-19T09:45:00':
            for symbol, position in list(broker.positions.items()):
                broker.submit(symbol, position.quantity, stamp, False, position.factor)
    if broker.positions:
        raise ValueError('固定案例未完成退出，不能标记闭环')
    if abs(broker.equity - 30000 - broker.realized_pnl) > 1e-7:
        raise AssertionError('账户资金和已实现损益不一致')
    return dict(status='PASS_FIXED_HISTORICAL_EXECUTION_REPLAY', formal_strategy_validated=False,
                participation=participation, snapshot=broker.snapshot(), fills=broker.fills,
                orders=broker.orders,
                limitations=['Fixed intents, not strategy signals',
                             'Buy caps 14.5/36 reserve both orders within 30000; differs from platform cap38 fixture',
                             'Local sell tax 0.05%; platform diagnostic 0.10%; do not compare net cash as identical'])


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dataset', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    raw = Path(args.dataset).read_bytes()
    dataset = json.loads(raw)
    result = dict(input_sha256=hashlib.sha256(raw).hexdigest(),
                  cases=[replay(dataset, rate) for rate in (.25, .001)])
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps([dict(participation=c['participation'], status=c['status'],
                          quantities=[f['quantity'] for f in c['fills']]) for c in result['cases']]))


if __name__ == '__main__':
    main()
