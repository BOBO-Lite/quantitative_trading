"""从完成的连续回放和真实RQ账户核验生成研究结论，不把暂停外推冒充活跃回测。"""
import hashlib,json
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'reports/simple_research';OUT=BASE/'continuous_2018_2019'

def main():
    statuses=json.loads((OUT/'run_status.json').read_text(encoding='utf8'))
    if len(statuses)!=2 or any(r['status']!='COMPLETED' for r in statuses):raise ValueError('连续回放未全部完成')
    parity=json.loads((OUT/'rqalpha_parity.json').read_text(encoding='utf8'))
    if any(r['status']!='PASS_CONTINUOUS_EXECUTION_PARITY' for r in parity):raise ValueError('连续独立账户未通过')
    benchmark=pd.read_csv(ROOT/'reports/s2_research/long_history/research_benchmark.csv').set_index('date')
    bm=float(benchmark.loc['2019-12-31','close']/benchmark.loc['2017-12-29','close']-1)
    lines=['# TECH1.0 连续研究结论（2026-09-09）','',
      '**工程账本核验通过；当前策略尚不支持上线。**','',
      '固定规则、30000元现金起步，连续回放2018-01-02至2019-12-31共487个交易日，没有年度重置资金。两档均进入12%回撤后的空仓暂停；没有实际下单，也没有改动用户真实持仓。','',
      '| 口径 | 基准成本 | 1.5倍成本压力 |','|---|---:|---:|']
    rs=[json.loads((OUT/f'cost{c}.json').read_text(encoding='utf8')) for c in (1.,1.5)]
    metrics=[('期末权益',[f"{r['final']['equity']:.2f}元" for r in rs]),('区间收益',[f"{r['metrics']['marked_return']:.2%}" for r in rs]),('最大分钟收盘回撤',[f"{r['metrics']['max_minute_close_drawdown']:.2%}" for r in rs]),('完整买卖次数',[str(sum(not f['buy'] for f in r['fills'])) for r in rs]),('实际计入的交易手续费',[f"{r['metrics']['fees_paid']:.2f}元" for r in rs]),('最后一笔成交日期',[r['fills'][-1]['fill_time'][:10] for r in rs])]
    lines += ['| '+name+' | '+' | '.join(values)+' |' for name,values in metrics]
    lines += ['',f'同期中证500价格指数收益为{bm:.2%}，不含指数分红。策略两档均计入140元现金分红和28元红利税；滑点已进入成交价。',
      '', '压力成本不是同一批交易额外扣费：100股整数、最低交易金额、资金/风险预算和暂停时点会改变后续订单路径。基准25笔、压力37笔，不能选择压力档作为“最优参数”，也不能宣称更高手续费改善策略。',
      '',f"RQAlpha真实事件、订单和账户逐分钟核对{sum(r['minute_comparisons'] for r in parity)}次，124笔成交，最大现金/权益差{max(r['maximum_cash_or_equity_difference'] for r in parity):.3g}元。共用订单意图，独立验证成交/费用/账户，不等于独立复现所有选股。",'',
      '## 暂停状态与研究边界','',
      '两档期末均无持仓、无预留资金、无应收分红，仍高于12%回撤暂停阈值。现有规则没有自动重置峰值或恢复交易条款；没有外部入金/规则变更时，空仓净值不会自行修复。继续同一固定规则不会产生新交易证据。未把暂停后的现金状态外推冒充完整2018—2022活跃回测。',
      '', '2020全年日线筛选已通过：102个允许开仓的信号日、3616个符合既定入场风险条件的股票日，错误0；尚未完成2020组合回放。2021以后未完成本策略全池验证。原S2正式实验仍为0/8。',
      '', '本轮结论是基准方案未显示足够的扣费后正收益证据，不能据此上线；不是证明所有技术策略无效，也不需要用户真实买卖来补历史验证。不同年份、不同回撤状态和成本的结果均保留。',
      '', '## 实际修复与证据','',
      '- 日线技术候选独立重算，保留历史股票池和逐股排除原因；未独立重算全部非候选。',
      '- MA20与MA60相等时的浮点误判已修复，保留被拒绝的2018原始日志与真实边界夹具。',
      '- 历史代码000043→001914依据2019-12-16实施公告桥接；原始OHLC/量额/状态完全对齐，接口因子与涨跌停差异另行记录。',
      '- 公司行动只核算首次可能持仓之后的权益；送转在实际登记持仓时停止，不能用两个月后的送转否决已结束的交易。',
      '- 只有统计比例不同、全部交易相关字段一致的重复分红行才合并；真实冲突、未知事件仍停止。',
      '- 分段日志按请求集合、分包长度和SHA-256核验；预取仅补数据，不决定是否买入。',
      '', '下一版范围建议见 `../NEXT_RESEARCH_OPTIONS.md`。当前版本保持研究用途，不修改原实盘协议。']
    (OUT/'RESULT.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    proof=[]
    for cost,r in zip((1.,1.5),rs):
        f=r['final'];flat=not r['positions'] and all(f[k]==0 for k in ('reserved_cash','dividend_receivable','unrealized_pnl')) and f['cash']==f['equity']
        paused=r['daily'][-1]['drawdown']>=.12
        if not flat or not paused:raise ValueError('不能声明空仓暂停')
        proof.append(dict(cost=cost,flat=flat,entry_paused=paused,end_drawdown=r['daily'][-1]['drawdown'],last_fill=r['fills'][-1]['fill_time'],automatic_recovery_defined=False))
    (OUT/'pause_proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf8')
    files=[ROOT/'src/simple_strategy_rules.py',ROOT/'src/research_portfolio.py',ROOT/'src/simple_minute_cache.py',ROOT/'src/simple_corporate_events.py',ROOT/'src/simple_history_replay.py',BASE/'PROTOCOL.md']+list(OUT.glob('cost*.json'))+[OUT/'rqalpha_parity.json',OUT/'corporate_events.json',OUT/'corporate_export.txt']
    files += [ROOT/'src/report_simple_continuous.py', ROOT/'src/report_simple_research.py',
              OUT/'RESULT.md', OUT/'pause_proof.json', OUT/'run_status.json',
              BASE/'module_tests.txt', BASE/'core_tests.txt', BASE/'framework_tests.txt',
              BASE/'integrity.json', BASE/'platform_restore_verification.json']
    manifest={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    (OUT/'manifest.json').write_text(json.dumps(dict(status='COMPLETED_WITH_NO_GO_FOR_DEPLOYMENT',sha256=manifest),ensure_ascii=False,indent=2),encoding='utf8')
    print('continuous report, pause proof and manifest written')

if __name__=='__main__':main()
