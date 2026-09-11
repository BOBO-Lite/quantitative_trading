"""审计平台页面导出的历史诊断日志；不执行日志里的Python表达式。"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path


NUMBER = r'[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?'


def number(text, field):
    match = re.search(r"'" + re.escape(field) + r"': (" + NUMBER + r")", text)
    if not match:
        raise ValueError('日志缺少数值字段：' + field)
    return float(match[1])


def audit_log(text, capital=30000., participation=.001):
    """回调时间按已审计的next_open映射经济时间，不能用于任意平台日志。"""
    bars = {}
    for match in re.finditer(r'BAR (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (\w+\.\w+) open=(' + NUMBER +
                             r') close=(' + NUMBER + r') vol=(' + NUMBER + r') amount=(' + NUMBER + r')', text):
        stamp, symbol, op, close, volume, amount = match.groups()
        bars[(stamp, symbol)] = dict(open=float(op), close=float(close), volume=float(volume), amount=float(amount))
    fills = []
    cash, inventory = capital, {}
    liquidity_excess = []
    matches = list(re.finditer(r'FILL (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) Trade\(([^\n]+)\)', text))
    # 正式报告页按倒序显示日志；以事件时间还原账本。
    for match in sorted(matches, key=lambda item: item[1]):
        stamp, payload = match.groups()
        symbol = re.search(r"'order_book_id': '([^']+)'", payload)[1]
        side = re.search(r"'side': SIDE\.(BUY|SELL)", payload)[1]
        economic_time = (datetime.fromisoformat(stamp) + timedelta(minutes=1)).isoformat(sep=' ')
        bar = bars.get((economic_time, symbol))
        if bar is None:
            raise ValueError('缺少经济成交分钟BAR：' + economic_time + ' ' + symbol)
        price, quantity = number(payload, 'last_price'), number(payload, 'last_quantity')
        commission, tax = number(payload, 'commission'), number(payload, 'tax')
        costs = number(payload, 'transaction_cost')
        expected = bar['open'] * (1.001 if side == 'BUY' else .999)
        cash += (-1 if side == 'BUY' else 1) * price * quantity - costs
        inventory[symbol] = inventory.get(symbol, 0) + (1 if side == 'BUY' else -1) * quantity
        if inventory[symbol] < 0 or cash < -1e-7:
            raise ValueError('成交账本出现负持仓或透支')
        within_volume = quantity <= bar['volume'] * participation + 1e-8
        item = dict(symbol=symbol, side=side, callback_time=stamp, economic_time=economic_time,
                    quantity=quantity, price=price, expected_next_open_price=expected,
                    price_matches=abs(price - expected) < 1e-8,
                    commission=commission, tax=tax, transaction_cost=costs,
                    fee_components_match=abs(costs - commission - tax) < 1e-8,
                    minute_volume=bar['volume'], within_requested_volume_limit=within_volume,
                    cash_after=cash)
        fills.append(item)
        if not within_volume:
            liquidity_excess.append(item)
    if not fills:
        raise ValueError('日志中没有成交，不能验收成交模型')
    end_accounts = sorted(re.findall(r'PROBE_END (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) StockAccount\(([^\n]+)\)', text))
    ended = '回测结束' in text and bool(end_accounts)
    final_cash = number(end_accounts[-1][1], 'available_cash') if end_accounts else None
    cash_matches = final_cash is not None and abs(cash - final_cash) < 1e-7
    return dict(schema_version=1, purpose='execution_contract_audit_not_strategy_performance',
                completed=ended, fill_count=len(fills), fills=fills,
                all_next_open_prices_match=all(x['price_matches'] for x in fills),
                all_fee_components_match=all(x['fee_components_match'] for x in fills),
                initial_cash=capital, reconstructed_cash=cash, platform_final_cash=final_cash,
                cash_reconciles=cash_matches, final_inventory=inventory,
                requested_participation=participation, volume_limit_excess_count=len(liquidity_excess),
                formal_strategy_validated=False,
                status='PASS_PRICE_AND_CASH_ONLY' if ended and cash_matches and all(x['price_matches'] and x['fee_components_match'] for x in fills) else 'INCOMPLETE_OR_MISMATCH')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.log.read_bytes()
    report = audit_log(raw.decode('utf-8-sig'))
    report['source_sha256'] = hashlib.sha256(raw).hexdigest()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'execution_audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    with (args.output / 'fills.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(report['fills'][0]))
        writer.writeheader()
        writer.writerows(report['fills'])
    print(json.dumps({k: v for k, v in report.items() if k != 'fills'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
