"""单持仓批次的现金分红账本。登记日确认资格，除息日计应收，派息日到账。
仅现金分红；送转、配股和无法核对的公司行动拒绝。交易手续费仍由执行账本处理。
"""
from calendar import monthrange
from datetime import date
from math import isfinite


def month_after(day, months):
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12); month += 1
    return date(year, month, min(day.day, monthrange(year,month)[1]))


def dividend_tax_rate(buy_day, sell_day):
    buy, sell = date.fromisoformat(buy_day), date.fromisoformat(sell_day)
    if sell < buy: raise ValueError('卖出早于买入')
    # 从取得日向前计算自然月；从卖出日倒减在2月末会错误延长20%档。
    return .2 if sell <= month_after(buy,1) else .1 if sell <= month_after(buy,12) else 0.


class CashDividendBook:
    def __init__(self, events):
        self.events, self.rights, self.closed, self.opened = {}, {}, set(), set()
        self.receivable = self.gross_income = self.tax_paid = 0.
        self.ledger = []
        for original in events:
            e = dict(original)
            for k in ('announcement_date','record_date','ex_date','pay_date'):
                if date.fromisoformat(e[k]).isoformat()!=e[k]: raise ValueError('日期格式错误')
            if not e['announcement_date'] <= e['record_date'] < e['ex_date'] <= e['pay_date']:
                raise ValueError('公司行动日期顺序错误')
            if e['record_date'] <= '2015-09-08':
                raise ValueError('早期红利税制未验收')
            if e.get('shares_per_share') != 0: raise ValueError('送转或其他股本变动尚未验收')
            if not isfinite(e['cash_per_share']) or e['cash_per_share'] <= 0:
                raise ValueError('分红金额必须为正数')
            key = e['symbol'], e['ex_date']
            if key in self.events: raise ValueError('重复或冲突分红事件')
            self.events[key]=e

    def close_day(self, day, positions):
        if day in self.closed: raise ValueError('登记日重复结算')
        for key,e in self.events.items():
            if e['record_date']!=day: continue
            p=positions.get(e['symbol'])
            qty = p.quantity if p else 0
            self.rights[key]=dict(quantity=qty, untaxed_quantity=qty, entry_day=p.entry_day if p else None, accrued=False,paid=False)
            self.ledger.append(dict(event='record',date=day,ex_date=e['ex_date'],symbol=e['symbol'],quantity=qty,cash=0))
        self.closed.add(day)

    def open_day(self, day):
        if day in self.opened: raise ValueError('交易日重复盘前处理')
        cash = 0.
        for key,e in sorted(self.events.items()):
            if day < e['ex_date']: continue
            if key not in self.rights:
                raise ValueError('缺登记日持仓快照，不得猜测分红资格')
            r=self.rights[key]; value=r['quantity']*e['cash_per_share']
            if not r['accrued']:
                if day != e['ex_date']: raise ValueError('缺除息日处理')
                self.receivable += value; self.gross_income += value; r['accrued']=True
                self.ledger.append(dict(event='accrue',date=day,ex_date=e['ex_date'],symbol=e['symbol'],quantity=r['quantity'],cash=value))
            if day >= e['pay_date'] and not r['paid']:
                self.receivable -= value; cash += value; r['paid']=True
                self.ledger.append(dict(event='pay',date=day,ex_date=e['ex_date'],symbol=e['symbol'],quantity=r['quantity'],cash=value))
        self.opened.add(day)
        return cash

    def sell(self,symbol,entry_day,quantity,day):
        tax=0.
        for key,e in self.events.items():
            r=self.rights.get(key)
            if e['symbol']!=symbol or r is None or not r['accrued'] or r['entry_day']!=entry_day: continue
            q=min(quantity,r['untaxed_quantity']); r['untaxed_quantity']-=q
            charge=q*e['cash_per_share']*dividend_tax_rate(entry_day,day)
            tax+=charge
            if q:self.ledger.append(dict(event='tax',date=day,ex_date=e['ex_date'],symbol=symbol,quantity=q,cash=-charge))
        self.tax_paid+=tax
        return tax

    def adjustment(self,symbol,day):
        e=self.events.get((symbol,day)); r=self.rights.get((symbol,day))
        return e['cash_per_share'] if e and r and r['quantity'] and r['accrued'] else None
