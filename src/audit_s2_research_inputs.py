"""生成四策略研究输入验收记录；缺数据时不输出收益率或启动调参。"""
import json
import hashlib
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def run():
    manifest_path = ROOT / 'runtime/history_backfill/manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    daily = ROOT / 'runtime/history_backfill/history_daily.csv.gz'
    columns = list(pd.read_csv(daily, nrows=1).columns)
    benchmark = pd.read_csv(ROOT / 'runtime/s1_benchmark.csv')
    long_evidence = ROOT / 'reports/s2_research/long_history/manifest.json'
    verified_long = None
    if long_evidence.exists():
        evidence = json.loads(long_evidence.read_text(encoding='utf-8'))
        if (evidence.get('status') == 'PASS_BENCHMARK_AND_HISTORICAL_INDUSTRY_SAMPLE'
                and evidence.get('hashes')
                and all((ROOT/p).is_file() and hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==digest
                        for p,digest in evidence['hashes'].items())):
            benchmark = pd.read_csv(ROOT / 'reports/s2_research/long_history/research_benchmark.csv')
            verified_long = dict(path=str(long_evidence.relative_to(ROOT)),sha256=hashlib.sha256(long_evidence.read_bytes()).hexdigest(),
                                 status=evidence['status'],full_research_ready=False)
    dates = pd.to_datetime(benchmark['date'])
    required = ['factor', 'is_st', 'is_paused', 'high_limit', 'low_limit']
    missing = sorted(set(required) - set(columns))
    contract = ROOT / 'runtime/s2_verified_replay/manifest.json'
    blockers = []
    if manifest.get('formal_backtest_ready') is not True:
        blockers.append('长历史日线源明确formal_backtest_ready=false，当前存续股票生存者偏差尚未消除')
    if missing:
        blockers.append('长历史日线缺少真实时点字段：' + ', '.join(missing))
    if dates.min() > pd.Timestamp('2018-01-02'):
        blockers.append('本地基准起始日期不足2018年，不能直接完成2018—2026分段环境回放')
    if not contract.exists():
        blockers.append('缺少覆盖完整研究期的分钟、时点财报事件、除权和成交回放输入包；已有固定样本不代表全区间就绪')
    else:
        # 不将仅存在的清单视为分钟数据已核验。
        blockers.append('分钟输入包尚须逐文件哈希、日期覆盖、交易日与字段语义验收')
    sample_reports = {}
    if verified_long:
        sample_reports['verified_long_benchmark_and_industry'] = verified_long
    for name, relative in {
        'calendar_snapshot': 'data_feasibility/calendar_source_audit.json',
        'corporate_actions_and_delisted_daily': 'data_feasibility/platform_capability_audit.json',
    }.items():
        path = ROOT / 'reports/s2_research' / relative
        if path.exists():
            record = json.loads(path.read_text(encoding='utf-8'))
            sample_reports[name] = dict(path=str(path.relative_to(ROOT)), reported_status=record.get('status'),
                                       reported_rows=record.get('row_count', record.get('daily_rows')),
                                       full_research_ready=False)
    payload = dict(generated_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                   status='BLOCKED_FOR_PERFORMANCE_VALIDATION', live_enabled=False,
                   daily_columns=columns, daily_source=manifest.get('source'),
                   benchmark_start=dates.min().strftime('%Y-%m-%d'),
                   benchmark_end=dates.max().strftime('%Y-%m-%d'),
                   blockers=blockers, optimization_runs=0, sample_evidence_reports=sample_reports,
                   reason='功能测试可继续；禁止用不完整数据伪造四策略收益或最优配置')
    output = ROOT / 'reports/s2_research/input_audit.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


if __name__ == '__main__':
    run()
