"""Publish the frozen external evidence gate, including unsuccessful outcomes."""
import hashlib
import json
from pathlib import Path
from external_volatility_gate import ROOT, OUT, save


def read(name):
    return json.loads((OUT/name).read_text(encoding='utf8'))


def main():
    results=read('results.json')
    lookup={(r['period'],r['variant']):r for r in results}
    audit=read('replication_audit.json')
    intervals=read('uncertainty.json')
    inventory=read('history_exposure_inventory.json')
    lines=['# EG1：外部正向证据复算与候选准入结果','',
    '2026-09-10。已完成历史暴露审计、原始论文核查、规则预登记及公开数据固定复算。本轮不是新的A股或FH回测。', '',
    '## 决定', '',
    '不将这项波动控制直接接入FH，也不把它作为提高绝对收益的替代方案。公开论文历史期内的风险调整改善方向能复算；论文公开后固定区间的无杠杆市场版本主要降低回撤，收益和夏普都没有超过持续市场暴露。保留为风险管理参考，不追加窗口、目标波动或均线变体。',
    '这不是证明波动管理对所有目标无效，也不否定风险更低的组合价值。两个组合承担的风险不同，不能仅凭低风险组合绝对收益较低便断言其无用。本轮结论是：没有证据支持其同时满足当前提高收益的目标并直接替换本项目规则。', '',
    '## 历史范围审计', '',
    f'对既有研究Markdown提取了{len(inventory)}个文件、{sum(len(r["hits"]) for r in inventory)}条历史范围/绩效相关记录，保留文件摘要、行号及原文。自动检索用于定位，不能单独证明一个时期从未被观察。', '',
    '|既有研究|已接触范围|新的检验如何命名|','|---|---|---|',
    '|E1/F/FH及退出、恢复研究|2018—2020多次重复|发现/调参历史，不能重新称盲测|',
    '|ETF及多资产连续回放|2018—2026-09-04|2021年后市场状态已经被观察|',
    '|S2原协议|明确把2023—2026标为已见|不能推翻旧披露，把这些年改称完全未见|',
    '|2021—2025的FH个股完整路径|已查报告未找到完成证据|可做固定规则跨时期迁移检验，但不是全项目盲测|',
    '|更早或未来A股数据|本轮没有证明有完全洁净历史|需先登记、审计；未来观察也必须先冻结规则|', '',
    '## 为什么选这个外部机制', '',
    'Moreira & Muir《Volatility Managed Portfolios》，NBER w22208。式(1)/(2)按前一个月日收益实现方差的倒数调整下一月风险；表4/5还检验权重上限1及费用。这比多空动量直接移植，更接近仅做多、小账户可考虑的风险管理机制。',
    '原文表4的无杠杆市场行报告：年化均值5.61%、alpha 2.12%，10bps成本后alpha 1.93%。这些是论文口径，不是本项目账户收益或年化承诺。原文并未宣称不加杠杆必然提高绝对收益。',
    '来源：https://www.nber.org/papers/w22208 。实际复算用French公开市场及动量日/月因子，先在1927—2015固定归一化常数，再带到2017—2025；2016为事先登记的公开过渡期。规则见PROTOCOL.md，协议摘要在任何本轮绩效统计前封存。', '',
    '## 固定复算结果', '',
    '下表为美国理论市场组合＋美国无风险利率，按月计算。基准是French广泛股票市场，不是标普500ETF，也不是A股。理论可分割持仓，不含本账户整手、最低佣金与成交限制；不得与FH的3万元账户回测直接比较。', '',
    '|时期|规则|理论复合年化|月末最大回撤|超额收益夏普|平均风险资产权重|',
    '|---|---|---:|---:|---:|---:|']
    labels={'market':'持续市场暴露','market_managed':'逆方差，允许杠杆','market_capped':'逆方差，最多100%','market_capped_fee10':'最多100%，10bps变动成本','market_capped_fee14':'最多100%，14bps变动成本'}
    for period,title in [('paper_period','1927—2015'),('post_publication','2017—2025')]:
        for variant,label in labels.items():
            r=lookup[period,variant]
            lines.append(f'|{title}|{label}|{r["theoretical_total_cagr_pct"]:.2f}%|{r["monthly_close_max_drawdown_pct"]:.2f}%|{r["sharpe"]:.3f}|{r["weight_mean"]*100:.2f}%|')
    c=lookup['post_publication','market_capped']; b=lookup['post_publication','market'];ci=intervals['market_capped']
    lines+=['',f'无杠杆主候选后续108个月，夏普差{c["sharpe"]-b["sharpe"]:+.3f}，成对12个月循环区块bootstrap的95%区间[{ci["low95"]:+.3f}, {ci["high95"]:+.3f}]。区间跨零，没有提供明确正向优势证据；它也不是证明真实优势必然为负。固定2000次、固定种子，未根据结果换方法。',
    '预先划定的2017—2020与2021—2025两段结果全部保留。无杠杆版前一段夏普低于基准，后一段高于基准，两段复合年化都低于基准。不单独展示后一段作为成功。', '',
    '## 动量核验与适配边界', '',
    '|时期|静态动量夏普|逆方差动量夏普|静态年化算术超额均值|逆方差年化算术超额均值|',
    '|---|---:|---:|---:|---:|']
    for p,label in [('paper_period','1927—2015'),('post_publication','2017—2025')]:
        a,b=lookup[p,'momentum'],lookup[p,'momentum_managed']
        lines.append(f'|{label}|{a["sharpe"]:.3f}|{b["sharpe"]:.3f}|{a["annual_arithmetic_excess_pct"]:.2f}%|{b["annual_arithmetic_excess_pct"]:.2f}%|')
    lines+=['', '动量的风险调整改善方向仍可见，但后续算术均值下降。它是买赢家、卖空输家的因子，不是我们能直接执行的仅做多账户，未扣底层换手、借券等成本。算术超额均值不是复合年化，不从因子序列推算本账户能赚多少钱。',
    '市场无上限版在后续最高权重4.26倍，原研究期复算甚至出现16.87倍；不符合本项目无新增杠杆的研究边界。不能用它的历史表现解释个人账户可实现收益。', '',
    '## 数据、执行与统计限制', '',
    '- 使用French当前202607 CRSP版本；官方说明自2025年发布起由FIZ改为CIZ，分红再投资口径改变，旧历史还可能被修订。因此本轮是公开机制复算，不是原论文旧数据精确复现，也不是真实前瞻记录。',
    '- 上月日收益去均值平方和使用真实日数，论文公式以22天简写。每日方差和官方月因子结合，不自行把日动量因子复利冒充月动量。',
    '- 归一化常数只使用1927—2015。该期是样本内尺度归一化；后续不重新校准，不使用当月方差决定当月仓位。',
    '- 10/14bps只是论文式目标权重变化成本；未模拟权重漂移、具体ETF手续费、T+1、整手和信号可执行延迟。理论RF为美国短期无风险利率，不代表A股闲置现金同等生息。',
    '- 2017—2025仅108个月，子区间48/60个月；bootstrap是有限样本描述，未声称校正本项目此前所有试验，也未新算Alpha显著性。', '',
    '## 验证及后续准入', '',
    f'6项针对性测试通过，覆盖缺失值、重复日期、百分数/年度行解析、跨年滞后、后续数据不改变训练常数及复利回撤。对{audit["scalar_reconstructed_returns"]}个管理收益逐一用标量公式复算，最大差{audit["max_scalar_error"]:.3g}。完整日期、仓位、成本和全部28组指标均保存。',
    '这项机制不进入FH收益优化队列。下一类候选应优先检查仅做多的选股或行业相对强度是否有可复现正向收益证据，再考虑最少A股适配；不能再把一个风险管理论文当作选股优势证明。暂不为寻找正数继续追加本机制变体。用户关于合理恢复开仓的最终要求保持不变。']
    (OUT/'RESULT.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    previous=json.loads((ROOT/'reports/capital_utilization/integrity.json').read_text(encoding='utf8'))
    progress={'README.md','SYSTEM_STATUS.md','CHANGELOG.md'}
    for key in ('files_sha256','production_inputs_sha256'):
        for name,h in previous[key].items():
            if name not in progress:assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==h,name
    note='> 2026-09-10外部证据准入阶段完成：已审计历史暴露；固定复算波动管理论文，原历史风险调整改善可复现，2017—2025无杠杆版主要降回撤、未提高绝对收益，不接FH、不追加该机制参数。2021年后不能称全项目盲测。详见[EG1证据准入](reports/evidence_gate/RESULT.md)。\n\n'
    for name in progress:
        p=ROOT/name;t=p.read_text(encoding='utf8')
        if not t.startswith(note):p.write_text(note+t,encoding='utf8')
    paths=[p for p in OUT.iterdir() if p.is_file() and p.name!='integrity.json']
    paths += [ROOT/'src/external_volatility_gate.py',ROOT/'src/report_external_volatility_gate.py',ROOT/'tests/test_external_volatility_gate.py']+[ROOT/n for n in progress]
    save('integrity.json',dict(status='EXTERNAL_EVIDENCE_GATE_COMPLETE_NO_FH_ADOPTION',tests_passed=6,
        files_sha256={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        production_inputs_sha256=previous['production_inputs_sha256'],production_changed=False,new_a_share_backtests=0,
        predecessor_preserved_except_progress=True,live_orders=False))
    print('EVIDENCE_GATE_REPORT_COMPLETE',len(paths),'files')


if __name__=='__main__':main()
