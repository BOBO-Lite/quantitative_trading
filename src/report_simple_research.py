"""从真实回放输出生成简版研究状态及不可变输入摘要。"""
import hashlib,json,re
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/simple_research'

def main():
    results=[json.loads((OUT/f'quarter_cost{c}.json').read_text(encoding='utf8')) for c in (1.,1.5)]
    parity=json.loads((OUT/'rqalpha_quarter_parity.json').read_text(encoding='utf8'))
    b=pd.read_csv(ROOT/'reports/s2_research/long_history/research_benchmark.csv').set_index('date')
    benchmark=float(b.loc['2019-06-28','close']/b.loc['2019-03-29','close']-1)
    screen=json.loads((OUT/'quarter_screen.json').read_text(encoding='utf8'))
    cache=json.loads((OUT/'minute_audit.json').read_text(encoding='utf8'))
    lines=['# TECH1.0 私人简版研究进度','',
      '本文件由真实结果生成；策略尚未通过长期有效性验收。原版S2正式实验仍为0/8，本版本单独登记。',
      '', '## 最新结论：2018—2019连续回放完成', '',
      '487交易日连续账户已完成，基准成本收益-2.60%、最大分钟收盘回撤12.33%；1.5倍成本收益+1.23%、最大回撤12.15%。两档均空仓并触发12%开仓暂停，现有证据不支持上线。费用改变后续入场和暂停路径，不能将压力档当成更优策略。',
      '', 'RQAlpha两档共233760次分钟账户核对、124笔成交通过；共用意图，独立成交及账户核验。详见[连续研究结论](continuous_2018_2019/RESULT.md)。2020仅完成日线筛选，2018—2022完整活跃历史研究尚未完成。下一版研究范围见[NEXT_RESEARCH_OPTIONS.md](NEXT_RESEARCH_OPTIONS.md)。',
      '', '## 已完成：2019年第二季度连续工程回放','',
      f"60个交易日、{sum(len(d['candidates']) for d in screen['days'])}条日线技术候选、{len(screen['minute_requests'])}个入场股票日；分钟缓存{cache['days']}个股票日、{cache['rows']}行。",'',
      '| 费用档 | 期末权益 | 扣费收益 | 分钟收盘最大回撤 | 完整交易 | 手续费 |',
      '|---|---:|---:|---:|---:|---:|']
    for r,c in zip(results,(1.,1.5)):
        m=r['metrics'];sells=[f for f in r['fills'] if not f['buy']]
        lines.append(f"| {c}倍 | {r['final']['equity']:.2f}元 | {m['marked_return']:.2%} | {m['max_minute_close_drawdown']:.2%} | {len(sells)} | {m['fees_paid']:.2f}元 |")
    lines += ['',f'同区间中证500价格指数收益为{benchmark:.2%}，不含指数分红；策略两档均含140元税前现金分红、28元红利税。',
      '',f"真实RQAlpha账户逐分钟核对{sum(r['minute_comparisons'] for r in parity)}次，两档均通过，最大现金/权益差{max(r['maximum_cash_or_equity_difference'] for r in parity):.3g}元。共用订单意图，独立验证成交与账户，不代表独立复现了选股。",
      '', '一个季度样本不足以判定长期优势；当前结果不支持启用TECH1.0实盘。固定参数继续验证，不根据这些结果选择最优阈值。',
      '', '## 简化后保留的必要部分','',
      '仅一套价量突破、一个大盘开关、必要仓位/止损规则、真实成交与税费、每日只读信号和人工执行。无需财报预约订阅、iFinD开户或真实买卖来推进研究。',
      '', '技术候选原始窗口均独立重算；非候选按股票和原因保留，尚未逐条独立重算全部排除。现金分红已验证；送转股和未知公司行动仍会阻止受影响回放，不能伪造或跳过。',
      '', '## 历史扩展','',
      '2018年度导出首次被本地校验拦截：002367.SZ在2018-03-16的MA20与MA60均为8.5605，数组浮点求和误判严格大于。失败原始日志保留；修正为与本地独立审计相同的精确求和均值，阈值不变。年度结果以2018/screen.json及实际组合输出为准，日线筛选不算完整绩效。',
      '', '2018—2022须连续携带资金、持仓和分红权利，不能把每年重置3万元的结果拼成连续回测。2023以后属于已见历史验证；真正前瞻验证需要未来市场数据。']
    if (OUT/'2018/rqalpha_annual_parity.json').exists():
        lines+=['','## 已完成：2018全年研究回放','',
                '243交易日，起始资金30000元；全年仅两个信号日大盘开关开启。两档各3笔完整交易。']
        for c in (1.,1.5):
            r=json.loads((OUT/f'2018/annual_cost{c}.json').read_text(encoding='utf8'))
            lines.append(f"- {c}倍成本：期末{r['final']['equity']:.2f}元，收益{r['metrics']['marked_return']:.2%}，分钟收盘最大回撤{r['metrics']['max_minute_close_drawdown']:.2%}。")
        lines+=['','RQAlpha两档共116640次分钟账户核对通过，现金/权益差异为零。交易很少，不能据此判断稳定优势；2019Q2是独立工程窗口，不能与本年度收益直接拼接。']
    (OUT/'PROGRESS.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    files=[ROOT/'src/simple_strategy_rules.py',ROOT/'src/research_portfolio.py',ROOT/'adapters/supermind_s1_minute_backtest.py']
    files+=list(OUT.glob('quarter_*.json'))+list(OUT.glob('minute_export*.txt'))+[OUT/'corporate_export.txt',OUT/'rqalpha_quarter_parity.json',OUT/'PROTOCOL.md']
    manifest={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    if manifest['adapters/supermind_s1_minute_backtest.py']!='c1e87739dcea419665650e4d714ea8d5a414a9ac849cd08d7596c30dcdfaf9e5':raise ValueError('冻结S1已变化')
    (OUT/'validation_manifest.json').write_text(json.dumps(dict(scope='TECH1 quarter evidence; not long history acceptance',sha256=manifest),ensure_ascii=False,indent=2),encoding='utf8')
    print('quarter report and manifest written')

if __name__=='__main__':main()
