"""米国債の 2 年・10 年利回りと長短金利差（10Y-2Y）を一次ソースから取る（KIK-779）.

一次ソースは米財務省の Daily Treasury Par Yield Curve Rates（CMT）の CSV。
取れなければ FRED（DGS2 / DGS10。中身は同じ財務省の CMT で、1 営業日ほど遅れる）に替える。
どちらも取れなければ ``available=False`` を返す。**先物（2YY=F）で代用しない。**

⚠️ なぜ先物を使わないか: risk-assessor は 2 年債に yfinance の ``2YY=F``（CBOT の
2 年債利回り先物）を使っていた。9/30 までは財務省と一致していた（4.885 vs 4.88）が、
2026-10-01 から 4.61 / 4.635 と約 17〜20bp 低く出た（限月の乗り換えとみられる）。
10Y-2Y は 0.45（正）なのに +0.63 と出て、7 指標スコアが +1、10/8 の発注ゲート
「10Y-2Y < 0.5%」が「あと 13bp」と誤って報告された。9/25 も正しくは 0.36 で、+0.71 と出ていた。
"""

from __future__ import annotations

import csv
import datetime
import io
from typing import Callable, Optional

TREASURY_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve"
    "&field_tdr_date_value={year}&page&_format=csv"
)
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"

Fetcher = Callable[[str], str]

#: 最新の営業日がこの暦日数より古ければ使わない。年末年始・米国の3連休でも 5 日程度。
#: 当年 CSV の取得に失敗して前年の値だけが取れた、などを「最新」と読まないため
MAX_AGE_DAYS = 7


def _http_get(url: str) -> str:
    import requests

    r = requests.get(url, timeout=30, headers={"User-Agent": "stock-skills/1.0"})
    r.raise_for_status()
    return r.text


def _num(v) -> Optional[float]:
    try:
        x = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return x


def parse_treasury_csv(text: str) -> dict[str, tuple[float, float]]:
    """財務省 CSV を ``{"YYYY-MM-DD": (2年, 10年)}`` にする。どちらかが空の行は捨てる."""
    out: dict[str, tuple[float, float]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        try:
            day = datetime.datetime.strptime(row.get("Date", "").strip(), "%m/%d/%Y").date()
        except ValueError:
            continue
        y2, y10 = _num(row.get("2 Yr")), _num(row.get("10 Yr"))
        if y2 is not None and y10 is not None:
            out[day.isoformat()] = (y2, y10)
    return out


def parse_fred_csv(text: str) -> dict[str, float]:
    """FRED の CSV を ``{"YYYY-MM-DD": 値}`` にする。欠損（"." や空）は捨てる."""
    out: dict[str, float] = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2:
            continue
        try:
            day = datetime.date.fromisoformat(row[0].strip())
        except ValueError:
            continue                     # ヘッダ行
        v = _num(row[1])
        if v is not None:
            out[day.isoformat()] = v
    return out


def _result(series: dict[str, tuple[float, float]], source: str, errors: list[str]) -> dict:
    days = sorted(series)
    last = days[-1]
    y2, y10 = series[last]
    history = [{"date": d, "y2": series[d][0], "y10": series[d][1],
                "spread": round(series[d][1] - series[d][0], 4)} for d in days[-30:]]
    return {
        "available": True, "source": source, "date": last,
        "y2": y2, "y10": y10, "spread": round(y10 - y2, 4),
        "history": history,
        # 財務省が取れずに FRED を使ったときは、その理由を残す（黙って切り替えない）
        "warning": "; ".join(errors) or None, "error": None,
    }


def _fresh(series: dict, today: datetime.date, errors: list[str], source: str) -> bool:
    last = max(series)
    age = (today - datetime.date.fromisoformat(last)).days
    if age > MAX_AGE_DAYS:
        errors.append(f"{source}: 最新 {last} が {age} 日前（{MAX_AGE_DAYS} 日超）で古い")
        return False
    return True


def get_treasury_curve(today: Optional[datetime.date] = None,
                       fetch: Fetcher = _http_get) -> dict:
    """10Y-2Y を返す。

    Returns
    -------
    dict
        ``available`` / ``source``（"treasury" か "fred"）/ ``date``（最新の営業日）/
        ``y2`` / ``y10`` / ``spread``（10Y-2Y, %pt）/ ``history``（直近 30 営業日）/
        ``warning``（財務省を取れず FRED にした理由、当年 CSV の取得失敗など）/ ``error``。
        取れない、または最新日が ``MAX_AGE_DAYS`` より古ければ ``available=False`` と ``error``。
        値は % 単位（5.28 = 5.28%）。
    """
    today = today or datetime.date.today()
    errors: list[str] = []

    series: dict[str, tuple[float, float]] = {}
    # 年初は当年の CSV が空なので前年も読む
    for year in (today.year, today.year - 1):
        try:
            series.update(parse_treasury_csv(fetch(TREASURY_URL.format(year=year))))
        except Exception as e:  # noqa: BLE001 — 取得失敗は理由を残してフォールバックする
            errors.append(f"treasury {year}: {type(e).__name__}: {e}")
        if series:
            break
    if series and _fresh(series, today, errors, "treasury"):
        return _result(series, "treasury", errors)
    if not series and not errors:
        errors.append("treasury: 2 Yr / 10 Yr の行がない")

    try:
        y2 = parse_fred_csv(fetch(FRED_URL.format(series="DGS2")))
        y10 = parse_fred_csv(fetch(FRED_URL.format(series="DGS10")))
        both = {d: (y2[d], y10[d]) for d in y2.keys() & y10.keys()}
        if both and _fresh(both, today, errors, "fred"):
            return _result(both, "fred", errors)
        if not both:
            errors.append("fred: DGS2 と DGS10 に共通の日付がない")
    except Exception as e:  # noqa: BLE001
        errors.append(f"fred: {type(e).__name__}: {e}")

    return {"available": False, "source": None, "date": None, "y2": None, "y10": None,
            "spread": None, "history": [], "warning": None, "error": "; ".join(errors)}
