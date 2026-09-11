"""Extend only the isolated MOM account to exact, matched stock distributions."""
import copy
from simple_corporate_events import build_events

def build(packets,symbols):
    clean=copy.deepcopy(packets);shares=[];blocked=[]
    for s in symbols:
        d=clean['dividend_'+s]['data'];detail=clean['details_'+s]['data']
        for stamp in list(d.get('symbol',{})):
            raw=d['give_stock'][stamp]+d['transfer_stock'][stamp]
            if not raw:continue
            matches=[i for i,date in detail['stock_bonus_ex_dividend_date'].items() if date[:10]==stamp[:10]]
            if not matches:raise ValueError('unmatched stock distribution')
            i=matches[0];bonus=detail['stock_bonus_per_share_bonus'][i];capital=detail['stock_bonus_per_share_capital_stock'][i];ratio=bonus+capital
            record=detail['stock_bonus_date_of_record'][i];trading=detail['stock_bonus_bonus_shares_trading_day'][i]
            if not record or not trading or not record[:10]<stamp[:10]<=trading[:10]:raise ValueError('stock distribution dates missing')
            # Ordinary floating-point source approximations may be reconciled against explicit per-share plan.
            if abs(raw-ratio)>2e-6:
                blocked.append(dict(symbol=s,record_date=record[:10],ex_date=stamp[:10],kind='stock_distribution_ratio_conflict',raw=raw,plan=ratio))
            else:
                if bonus and s not in ('600161.SH','002030.SZ'):raise ValueError('unverified stock dividend par value')
                shares.append(dict(symbol=s,record_date=record[:10],ex_date=stamp[:10],pay_date=(detail['stock_bonus_date_payable'][i] or stamp)[:10],announcement_date=detail['stock_bonus_dividend_announcement_date'][i][:10],cash_per_share=d['cash_dividends'][stamp],shares_per_share=ratio,shares_trading_date=trading[:10],taxable_cash_per_share=d['cash_dividends'][stamp]+bonus,bonus_per_share=bonus,capital_per_share=capital,raw_ratio=raw))
            # Remove the entire distribution from the cash-only adapter, preserving it in shares/blocked.
            for values in d.values():del values[stamp]
            for j in matches:
                for values in detail.values():del values[j]
    cash,other=build_events(clean,symbols,'2018-01-01')
    return cash+shares,other+blocked
