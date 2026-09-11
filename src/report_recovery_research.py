"""披露所有预登记路径；不把缺数据的中途状态当作全年收益。"""
import json
from datetime import date
from recovery_research import OUT,PRIOR

def main():
    rows=[]
    for variant in ('R0','R1','R2'):
        for cost in (1.,1.5):
            path=OUT/f'{variant}_cost{cost}.json'
            if not path.exists():raise ValueError('仍有未完成路径，不能输出完整收益表')
            r=json.loads(path.read_text(encoding='utf8'))
            if len(r['daily'])!=730 or len(r['minute_curve'])!=175200:raise ValueError('日历覆盖不完整')
            ref=json.loads((PRIOR/f'E1_cost{cost}.json').read_text(encoding='utf8'))
            if variant=='R0' and r!=ref:raise ValueError('基准完整结果不一致')
            year=[d for d in r['daily'] if d['date'].startswith('2020')]
            prior=next(d for d in r['daily'] if d['date']=='2019-12-31')
            rows.append(dict(variant=variant,cost=cost,return_total=r['metrics']['marked_return'],
                cagr=(r['final']['equity']/30000)**(365.25/(date(2020,12,31)-date(2018,1,2)).days)-1,
                return_2020=r['final']['equity']/prior['equity']-1,maximum_drawdown=r['metrics']['max_minute_close_drawdown'],
                equity=r['final']['equity'],equity_delta_vs_baseline=r['final']['equity']-ref['final']['equity'],
                fees=r['metrics']['fees_paid'],fills=len(r['fills']),fills_2020=sum(f['fill_time'].startswith('2020') for f in r['fills']),
                average_exposure_2020=sum((d['equity']-d['cash']-d['dividend_receivable'])/d['equity'] for d in year)/len(year),
                cash_only_ge_12_days_2020=sum(d['drawdown']>=.12 and abs(d['equity']-d['cash'])<1e-6 for d in year),
                hard_halt_days=sum(d['halted'] for d in r['daily']),held_symbols=sorted(r['positions']),
                last_fill=r['fills'][-1]['fill_time'] if r['fills'] else None))
    (OUT/'comparison.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
    lines=['# RECOVERY1 暂停恢复与市场防守退出结果','',
        '3万元连续2018-01-02—2020-12-31，730交易日，两档成本均保留。历史峰值与回撤不重置。R0为原E1收盘确认退出；R1只增加保守恢复开仓；R2只取消市场防守对已有持仓的强制退出。具体规则见PROTOCOL.md。','',
        '|方案|成本倍数|累计收益|年化|2020收益|最大分钟收盘回撤|2020成交笔数|',
        '|---|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        lines.append(f"|{r['variant']}|{r['cost']}|{r['return_total']:.2%}|{r['cagr']:.2%}|{r['return_2020']:.2%}|{r['maximum_drawdown']:.2%}|{r['fills_2020']}|")
    lines+=['','恢复允许增加风险暴露；15%为硬停止触发阈值，不是跳空或涨跌停条件下损失保证。即使结果超过15%也如实披露，不截断曲线。公司行动与分钟数据不完整会阻止对应路径，未通过不能认定绩效完成。','',
        '本组使用已经见过的历史，不证明样本外有效。R0必须完整复现；新增路径的独立RQAlpha核对另见rqalpha_parity.json，是共用交易意图的执行核验，不是独立预测检验。两项改动没有叠加，也没有根据结果搜索阈值。','']
    (OUT/'RESULT.md').write_text('\n'.join(lines),encoding='utf8')
    print(json.dumps(rows,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
