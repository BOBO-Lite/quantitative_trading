"""只报告完整退出扩展，披露所有成本档及期末持仓。"""
import json
from datetime import date
from exit_extension_research import OUT

def main():
    rows=[]
    for variant in ('E0','E1','E2'):
        for cost in (1.,1.5):
            path=OUT/f'{variant}_cost{cost}.json'
            if not path.exists(): raise ValueError('未完成全部路径，不能生成完整阶段收益表')
            r=json.loads(path.read_text(encoding='utf8'))
            if len(r['daily'])!=730 or len(r['minute_curve'])!=175200 or r['daily'][-1]['date']!='2020-12-31':
                raise ValueError('连续日历覆盖不符')
            prior=next(d for d in r['daily'] if d['date']=='2019-12-31')
            year=[d for d in r['daily'] if d['date'].startswith('2020')]
            elapsed=(date(2020,12,31)-date(2018,1,2)).days/365.25
            rows.append(dict(variant=variant,cost=cost,equity=r['final']['equity'],total_return=r['metrics']['marked_return'],
                cagr=(r['final']['equity']/30000)**(1/elapsed)-1,return_2020=r['final']['equity']/prior['equity']-1,
                maximum_minute_drawdown=r['metrics']['max_minute_close_drawdown'],fills=len(r['fills']),
                fills_2020=sum(f['fill_time'].startswith('2020') for f in r['fills']),
                held_symbols=sorted(r['positions']),fees=r['metrics']['fees_paid'],
                average_exposure_2020=sum((d['equity']-d['cash']-d['dividend_receivable'])/d['equity'] for d in year)/len(year),
                days_2020=len(year),unrealized_pnl=r['final']['unrealized_pnl']))
    (OUT/'comparison.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
    text=['# EXIT1 连续至2020年结果','',
          '3万元从2018-01-02连续至2020-12-31，共730交易日；无跨年重置。所有版本固定买点。年末按持仓市值计权益，不虚构强平。2020为历史扩展，不是真正未见未来。','',
          '|版本|成本倍数|累计收益|年化|2020年收益|分钟收盘最大回撤|2020成交笔数|期末持仓数|',
          '|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        text.append(f"|{r['variant']}|{r['cost']}|{r['total_return']:.2%}|{r['cagr']:.2%}|{r['return_2020']:.2%}|{r['maximum_minute_drawdown']:.2%}|{r['fills_2020']}|{len(r['held_symbols'])}|")
    text.extend(['','E0为原始盘中保护触发；E1改为收盘确认、次日最早09:32退出；E2在E1上将后续跟踪放宽至3ATR，初始风险不变。市场防守、持有20日上限与账户风险阈值均未改变。','',
                 '旧区间的成交、日账户、分钟账户、委托和决策前缀均须完全一致才接受扩展输出。RQAlpha结果另见 rqalpha_parity.json；账户核账通过也不代表策略已证明有效。','',
                 '组合资金与后续入场随卖点改变，不能将全部组合收益差异归因于某笔卖点。此前同入场逐笔对照在高成本下未显示稳定优势，必须连同本结果保留。买点2%追价对照单独登记，不混入本组。',''])
    (OUT/'RESULT.md').write_text('\n'.join(text),encoding='utf8')
    print(json.dumps(rows,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
