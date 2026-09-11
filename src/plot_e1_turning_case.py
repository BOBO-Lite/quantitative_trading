"""Plot observed daily closes and separately labelled actual/simulated executions."""
import json
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from e1_turning_research import OUT

def main():
    case=json.loads((OUT/'case_002317.json').read_text(encoding='utf8'))
    repair=json.loads((OUT/'case_exit_repair.json').read_text(encoding='utf8'))['results']
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans'];plt.rcParams['axes.unicode_minus']=False
    fig,ax=plt.subplots(figsize=(12,5.8),layout='constrained')
    dates=[datetime.fromisoformat(d['date']) for d in case['daily']];closes=[d['raw_daily']['close'] for d in case['daily']]
    ax.plot(dates,closes,color='#335c81',marker='o',markersize=3,label='每日收盘价（不是盘中高低点）')
    ax.axvspan(datetime(2020,1,24),datetime(2020,2,2,23,59),color='#e9edf1',label='春节休市区间')
    markers=[('原买入',case['fills']['E1'][0],(-8,24),'#252525'),('原E1卖出',case['fills']['E1'][1],(15,18),'#1b7f5b'),('延长版W卖出',case['fills']['W'][1],(-120,-45),'#b63636'),('新增保护P卖出',repair['P']['fills'][1],(20,38),'#8a5a16')]
    for label,f,offset,color in markers:
        x=datetime.fromisoformat(f['fill_time']);y=f['price'];ax.scatter([x],[y],s=50,color=color,zorder=5)
        ax.annotate(f"{label}\n{x:%m-%d %H:%M}  {y:.3f}元",(x,y),xytext=offset,textcoords='offset points',fontsize=9,color=color,arrowprops=dict(arrowstyle='-',color=color))
    peak=case['peak'];x=datetime.fromisoformat(peak['datetime']);y=peak['high'];ax.scatter([x],[y],s=65,color='#6f42a5',marker='D',zorder=6)
    ax.annotate(f'事后盘中最高 {y:.2f}元\n{x:%m-%d %H:%M}，不是预先已知卖点',(x,y),xytext=(-175,15),textcoords='offset points',fontsize=9,color='#6f42a5',arrowprops=dict(arrowstyle='-',color='#6f42a5'))
    ax.set_title('002317.SZ：延长持有的回吐，与过早保护造成的误卖',loc='left',fontsize=15,pad=20)
    ax.set_ylabel('原始价格（元）');ax.set_ylim(10,18.7);ax.xaxis.set_major_locator(mdates.DayLocator(interval=7));ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
    ax.grid(axis='y',alpha=.18);ax.spines[['top','right']].set_visible(False);ax.legend(loc='upper left',frameon=False,fontsize=9)
    fig.supxlabel('固定原买入600股的单笔重放；P未到最高点即退出。图示不是完整账户收益，也不假设最高价可成交。',fontsize=9)
    fig.savefig(OUT/'case_002317.png',dpi=160);fig.savefig(OUT/'case_002317.svg');plt.close(fig)
if __name__=='__main__':main()
