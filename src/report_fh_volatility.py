"""Risk/return tradeoff report for the pre-registered FH adaptation."""
import json,hashlib
from statistics import mean
from pathlib import Path
from fh_volatility import ROOT,OUT,save
from report_e1_asymmetric import decomposition

def read(p):return json.loads(p.read_text(encoding='utf8'))

def main():
    statuses=read(OUT/'status.json')
    assert len({(r['mode'],r['cost']) for r in statuses})==6
    rows=[];attrs={}
    for cost in (1.,1.5):
        baseline=read(OUT/f'BASE_cost{cost}.json')
        original=read(ROOT/f'reports/e1_reentry_pair/FH_cost{cost}.json')
        assert baseline==original
        for mode in ('BASE','DYNAMIC','CONSTANT'):
            r=read(OUT/f'{mode}_cost{cost}.json');daily=r['daily']
            a=decomposition(r,baseline);attrs[f'{mode}_{cost}']=a
            for key,field in [('daily','date'),('minute_curve','datetime'),('fills','fill_time')]:
                assert [x for x in r[key] if x[field]<'2020-01-01']==[x for x in baseline[key] if x[field]<'2020-01-01']
            prior=[x for x in daily if x['date']<'2020-01-01'][-1]['equity']
            future=[x for x in daily if x['date']>='2020-01-01']
            curve=[x for x in r['minute_curve'] if x['datetime']>='2020-01-01']
            peak=prior;dd2020=0
            for x in curve:peak=max(peak,x['equity']);dd2020=max(dd2020,1-x['equity']/peak)
            events=read(OUT/f'{mode}_cost{cost}_events.json')
            cash=30000+sum((-1 if f['buy'] else 1)*f['price']*f['quantity']-f['fees'] for f in r['fills'])+r['final']['dividend_income']-r['final']['dividend_tax']
            assert abs(cash-r['final']['cash'])<1e-6
            row=dict(mode=mode,cost=cost,return_pct=r['metrics']['marked_return']*100,
                cagr_three_year_approx_pct=((1+r['metrics']['marked_return'])**(1/3)-1)*100,
                drawdown_pct=r['metrics']['max_minute_close_drawdown']*100,
                return_2020_pct=(daily[-1]['equity']/prior-1)*100,drawdown_2020_local_peak_pct=dd2020*100,
                delta_yuan=a['total_delta'],buys=sum(f['buy'] for f in r['fills']),
                buys_2020=sum(f['buy'] and f['fill_time']>='2020-01-01' for f in r['fills']),
                exposure_2020_pct=mean((d['equity']-d['cash']-d['dividend_receivable'])/d['equity'] for d in future)*100,
                flat_days_2020=sum(abs(d['unrealized_pnl'])<1e-12 and abs(d['equity']-d['cash']-d['dividend_receivable'])<1e-6 for d in future),
                recovery_allowed_events=sum(e.get('event')=='latched_recovery_allowed' for e in events),
                hard_halted=any(d['halted'] for d in daily))
            rows.append(row)
    save('comparison.json',rows);save('attribution.json',attrs)
    lines=['# FH-V1 波动管理风险预算适配结果','',
    '2026-09-10。3万元连续2018—2020账户，2018—2019完全沿用FH，仅2020启用已登记的新买入风险预算。不是美国指数收益，不是原论文完整月度持仓再平衡，也不是未见样本外。', '',
    '## 同账户结果', '',
    '|方案|成本|三年累计|三年近似CAGR|全期分钟回撤|2020收益|2020局部峰值分钟回撤|相对FH权益差|',
    '|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:lines.append(f'|{r["mode"]}|{r["cost"]}|{r["return_pct"]:+.2f}%|{r["cagr_three_year_approx_pct"]:+.2f}%|{r["drawdown_pct"]:.2f}%|{r["return_2020_pct"]:+.2f}%|{r["drawdown_2020_local_peak_pct"]:.2f}%|{r["delta_yuan"]:+.2f}元|')
    lines+=['','2020局部峰值回撤只为分期统计，从2019末权益起计算；账户实际风控仍沿用完整历史高点，没有重置。CAGR按三年近似；2020收益由连续账户2019末权益到2020末计算。', '',
    '|方案|成本|2020买入次数|2020平均收盘仓位|2020空仓日|恢复允许事件|是否硬停止|',
    '|---|---:|---:|---:|---:|---:|---|']
    for r in rows:lines.append(f'|{r["mode"]}|{r["cost"]}|{r["buys_2020"]}|{r["exposure_2020_pct"]:.2f}%|{r["flat_days_2020"]}|{r["recovery_allowed_events"]}|{r["hard_halted"]}|')
    lines+=['','恢复允许事件是定仓许可记录，不等于真实恢复成交次数。BASE原FH；DYNAMIC使用上月波动；CONSTANT固定为校准期平均预算乘数64.53%。实际平均仓位可能不同，因此固定组不是事后精确配平暴露。', '',
    '## 范围与解释', '',
    '降低回撤可以改善资金承受能力和风险调整表现，也可能通过减少账户限仓间接改善后续收益，但降低回撤本身不等于最终收益增加。须同时看保留收益、减少亏损、错失机会、实际暴露和成本。',
    '这里仅改新买入风险预算，未对存量持仓做月度减仓；也没有取消FH市场防守。若原规则长期不允许开仓，波动预算不会凭空创造新的买点。美国市场约8%的理论年化来自不同资产行情、持仓和现金利率，不能直接当本账户回报。',
    '4项新增测试通过；2条原账户完整一致；6条账户现金核对，4条改动的2018—2019日账本、逐分钟权益和成交均与对应原FH相同。逐笔损益差额全部与最终账户核对，见attribution.json。所有参数先登记，不根据2020表现追加参数。',
    '最终候选决定见本目录DECISION.md。本阶段属于风险管理适配研究；保持合理恢复开仓要求，不接实盘。']
    (OUT/'RESULT.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps(rows,ensure_ascii=False))

if __name__=='__main__':main()
