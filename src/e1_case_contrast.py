"""Descriptive success/failure contrasts; labels are outcomes, never input features."""
import json,statistics
from collections import Counter,defaultdict
from e1_condition_study import ROOT,OUT,save

def outcome_class(value):
    return 'up_gt5' if value>5 else 'down_lt_minus5' if value<-5 else 'middle'

def main():
    data=json.loads((OUT/'signals.json').read_text(encoding='utf8'))['signals']
    trend={(r['symbol'],r['date']):r for r in json.loads((ROOT/'reports/e1_rank_research/feature_audit.json').read_text(encoding='utf8'))['features']}
    source={}
    for year in (2018,2019,2020):
        for day in json.loads((ROOT/f'reports/simple_research/{year}/screen.json').read_text(encoding='utf8'))['days']:
            for r in day['candidates']:source[r['symbol'],day['date']]=(r,day['benchmark'])
    rows=[]
    for r in data:
        value=r['outcomes']['10'];end=r['exit_days']['10']
        if value is None or end is None:continue
        period='discovery' if end<='2019-12-31' else 'review2020' if r['asof']>='2020-01-01' else None
        if period is None:continue
        s,b=source[r['symbol'],r['asof']];t=trend[r['symbol'],r['asof']]
        features=dict(ma20_distance_pct=(s['close']/s['ma20']-1)*100,
                      breakout_distance_pct=(s['close']/s['prior_breakout_close']-1)*100,
                      volume_ratio=s['volume_ratio'],atr_pct=s['atr20_raw']/s['raw_close']*100,
                      rs20_pct=t['rs20']*100,r2=t['r2'],market_ret20_pct=b['ret20']*100)
        rows.append(dict(symbol=r['symbol'],asof=r['asof'],period=period,label=outcome_class(value),forward10_pct=value,features=features))
    result={}
    for period in ('discovery','review2020'):
        selected=[r for r in rows if r['period']==period];byday=defaultdict(list)
        for r in selected:byday[r['asof']].append(r)
        result[period]={}
        for label in ('up_gt5','middle','down_lt_minus5'):
            a=[r for r in selected if r['label']==label]
            result[period][label]=dict(signal_cases=len(a),raw_case_pct=len(a)/len(selected)*100,
              date_balanced_class_pct=sum(sum(r['label']==label for r in d)/len(d) for d in byday.values())/len(byday)*100,
              feature_medians={k:statistics.median(r['features'][k] for r in a) for k in a[0]['features']} if a else {})
    save('case_contrast.json',dict(label_definition='Next-session open to tenth-session close factor return: >5%, <-5%, otherwise middle.',
           interpretation='Descriptive sample associations only. Repeated/overlapping signals are not independent trades; feature medians use raw cases.',
           model_trained=False,forecast_accuracy_claimed=False,summary=result,cases=rows))
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
