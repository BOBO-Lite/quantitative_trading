"""完整披露收紧追价的两档结果及组合路径差异。"""
import json
from datetime import date
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/entry_research'

def main():
    results=[]
    for cost in (1.,1.5):
        original=json.loads((OUT/f'B0_cost{cost}.json').read_text(encoding='utf8'))
        frozen=json.loads((ROOT/f'reports/exit_research/extension_2020/E0_cost{cost}.json').read_text(encoding='utf8'))
        if original!=frozen:raise ValueError('买点基准完整输出不一致')
        base_keys={(f['symbol'],f['fill_time']) for f in original['fills'] if f['buy']}
        for variant in ('B0','B1'):
            r=json.loads((OUT/f'{variant}_cost{cost}.json').read_text(encoding='utf8'))
            if len(r['daily'])!=730 or len(r['minute_curve'])!=175200:raise ValueError('未完成三年连续回放')
            keys={(f['symbol'],f['fill_time']) for f in r['fills'] if f['buy']}
            annual=(r['final']['equity']/30000)**(365.25/(date(2020,12,31)-date(2018,1,2)).days)-1
            results.append(dict(variant=variant,cost=cost,total_return=r['metrics']['marked_return'],cagr=annual,
                maximum_minute_drawdown=r['metrics']['max_minute_close_drawdown'],fees=r['metrics']['fees_paid'],
                fills=len(r['fills']),entries=len(keys),baseline_entries=len(base_keys),common_entry_times=len(keys&base_keys),
                entry_times_only_in_variant=len(keys-base_keys),equity=r['final']['equity'],
                equity_difference_from_baseline=r['final']['equity']-original['final']['equity'],held_symbols=sorted(r['positions']),
                fills_2020=sum(f['fill_time'].startswith('2020') for f in r['fills'])))
    (OUT/'comparison.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
    lines=['# ENTRY1 收紧追价完整结果','',
        '2018-01-02—2020-12-31，730交易日，3万元连续账户；固定原TECH1卖点和风险规则，只将突破确认/委托追价上限从前收盘价+4%收紧到+2%。初始保护价与定仓仍按同一公式由委托限价计算，实际水平和后续资金路径可能改变。','',
        '|买点|成本倍数|累计收益|年化|最大分钟收盘回撤|成交笔数|费用|',
        '|---|---:|---:|---:|---:|---:|---:|']
    for r in results:
        lines.append(f"|{r['variant']}|{r['cost']}|{r['total_return']:.2%}|{r['cagr']:.2%}|{r['maximum_minute_drawdown']:.2%}|{r['fills']}|{r['fees']:.2f}|")
    lines+=['','B0原买点两档与E0完整输出逐项相同。B1两档的收益都低于各自B0，回撤也略大，因此本实验不支持把2%追价上限推广为有效改进。全部期末空仓、2020无新增成交；前期回撤与风险预算约束继续限制开仓，不能把2020空仓当作买点经过活跃牛市验证。','',
        '入场时点以股票代码+真实成交时间匹配；不把组合净值差当同一笔交易的因果差异：','']
    for r in results:
        if r['variant']=='B1':
            lines.append(f"- 成本{r['cost']}：原买点{r['baseline_entries']}次、收紧后{r['entries']}次；共同买入时点{r['common_entry_times']}次，收紧版独有时点{r['entry_times_only_in_variant']}次；期末权益相对原版差{r['equity_difference_from_baseline']:.2f}元。")
    lines+=['','确认条件虽更窄，组合交易数不一定更少：先前入场、退出、现金和风险预算会影响后续能否买入。这里没有将未成交机会的未来涨幅计入策略收益，也没有用最优成本档替代全表。','',
            '本组历史已经用于开发与比较，不是真正未见未来。独立RQAlpha账户核对另见 rqalpha_parity.json；通过只说明同一意图下的撮合和账户一致，不证明选股盈利。未修改冻结S1、正式日线或实际持仓。','']
    (OUT/'RESULT.md').write_text('\n'.join(lines),encoding='utf8')
    print(json.dumps(results,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
