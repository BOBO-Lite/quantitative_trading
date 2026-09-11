"""Report full account results and seal this independent research stage."""
import json,hashlib
from collections import Counter
from pathlib import Path
from statistics import mean
from capital_utilization import ROOT,OUT,save
from report_e1_asymmetric import decomposition
def read(p):return json.loads(p.read_text(encoding='utf8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    diagnosis=read(OUT/'diagnosis.json');states=read(OUT/'experiment_status.json')
    assert len(diagnosis)==len(states)==4 and all(r['parity'] for r in diagnosis)
    assert 'Ran 388 tests' in (OUT/'module_tests.txt').read_text(encoding='utf8')
    comparison=[];attribution={}
    for mode in ('FH','E1H'):
        for cost in (1.,1.5):
            old=read(ROOT/f'reports/e1_reentry_pair/{mode}_cost{cost}.json');new=read(OUT/f'{mode}_min3000_cost{cost}.json')
            a=decomposition(new,old);attribution[f'{mode}_{cost}']=a
            row=dict(mode=mode,cost=cost,old_return=old['metrics']['marked_return']*100,new_return=new['metrics']['marked_return']*100,old_dd=old['metrics']['max_minute_close_drawdown']*100,new_dd=new['metrics']['max_minute_close_drawdown']*100,delta_yuan=a['total_delta'],buys=sum(f['buy'] for f in new['fills']),flat_days=sum(d['flat_close'] for d in new['utilization_audit']),mean_exposure=mean((d['equity']-d['cash']-d['dividend_receivable'])/d['equity'] for d in new['daily'])*100)
            assert len(new['daily'])==730 and len(new['minute_curve'])==175200
            cash=30000+sum((-1 if f['buy'] else 1)*f['price']*f['quantity']-f['fees'] for f in new['fills'])+new['final']['dividend_income']-new['final']['dividend_tax']
            assert abs(cash-new['final']['cash'])<1e-6
            comparison.append(row)
    save('comparison.json',comparison);save('attribution.json',attribution)
    lines=['# 资金利用率诊断与恢复最低金额试验','', '2026-09-10。固定FH与相同恢复条件的E1H，先诊断再固定单一改动。2018—2020、3万元、正常及1.5倍成本。累计不是年化。规则见PROTOCOL.md。', '',
    '## 空仓日分解','', '|方案|成本|市场防守且空仓|既有股票池无合格日线信号|未进入有效定仓环节|定仓或组合限制|收盘持仓|', '|---|---:|---:|---:|---:|---:|---:|']
    for r in diagnosis:
        b=r['flat_buckets'];assert sum(b.values())==730
        lines.append(f"|{r['mode']}|{r['cost']}|{b.get('defensive_cash',0)}|{b.get('no_selected_signal',0)}|{b.get('no_intraday_confirmation_or_engine_block',0)}|{b.get('sizing_or_portfolio_block',0)}|{b.get('held',0)}|")
    lines+=['','FH正常的620个空仓日中553日为市场防守（89.19%）。这是状态归类，不是证明解除防守能赚多少钱。558个防守日中5日收盘仍有持仓，不能把防守日数和空仓日数混用。既有历史筛选覆盖不等于放松过滤后的全市场股票池。',
    'FH正常在收盘空仓日中，恢复趋势不足5日影响26个不同交易日；风险允许但低于4000元影响15日；整手或风险预算算不出数量影响5日。部分日有多种限制，三者不能直接相加。候选定仓次数不等于天数，也不等于成交数。', '',
    '## 完整账户试验','', '仅恢复状态的最低金额4000改3000，正常状态仍4000，其他信号与风险预算不变。', '',
    '|方案|成本|原累计|改后累计|原最大回撤|改后最大回撤|权益差|买入次数|空仓日|平均收盘仓位|', '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in comparison:lines.append(f"|{r['mode']}|{r['cost']}|{r['old_return']:+.2f}%|{r['new_return']:+.2f}%|{r['old_dd']:.2f}%|{r['new_dd']:.2f}%|{r['delta_yuan']:+.2f}元|{r['buys']}|{r['flat_days']}|{r['mean_exposure']:.2f}%|")
    lines+=['','逐笔新增、减少、改数量交易及期末估值差见attribution.json，全部与实际账户权益核对。不能仅凭增加交易或仓位认为成功。', '',
    '## 外部依据','', 'Pyfolio分拆仓位暴露与交易分析；Alphalens分拆因子收益、信息系数和换手；LEAN官方文档披露最小目标仓位可能不生成订单；Zipline #2732用户因买不起一个完整交易单位而停止交易。来源、原文和适用边界见EXTERNAL_REVIEW.md。未发现可直接证明这些修改能让本账户获得高收益的外部证据。', '',
    '## 验证与边界','', '4条观察器账户的完整输出与上轮逐项相等（包括成交、订单、决策、逐分钟权益），4条改动账户完整运行；388项模块测试通过，4组改动收益贡献与现金核对通过。研究账户均未使用未来价格决定交易。仍是已见历史探索，没有新的样本外或RQAlpha独立复验。原交易规则、实盘入口和封存研究代码未修改。']
    lines+=['', '## 本轮结论与下一项研究', '',
    '不采用恢复最低金额3000元替换4000元。四条路径中三条收益降低，四条最大回撤均扩大。FH正常成本买入由36次增至54次，空仓620日降至585日，平均收盘仓位7.38%升至8.69%，但累计收益8.17%降至4.44%。资金利用率提高不等于新增交易有正期望。保留FH原恢复机制及4000元门槛作为下一阶段研究对照；不会恢复旧的12%永久停止开仓规则。',
    'FH正常成本权益减少1118.36元：新增或改数量交易合计-2577.77元，移除或改数量的原交易贡献+1389.33元，分红及未平仓估值差+70.08元。22笔严格匹配交易作为相同部分单独核对。这里是实际交易路径差额分解，不是把所有损益都归因于新增18次买入。',
    'FH高成本路径权益反而增加257.52元，但新增或改数量交易仍合计-769.28元，主要由移除或改数量的原交易贡献+1026.81元抵消。两档成本会改变权益、整手数量、恢复触发和后续交易集合，不能把高成本路径的较高收益解读为手续费提高能赚钱。该变化未显示跨成本稳健改善。',
    '下一项先针对市场防守的边界状态：553个防守且空仓日中，432日基准收盘不高于60日均线，121日虽高于60日均线但不满足收盘价>20日均线>60日均线的完整条件。分组使用当时已知的前一交易日数据。先核验这121日对应历史股票筛选覆盖，再固定一个恢复/过渡条件与FH完整配对回放；不同时放宽风险预算、最低金额和退出规则。上述天数只描述过滤状态，不证明放开后会赚钱。',
    '此前R2取消市场防守强制退出的正常/压力累计为-2.59%/-3.61%，使用原E1和旧停止开仓规则，不能当作FH本轮直接对照。但它提醒我们，空仓多并不足以支持删除市场防守。']
    (OUT/'RESULT.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps(comparison,ensure_ascii=False))
if __name__=='__main__':main()
