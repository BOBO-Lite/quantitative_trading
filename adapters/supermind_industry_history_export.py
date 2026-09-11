"""在SuperMind研究环境按年度导出历史时点一级行业成分。

每次默认只导出12个月，下载后修改START_MONTH继续。只读数据，不含交易API。
"""

from datetime import datetime

import pandas as pd
from mindgo_api import get_all_securities, get_industry_relate, get_industry_stocks


START_YEAR = 2018
END_YEAR = 2026
INDUSTRY_TYPE = "industryid1"
CLASSIFICATION_NAME = "SuperMind一级行业分类"


def write_json(payload, path):
    pd.Series(payload, dtype=object).to_json(path, force_ascii=False, indent=2)


def month_ends(start_month, count):
    start = pd.Timestamp(start_month + "-01")
    return [
        (start + pd.offsets.MonthEnd(i + 1)).strftime("%Y%m%d")
        for i in range(count)
        if start + pd.offsets.MonthEnd(i + 1) <= pd.Timestamp.today()
    ]


def export_industry_history(year):
    start_month = "{}-01".format(year)
    output_path = "supermind_industry_history_{}.json".format(year)
    payload = {
        "schema_version": 1,
        "source": "supermind_get_industry_relate_and_stocks",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "industry_type": INDUSTRY_TYPE,
        "classification_name": CLASSIFICATION_NAME,
        "year": year,
        "start_month": start_month,
        "month_count": 12,
        "snapshots": {},
        "universe_snapshots": {},
        "failures": [],
    }
    for date in month_ends(start_month, 12):
        try:
            securities = get_all_securities("stock", date)
            universe_rows = []
            for symbol, security in securities.iterrows():
                universe_rows.append({
                    "date": date,
                    "symbol": str(symbol),
                    "name": str(security.get("display_name", "")),
                    "listed_date": str(security.get("listed_date", ""))[:10],
                    "de_listed_date": str(security.get("de_listed_date", ""))[:10],
                    "exchange": str(security.get("exchange", "")),
                })
            payload["universe_snapshots"][date] = universe_rows
            industries = get_industry_relate(date=date, types=INDUSTRY_TYPE)
            date_rows = []
            for industry_name, row in industries.iterrows():
                industry_code = str(row["industry_symbol"])
                members = get_industry_stocks(industry_code, date)
                for symbol in members:
                    date_rows.append({
                        "date": date,
                        "symbol": str(symbol),
                        "industry_code": industry_code,
                        "industry_name": str(industry_name),
                    })
            payload["snapshots"][date] = date_rows
            print("完成月末", date, "股票", len(universe_rows), "行业映射", len(date_rows))
        except Exception as exc:
            payload["failures"].append({
                "date": date,
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
            print("行业月末失败", date, type(exc).__name__, str(exc))
            write_json(payload, output_path)
            raise RuntimeError("导出失败，已停止，避免继续生成无效年度文件")
        write_json(payload, output_path)
    payload["status"] = "completed" if not payload["failures"] else "completed_with_failures"
    payload["finished_at"] = datetime.now().isoformat(timespec="seconds")
    write_json(payload, output_path)
    return output_path


for export_year in range(START_YEAR, END_YEAR + 1):
    path = export_industry_history(export_year)
    print("年度导出完成", export_year, path)
