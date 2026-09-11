"""重算既有真实日线并验证TECH1.0接口；固定两股样本不评价全池绩效。"""
import copy,hashlib,json
from pathlib import Path
from import_supermind_minute_probe import decode_packets
from research_daily_features import build_feature_report
from build_history_sample_bundle import build_bundle
from research_portfolio import run_bundle
from s2_strategy_rules import Policy
import simple_strategy_rules as rules
ROOT=Path(__file__).resolve().parents[1]

def main():
    raw=ROOT/'reports/s2_research/feature_export_6a9fdb7054104300b63c389a.txt'
    evidence=json.loads((ROOT/'reports/s2_research/portfolio_replay/daily_feature_validation_manifest.json').read_text(encoding='utf8'))
    if hashlib.sha256(raw.read_bytes()).hexdigest()!=evidence['sha256'][str(raw.relative_to(ROOT)).replace('\\','/')]:
        raise ValueError('日线原始证据变化')
    features=build_feature_report(decode_packets(raw.read_text(encoding='utf8')),['2019-04-16','2019-04-17','2019-04-18','2019-04-19'])
    minutes=json.loads((ROOT/'reports/s2_research/portfolio_replay/historical_minute_sample.json').read_text(encoding='utf8'))
    bundle=build_bundle(features,minutes)
    bundle['research_version']=rules.VERSION;bundle['source_kind']='REAL_TWO_STOCK_TECH1_INTERFACE_SAMPLE'
    states={d['date']:{r['symbol']:r['is_st'] for r in d['stocks']} for d in features['days']}
    for day in bundle['days']:
        for batch in day['minutes']:
            for symbol,bar in batch['bars'].items():bar['is_st']=states[day['date']][symbol]
        for row in day['previous_close']['stocks']:
            row['market_state_verified']=True
            row['market_state_evidence']=dict(log_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),method='recomputed_raw_history_dates_and_historical_state')
    out=ROOT/'reports/simple_research';out.mkdir(parents=True,exist_ok=True)
    (out/'sample_bundle.json').write_text(json.dumps(bundle,ensure_ascii=False,indent=2),encoding='utf8')
    for cost in (1.,1.5):
        result=run_bundle(copy.deepcopy(bundle),Policy(cost_multiplier=cost),rules=rules)
        result['performance_interpretation_allowed']=False
        result['scope']='two-stock interface test, not full-universe strategy validation'
        (out/f'sample_cost{cost}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        print(dict(cost=cost,fills=len(result['fills']),orders=len(result['orders']),final=result['final'],performance_interpretation_allowed=False))

if __name__=='__main__':main()
