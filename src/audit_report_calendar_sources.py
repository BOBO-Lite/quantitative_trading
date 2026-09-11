"""审计公开预约披露快照；日期存在不代表历史时点可用，不解除策略门禁。"""
import hashlib
import json
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def date_only(value, field):
    if value in (None, ''):
        return None
    if not isinstance(value, str):
        raise ValueError('日期类型错误：' + field)
    # 这些来源只提供预约目标日；即使字符串带00:00:00也不是公开时刻。
    try:
        parsed = date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ValueError('日期无效：' + field) from exc
    if value not in (parsed.isoformat(), parsed.isoformat() + ' 00:00:00'):
        raise ValueError('未登记的日期格式：' + field)
    return parsed.isoformat()


def normalize_snapshot(payload, provider):
    if provider == 'eastmoney':
        result = payload.get('result')
        if payload.get('success') is not True or not isinstance(result, dict):
            raise ValueError('东方财富未返回成功数据')
        records = result.get('data')
        mapping = {'code': 'SECURITY_CODE', 'period': 'REPORT_DATE',
                   'scheduled': 'FIRST_APPOINT_DATE', 'actual': 'ACTUAL_PUBLISH_DATE',
                   'changes': ['FIRST_CHANGE_DATE', 'SECOND_CHANGE_DATE', 'THIRD_CHANGE_DATE']}
    elif provider == 'cninfo':
        records = payload.get('prbookinfos')
        mapping = {'code': 'seccode', 'period': 'f001d_0102',
                   'scheduled': 'f002d_0102', 'actual': 'f006d_0102',
                   'changes': ['f003d_0102', 'f004d_0102', 'f005d_0102']}
    else:
        raise ValueError('未登记来源')
    if not isinstance(records, list) or not records:
        raise ValueError('空响应不等于没有事件')
    normalized, seen = [], set()
    for row in records:
        required = [mapping[k] for k in ('code', 'period', 'scheduled', 'actual')] + mapping['changes']
        if any(key not in row for key in required):
            raise ValueError('预约快照缺少字段')
        code = row[mapping['code']]
        if not isinstance(code, str) or len(code) != 6 or not code.isdigit():
            raise ValueError('股票代码无效')
        period = date_only(row[mapping['period']], 'period')
        scheduled = date_only(row[mapping['scheduled']], 'scheduled')
        actual = date_only(row[mapping['actual']], 'actual')
        changes = [date_only(row[key], key) for key in mapping['changes']]
        if period is None or scheduled is None:
            raise ValueError('缺少报告期或首次预约日')
        if any(value is not None and value <= period for value in [scheduled, actual] + changes):
            raise ValueError('披露日不晚于报告期，需人工检查来源语义')
        key = (code, period)
        if key in seen:
            raise ValueError('重复股票报告期，不能静默覆盖版本')
        seen.add(key)
        normalized.append(dict(provider=provider, code=code, report_period=period,
                               first_scheduled_date=scheduled, changed_scheduled_dates=changes,
                               actual_report_date=actual, published_at=None, available_at=None,
                               event_clear=False, pit_ready=False,
                               blockers=['APPOINTMENT_VERSION_PUBLICATION_TIME_MISSING',
                                         'HISTORICAL_COVERAGE_EVIDENCE_MISSING']))
    return normalized


def compare_sources(rows):
    """同一股票/报告期跨来源一致也不能补造可见时刻；冲突须单独定位。"""
    groups = {}
    for row in rows:
        groups.setdefault((row['code'], row['report_period']), []).append(row)
    checks = []
    for (code, period), group in sorted(groups.items()):
        if len({r['provider'] for r in group}) < 2:
            continue
        signatures = {(r['first_scheduled_date'], tuple(r['changed_scheduled_dates']),
                       r['actual_report_date']) for r in group}
        checks.append(dict(code=code, report_period=period, dates_agree=len(signatures) == 1,
                           pit_ready=False))
    return checks


def audit(directory):
    directory = Path(directory)
    probes = json.loads((directory / 'public_calendar_probe.json').read_text(encoding='utf-8'))
    rows, files, errors = [], [], []
    for probe in probes:
        if 'error' in probe:
            errors.append({'name': probe['name'], 'error': probe['error']})
            continue
        name = probe['name']
        if Path(name).name != name or '/' in name or '\\' in name or ':' in name:
            raise ValueError('非法源文件名')
        path = directory / (name + '.json')
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != probe.get('sha256'):
            raise ValueError('来源文件SHA256不一致：' + name)
        provider = 'eastmoney' if name.startswith('eastmoney_') else 'cninfo' if name.startswith('cninfo_') else None
        parsed = normalize_snapshot(json.loads(raw), provider)
        if len(parsed) != probe.get('row_count'):
            raise ValueError('来源记录数量不一致：' + name)
        rows.extend(parsed)
        files.append(dict(name=name, sha256=digest, rows=len(parsed)))
    comparisons = compare_sources(rows)
    return dict(status='SNAPSHOT_AUDITED_PIT_BLOCKED', row_count=len(rows), sources=files,
                source_errors=errors, rows=rows, cross_source_checks=comparisons,
                source_conflict_count=sum(not x['dates_agree'] for x in comparisons),
                event_clear=False, formal_backtest_ready=False,
                interpretation='仅核验历史预约目标日期，不证明当时已知，不可用于放行开仓')


if __name__ == '__main__':
    output_dir = ROOT / 'reports/s2_research/data_feasibility'
    result = audit(output_dir)
    (output_dir / 'calendar_source_audit.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}, ensure_ascii=False, indent=2))
