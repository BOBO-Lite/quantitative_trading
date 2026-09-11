"""Describe realized trades and observed holding paths; no optimal-exit backtest."""
import json,hashlib
from collections import Counter,defaultdict
from statistics import mean,median
from e1_condition_study import ROOT
from recovery_research import prepare
from exit_extension_research import read_export
from simple_history_replay import merge_cache

OUT=ROOT/'reports/e1_trade_path_diagnosis'

def analyze(path,cache):
    result=json.loads(path.read_text(encoding='utf8'));opened={};trades=[]
    for f in result['fills']:
        s=f['symbol']
        if f['buy']:
            assert s not in opened,'partial/add entry needs separate handling'
            opened[s]=f;continue
        b=opened.pop(s);assert b['quantity']==f['quantity'],'share change needs separate handling'
        start,end=b['fill_time'],f['fill_time'];entry_factor=cache.daily[s][start[:10]]['factor']
        vals=[0.];days=0
        for d in sorted(cache.daily[s]):
            if not start[:10]<=d<=end[:10]:continue
            if (s,d) not in cache.minutes:raise ValueError('holding minute missing '+s+d)
            days+=1
            for bar in cache.minutes[s,d]:
                if start<=bar['datetime']<end:
                    vals.append((bar['close']*bar['factor']/(b['price']*entry_factor)-1)*100)
        end_return=(f['price']*cache.daily[s][end[:10]]['factor']/(b['price']*entry_factor)-1)*100
        vals.append(end_return)
        trades.append(dict(symbol=s,buy_time=start,sell_time=end,holding_sessions=days,
          quantity=b['quantity'],entry_value=b['price']*b['quantity'],net_pnl=f['net_pnl'],
          fees=b['fees']+f['fees'],exit_reason=f['reason'],adjusted_exit_return_pct=end_return,
          max_minute_close_gain_pct=max(vals),min_minute_close_return_pct=min(vals),
          peak_to_exit_pp=max(vals)-end_return))
    assert not opened and not result['positions']
    net=sum(t['net_pnl'] for t in trades)
    assert abs(net-result['final']['realized_pnl'])<1e-6
    income=result['final']['dividend_income']-result['final']['dividend_tax']
    assert abs(net+income-(result['final']['equity']-30000))<1e-6
    losses=[t for t in trades if t['net_pnl']<0];wins=[t for t in trades if t['net_pnl']>=0]
    buckets={}
    for threshold in (2,3,5):
        groups=defaultdict(list)
        for t in trades:
            if t['net_pnl']>=0:k='net_profitable'
            elif t['max_minute_close_gain_pct']>=threshold:k='rose_then_net_loss'
            elif t['min_minute_close_return_pct']<=-threshold:k='no_threshold_gain_and_fell'
            else:k='narrow_range_net_loss'
            groups[k].append(t)
        buckets[str(threshold)]={k:dict(count=len(v),net_pnl=sum(t['net_pnl'] for t in v),median_holding_sessions=median(t['holding_sessions'] for t in v)) for k,v in groups.items()}
    exposure=[(d['equity']-d['cash']-d['dividend_receivable'])/d['equity'] for d in result['daily']]
    reasons=defaultdict(list)
    for t in trades:reasons[t['exit_reason']].append(t)
    summary=dict(trades=len(trades),net_winners=len(wins),net_losers=len(losses),winner_pnl=sum(t['net_pnl'] for t in wins),loser_pnl=sum(t['net_pnl'] for t in losses),trade_net_pnl=net,net_dividend=income,account_pnl=net+income,fees=result['metrics']['fees_paid'],before_fees_account_pnl=net+income+result['metrics']['fees_paid'],median_holding_sessions=median(t['holding_sessions'] for t in trades),mean_day_close_exposure_pct=mean(exposure)*100,flat_close_days=sum(abs(x)<1e-10 for x in exposure),daily_count=len(exposure),threshold_buckets=buckets,exit_reasons={k:dict(count=len(v),net_pnl=sum(t['net_pnl'] for t in v)) for k,v in reasons.items()},largest_losses=sorted(trades,key=lambda t:t['net_pnl'])[:5])
    return dict(source=str(path.relative_to(ROOT)),source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),summary=summary,trades=trades)

def main():
    OUT.mkdir(exist_ok=True);cache,bundle=prepare();print('BASE_CACHE_READY',flush=True)
    for folder in ('e1_rank_research','e1_conditions'):
        for p in sorted((ROOT/'reports'/folder).glob('minute_export_*.txt')):cache=merge_cache([cache,read_export(p)])
    output={}
    for name,path in [('original_E1',ROOT/'reports/exit_research/extension_2020/E1_cost1.0.json'),('filtered_E1',ROOT/'reports/e1_conditions/ma20_far10_cost1.0.json')]:
        output[name]=analyze(path,cache);print(name,json.dumps(output[name]['summary'],ensure_ascii=False),flush=True)
    output['interpretation']='Descriptive realized-trade diagnosis, normal costs only. Minute-close extrema exclude post-exit bars, include actual adjusted exit; not attainable optimal exits. 2/3/5 percent thresholds are explanatory sensitivity checks, not trading rules. Net trade PnL excludes cash dividends, which are reconciled separately. Holdings remain overlapping; cannot sum hypothetical peak profits as feasible portfolio return.'
    (OUT/'diagnosis.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf8')

if __name__=='__main__':main()
