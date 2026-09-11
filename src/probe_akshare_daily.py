"""隔离进程实测AKShare日期明确的原始日线；失败只留证据，不覆盖正式数据。"""
import argparse, csv, hashlib, importlib.metadata, json, subprocess, sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from adapters.akshare_readonly import normalize_daily, compare_dated_rows

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--date', required=True)
    p.add_argument('--symbols', nargs='+', default=['000001.SZ', '600036.SH', '601555.SH'])
    p.add_argument('--output', required=True)
    p.add_argument('--provider', choices=['eastmoney','tencent'], default='eastmoney')
    p.add_argument('--reference', help='可选：现有日期明确的日线文件，用于交叉核对，不修改它')
    p.add_argument('--worker', action='store_true')
    args = p.parse_args()
    if args.worker:
        import akshare as ak
        if args.provider == 'eastmoney':
            df = ak.stock_zh_a_hist(symbol=args.symbols[0][:6], period='daily', start_date=args.date.replace('-', ''), end_date=args.date.replace('-', ''), adjust='', timeout=12)
        else:
            df = ak.stock_zh_a_hist_tx(symbol=args.symbols[0][-2:].lower()+args.symbols[0][:6], start_date=args.date.replace('-', ''), end_date=args.date.replace('-', ''), adjust='', timeout=12)
        print(df.to_json(orient='records', date_format='iso', force_ascii=False))
        return
    out = Path(args.output); out.mkdir(parents=True, exist_ok=True)
    references = {}
    if args.reference:
        with Path(args.reference).open(encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                if row['date'] == args.date and row['symbol'] in args.symbols:
                    if row['symbol'] in references:
                        raise ValueError('参考日线重复')
                    references[row['symbol']] = row
    results = []
    for symbol in args.symbols:
        item = dict(symbol=symbol, target_date=args.date, observed_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat())
        try:
            run = subprocess.run([sys.executable, '-X', 'utf8', __file__, '--worker', '--date', args.date, '--symbols', symbol, '--output', str(out), '--provider', args.provider], capture_output=True, timeout=40, encoding='utf-8', errors='replace')
            if run.returncode:
                raise RuntimeError(run.stderr[-2500:])
            records = json.loads(run.stdout)
            for row in records:
                date_key = '日期' if args.provider == 'eastmoney' else 'date'
                row[date_key] = row[date_key].split('T')[0]
            raw = json.dumps(records, ensure_ascii=False, indent=2).encode('utf-8')
            name = symbol + '.raw.json'; (out / name).write_bytes(raw)
            item.update(raw_file=name, sha256=hashlib.sha256(raw).hexdigest())
            if args.provider == 'eastmoney':
                item['row'] = normalize_daily(records, symbol, args.date, item['observed_at'])
            else:
                from adapters.akshare_readonly import normalize_tencent_daily
                item['row'] = normalize_tencent_daily(records, symbol, args.date, item['observed_at'], importlib.metadata.version('akshare'))
            item['status'] = 'PASS_DATED_PRICE_ROW'
            if args.reference:
                item['comparison'] = compare_dated_rows(item['row'], references[symbol])
                if not item['comparison']['matches']:
                    raise ValueError('与参考日线不一致，禁止接纳')
        except Exception as exc:
            item.update(status='BLOCKED_SOURCE', error=str(exc))
        results.append(item)
    result = dict(provider=args.provider, akshare_version=importlib.metadata.version('akshare'), target_date=args.date, cases=results, formal_database_updated=False, automatic_trading=False, status='READ_ONLY_SAMPLE_PASS' if all(x['status']=='PASS_DATED_PRICE_ROW' for x in results) else 'SOURCE_NOT_ACCEPTED')
    if args.reference:
        result['reference'] = dict(path=str(Path(args.reference).resolve()), sha256=hashlib.sha256(Path(args.reference).read_bytes()).hexdigest(), note='现有日线用于数值核对；是否独立上游需按其来源另行判断')
    (out / 'probe.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True))
if __name__ == '__main__':
    main()

