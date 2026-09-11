"""Fixed public-factor replication; never connected to broker or live strategies."""
from pathlib import Path
import csv
import hashlib
import io
import json
import re
import zipfile
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/evidence_gate'


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def parse_factor_text(text, digits, columns):
    rows = []
    for line in text.splitlines():
        if not re.match(r'^\s*\d{' + str(digits) + r'},', line):
            continue
        fields = next(csv.reader([line]))
        assert len(fields) == len(columns) + 1, 'unexpected factor columns'
        date = fields[0].strip()
        values = [float(x) for x in fields[1:]]
        assert all(np.isfinite(x) and x > -90 for x in values), 'missing/sentinel return'
        rows.append([date] + [x / 100 for x in values])
    assert rows, 'no returns'
    frame = pd.DataFrame(rows, columns=['date'] + columns).set_index('date')
    assert frame.index.is_unique and frame.index.is_monotonic_increasing
    return frame


def load_zip(name, digits, columns):
    with zipfile.ZipFile(OUT / (name + '.zip')) as archive:
        names = archive.namelist()
        assert len(names) == 1
        text = archive.read(names[0]).decode('utf-8-sig')
    # Do not select annual summary rows from monthly files.
    return parse_factor_text(text, digits, columns)


def lagged_variance(daily, months):
    grouped = daily.groupby(daily.index.str[:6])
    realized = grouped.apply(lambda x: float(np.sum((x - x.mean()) ** 2)))
    counts = grouped.size()
    previous = [(pd.Period(m, freq='M') - 1).strftime('%Y%m') for m in months]
    assert all(m in realized.index and counts.loc[m] >= 10 for m in previous), 'missing prior month'
    variance = pd.Series(realized.loc[previous].to_numpy(), index=months)
    assert (variance > 0).all() and np.isfinite(variance).all()
    return variance


def fit_scale(returns, lagvar):
    train = (returns.index >= '192701') & (returns.index <= '201512')
    assert train.any()
    return float(returns.loc[train].std(ddof=1) / (returns.loc[train] / lagvar.loc[train]).std(ddof=1))


def metrics(excess, weights, total=None):
    arr = np.asarray(excess, dtype=float)
    vol = float(np.std(arr, ddof=1) * np.sqrt(12))
    result = dict(months=len(arr), annual_arithmetic_excess_pct=float(arr.mean()*1200),
                  annual_vol_pct=vol*100, sharpe=float(arr.mean()*12/vol),
                  weight_mean=float(np.mean(weights)), weight_max=float(np.max(weights)),
                  weight_above_one_months=int(np.sum(np.asarray(weights)>1)))
    if total is not None:
        x = np.asarray(total)
        assert (x > -1).all(), 'theoretical account ruined'
        nav = np.r_[1., np.cumprod(1+x)]
        result.update(theoretical_total_cagr_pct=float((nav[-1]**(12/len(x))-1)*100),
                      monthly_close_max_drawdown_pct=float(np.max(1-nav/np.maximum.accumulate(nav))*100))
    return result


def paired_block_interval(candidate, baseline):
    a, b = np.asarray(candidate), np.asarray(baseline)
    assert len(a) == len(b)
    n = len(a)
    rng = np.random.default_rng(20260910)
    indices = ((rng.integers(0, n, size=(2000, (n+11)//12, 1)) + np.arange(12)) % n).reshape(2000,-1)[:, :n]
    def sharpe(x):
        return x.mean(axis=1) / x.std(axis=1, ddof=1) * np.sqrt(12)
    differences = sharpe(a[indices]) - sharpe(b[indices])
    return dict(method='paired circular 12-month blocks; 2000 draws; fixed c',
                low95=float(np.quantile(differences,.025)), high95=float(np.quantile(differences,.975)))


def main():
    lock = json.loads((OUT/'protocol_lock.json').read_text())
    assert hashlib.sha256((OUT/'PROTOCOL.md').read_bytes()).hexdigest() == lock['protocol_sha256']
    d = load_zip('french_factors_daily',8,['Mkt-RF','SMB','HML','RF'])
    m = load_zip('french_factors_monthly',6,['Mkt-RF','SMB','HML','RF'])
    md = load_zip('french_mom_daily',8,['Mom'])
    mm = load_zip('french_mom_monthly',6,['Mom'])
    months = pd.period_range('1927-01','2025-12',freq='M').strftime('%Y%m')
    assert set(months).issubset(m.index) and set(months).issubset(mm.index)
    frame = pd.DataFrame(index=months)
    frame['rf'] = m.loc[months,'RF']
    scales = {}
    for name,daily,monthly,column in [('market',d,m,'Mkt-RF'),('momentum',md,mm,'Mom')]:
        frame[name] = monthly.loc[months,column]
        frame[name+'_lagvar'] = lagged_variance(daily[column],months)
        c = fit_scale(frame[name],frame[name+'_lagvar']); scales[name] = c
        frame[name+'_weight'] = c / frame[name+'_lagvar']
        frame[name+'_managed'] = frame[name]*frame[name+'_weight']
    frame['market_capped_weight'] = frame.market_weight.clip(upper=1)
    frame['market_capped'] = frame.market*frame.market_capped_weight
    # Paper-style target-weight changes, not an executable share-level turnover model.
    changes = frame.market_capped_weight.diff().abs()
    changes.iloc[0] = abs(frame.market_capped_weight.iloc[0]-1.)
    frame['market_capped_fee10'] = frame.market_capped - .001*changes
    frame['market_capped_fee14'] = frame.market_capped - .0014*changes
    frame['market_target_weight_change'] = changes
    groups = [('paper_period','192701','201512'),('post_publication','201701','202512'),
              ('post_2017_2020','201701','202012'),('post_2021_2025','202101','202512')]
    variants = [('market','one'),('market_managed','market_weight'),('market_capped','market_capped_weight'),
                ('market_capped_fee10','market_capped_weight'),('market_capped_fee14','market_capped_weight'),
                ('momentum','one'),('momentum_managed','momentum_weight')]
    results = []
    for group,start,end in groups:
        block = frame.loc[start:end]
        for variant,weight in variants:
            weights = np.ones(len(block)) if weight=='one' else block[weight]
            r = metrics(block[variant],weights,block[variant]+block.rf if variant.startswith('market') else None)
            r.update(period=group, variant=variant)
            results.append(r)
    post = frame.loc['201701':'202512']
    intervals = {v:paired_block_interval(post[v],post.market) for v in ('market_capped','market_capped_fee10','market_capped_fee14')}
    # Independent scalar reconstruction of every managed return and the capped cost path.
    max_error = 0.
    for name,daily,col in [('market',d,'Mkt-RF'),('momentum',md,'Mom')]:
        for month in months:
            prior = (pd.Period(month,freq='M')-1).strftime('%Y%m')
            vals = daily.loc[daily.index.str.startswith(prior),col].tolist()
            avg = sum(vals)/len(vals);rv = sum((x-avg)**2 for x in vals)
            expected = scales[name]/rv*float(frame.loc[month,name])
            max_error = max(max_error,abs(expected-float(frame.loc[month,name+'_managed'])))
    assert max_error < 1e-12
    frame.index.name = 'month'
    frame.to_json(OUT/'monthly_paths.json',orient='index',double_precision=15)
    save('results.json',results);save('uncertainty.json',intervals)
    save('replication_audit.json',dict(protocol_sha256=lock['protocol_sha256'],scales=scales,
        continuous_months=len(months),training_months=1068,post_publication_months=108,
        scalar_reconstructed_returns=2*len(months),max_scalar_error=max_error,
        no_a_share_account=True,no_new_fh_variant=True,data_vintage='202607 CRSP via French; downloaded 2026-09-10'))
    print(json.dumps([r for r in results if r['period']=='post_publication'],ensure_ascii=False))
    print(json.dumps(intervals))


if __name__ == '__main__':
    main()
