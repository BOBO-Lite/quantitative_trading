"""ENTRY1：冻结原始退出，仅收紧突破追价。"""
import json
import argparse
from pathlib import Path
import simple_strategy_rules as base
from exit_research import ExitRules

class EntryRules(ExitRules):
    def __init__(self, entry_variant):
        super().__init__('E0')
        if entry_variant not in ('B0', 'B1'):
            raise ValueError('未登记买入版本')
        self.entry_variant = entry_variant

    def entry_cap(self, row, route):
        if self.entry_variant == 'B0':
            return base.entry_cap(row, route)
        return int((row['raw_close'] * 1.02 + 1e-10) * 100) / 100

    def entry_confirmed(self, signal, minute, route, day_open, day_vwap):
        ok = base.entry_confirmed(signal, minute, route, day_open, day_vwap)
        return ok and (self.entry_variant == 'B0' or minute['close'] <= self.entry_cap(signal, route))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--interactive',action='store_true')
    parser.add_argument('--variants',nargs='+',choices=['B0','B1'],default=['B0','B1'])
    args=parser.parse_args()
    from exit_extension_research import prepare, OUT as EXITS, read_export
    from simple_history_replay import merge_cache
    from simple_minute_cache import MissingMinutes
    from research_portfolio import run_bundle
    from s2_strategy_rules import Policy
    out=EXITS.parents[1]/'entry_research'
    cache,bundle=prepare()
    for path in sorted(out.glob('minute_export_*.txt')):
        supplement=read_export(path)
        # 本组仅改变追价，上游候选和公司行动范围不变。
        if not set(supplement.daily)<=set(cache.daily): raise ValueError('新增股票超出研究数据范围')
        cache=merge_cache([cache,supplement])
    statuses=[];missing=[];loaded=set(out.glob('minute_export_*.txt'))
    print('ENTRY_INPUTS_VERIFIED',flush=True)
    for variant in args.variants:
        for cost in (1.,1.5):
          while True:
            try:
                result=run_bundle(bundle,Policy(cost_multiplier=cost),rules=EntryRules(variant),minute_loader=cache.load)
                if variant=='B0':
                    original=json.loads((EXITS/f'E0_cost{cost}.json').read_text(encoding='utf8'))
                    if result!=original: raise ValueError('B0与原E0完整输出不一致')
                (out/f'{variant}_cost{cost}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
                row=dict(variant=variant,cost=cost,status='COMPLETED',metrics=result['metrics'],final=result['final'],fills=len(result['fills']))
            except MissingMinutes as exc:
                if args.interactive:
                    (out/'missing_minutes.json').write_text(json.dumps(exc.requests,ensure_ascii=False,indent=2),encoding='utf8')
                    print('AWAIT_ENTRY_MINUTES '+json.dumps(exc.requests,ensure_ascii=False),flush=True)
                    if input().strip()!='continue':raise ValueError('未完成路径已停止，不产生全段绩效')
                    new=set(out.glob('minute_export_*.txt'))-loaded
                    if not new:raise ValueError('没有新增真实行情')
                    for path in sorted(new):
                        supplement=read_export(path)
                        if not set(supplement.daily)<=set(cache.daily):raise ValueError('增量股票超出研究范围')
                        cache=merge_cache([cache,supplement])
                    loaded |= new
                    continue
                missing.extend(exc.requests)
                row=dict(variant=variant,cost=cost,status='MISSING_MINUTES',requests=exc.requests)
            except ValueError as exc:
                row=dict(variant=variant,cost=cost,status='BLOCKED_REPLAY',error=str(exc))
            statuses.append(row)
            (out/'run_status.json').write_text(json.dumps(statuses,ensure_ascii=False,indent=2),encoding='utf8')
            print(json.dumps(row,ensure_ascii=False),flush=True)
            break
    unique=[dict(symbol=s,date=d) for s,d in sorted({(r['symbol'],r['date']) for r in missing})]
    (out/'missing_minutes.json').write_text(json.dumps(unique,ensure_ascii=False,indent=2),encoding='utf8')

if __name__=='__main__': main()
