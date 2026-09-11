"""Read-only causal exit trace and fixed-horizon controls for the sealed FH."""
import json
import hashlib
from pathlib import Path
from e1_reentry_pair import ReentryRules

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/exit_horizon'
def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def save(n, v): (OUT/n).write_text(json.dumps(v, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')

class TraceRules(ReentryRules):
    def __init__(self):
        super().__init__('FH')
        self.first_triggers = {}
    def exit_reason(self, p, bar, route, drawdown, holding_days, close_signal=False, industry_weak=False):
        reason = super().exit_reason(p, bar, route, drawdown, holding_days, close_signal, industry_weak)
        if reason:
            key = (bar['symbol'], p['entry_date'])
            self.first_triggers.setdefault(key, dict(symbol=bar['symbol'], entry_date=p['entry_date'],
                trigger_time=bar['datetime'], reason=reason, close_signal=close_signal,
                holding_days=holding_days, route=route, drawdown=drawdown,
                price=bar['close'], stop=p['stop'], entry_reference=p['entry_price'],
                initial_r=p['initial_r'], prior_context=bar['confirmation']))
        return reason

def trace():
    from recovery_research import prepare
    from simple_history_replay import merge_cache
    from exit_extension_research import read_export
    from e1_confirmation import ConfirmationLoader
    from research_portfolio import run_bundle
    from s2_strategy_rules import Policy
    import e1_turning_research as prev
    cache, bundle = prepare()
    print('BASE_INPUTS_LOADED', flush=True)
    prev.OUT = OUT
    bundle = prev.resolve_known_rights_event(bundle)
    for folder in ('e1_rank_research','e1_conditions','e1_loss_signals','e1_asymmetric','e1_turning','e1_confirmation','e1_reentry_pair','capital_utilization','fh_volatility'):
        for p in sorted((ROOT/'reports'/folder).glob('minute_export_*.txt')):
            cache = merge_cache([cache, read_export(p)])
        print('MERGED '+folder, flush=True)
    loader = ConfirmationLoader(cache, bundle)
    for cost in (1.0, 1.5):
        rules = TraceRules()
        result = run_bundle(bundle, Policy(cost_multiplier=cost), rules=rules, minute_loader=loader.load)
        old = read(ROOT/f'reports/e1_reentry_pair/FH_cost{cost}.json')
        assert result == old, 'audit changed baseline behavior'
        save(f'triggers_cost{cost}.json', list(rules.first_triggers.values()))
        save(f'parity_cost{cost}.json', dict(exact_full_result_match=True, daily_points=len(result['daily']),
            minute_points=len(result['minute_curve']), fills=len(result['fills'])))
        print('EXACT_FH_PARITY '+str(cost), flush=True)

def horizons():
    from hold_benchmarks import hold_path, trade_batches, original_pnl
    from statistics import median
    data = read(ROOT/'reports/hold_benchmarks/historical_inputs.json')
    calendar = sorted({d['date'] for y in (2018,2019,2020) for d in read(ROOT/f'reports/simple_research/{y}/screen.json')['days'] if '2018-01-01'<=d['date']<='2020-12-31'})
    bench = {d['date']:d['benchmark']['close'] for y in (2018,2019,2020) for d in read(ROOT/f'reports/simple_research/{y}/screen.json')['days']}
    rows = []
    for cost in (1.0,1.5):
        triggers = {(r['symbol'],r['entry_date']):r for r in read(OUT/f'triggers_cost{cost}.json')}
        for index, trade in enumerate(trade_batches(read(ROOT/f'reports/e1_reentry_pair/FH_cost{cost}.json')), 1):
            buy = trade['buy']; start = buy['fill_time'][:10]; symbol = buy['symbol']
            trigger = triggers[symbol,start]
            assert trigger['trigger_time'] <= trade['sells'][0]['fill_time']
            for horizon in (20,60):
                row = dict(cost=cost,index=index,symbol=symbol,entry=start,horizon=horizon,trigger=trigger,actual_exit=trade['sells'][-1]['fill_time'])
                offset = calendar.index(start)+horizon-1
                if offset >= len(calendar):
                    row.update(status='CENSORED',reason='insufficient_future_window');rows.append(row);continue
                end = calendar[offset];row['end']=end
                capital = buy['quantity']*buy['price']+buy['fees']
                try:
                    held = hold_path(symbol,buy,capital,calendar[calendar.index(start):offset+1],data)
                    # Only compare with an exit already executed by this same endpoint.
                    if trade['sells'][-1]['fill_time'][:10]>end:
                        row.update(status='EXIT_AFTER_WINDOW',hold_return_pct=held['return_pct']);rows.append(row);continue
                    pnl = original_pnl(trade,data['events'][symbol])
                    market = bench[end]/bench[start]-1
                    row.update(status='COMPLETE',original_net=pnl,hold_net=held['profit'],
                        difference=held['profit']-pnl,hold_return_pct=held['return_pct'],
                        difference_pct=(held['profit']-pnl)/capital*100,
                        hold_close_drawdown_pct=held['close_drawdown_pct'],
                        market_close_to_close_pct=market*100,
                        best_marked_return_pct=max(r['equity']/capital-1 for r in held['curve'])*100,
                        worst_marked_return_pct=min(r['equity']/capital-1 for r in held['curve'])*100)
                except ValueError as e:
                    row.update(status='BLOCKED',reason=str(e))
                rows.append(row)
    save('cases.json', rows)
    groups=[]
    for cost in (1.0,1.5):
        for horizon in (20,60):
            current=[r for r in rows if r['cost']==cost and r['horizon']==horizon]
            for reason in ['ALL']+sorted({r['trigger']['reason'] for r in current}):
                subset=[r for r in current if reason=='ALL' or r['trigger']['reason']==reason]
                done=[r for r in subset if r['status']=='COMPLETE']
                groups.append(dict(cost=cost,horizon=horizon,reason=reason,total=len(subset),complete=len(done),
                    statuses={s:sum(r['status']==s for r in subset) for s in sorted({r['status'] for r in subset})},
                    hold_better=sum(r['difference']>1e-6 for r in done),exit_better=sum(r['difference']< -1e-6 for r in done),
                    median_difference_pct=median(r['difference_pct'] for r in done) if done else None))
    save('groups.json',groups)
    print(json.dumps(groups,ensure_ascii=False),flush=True)

if __name__=='__main__':
    import sys
    assert hashlib.sha256((OUT/'PROTOCOL.md').read_bytes()).hexdigest()==read(OUT/'protocol_lock.json')['sha256']
    if '--horizons-only' not in sys.argv: trace()
    horizons()
