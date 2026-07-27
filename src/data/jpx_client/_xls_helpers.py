"""XLS パース共通ヘルパー。列ヘッダー動的検出・数値抽出。"""

import io
import re
import sys
from typing import Optional

import pandas as pd


def read_xls(data: bytes, engine: str = "xlrd") -> Optional[pd.DataFrame]:
    try:
        return pd.read_excel(io.BytesIO(data), engine=engine, header=None)
    except Exception as e:
        print(f"[jpx_client] XLS read failed ({engine}): {e}", file=sys.stderr)
        return None


def to_numeric(series: "pd.Series") -> "pd.Series":
    return pd.to_numeric(series, errors="coerce")


def find_row_by_keyword(df: pd.DataFrame, keyword: str, col: int = 0) -> Optional[int]:
    """指定列にキーワードを含む最初の行インデックスを返す。"""
    for i, val in df.iloc[:, col].items():
        if isinstance(val, str) and keyword.lower() in val.lower():
            return i
    return None


def extract_number(df: pd.DataFrame, row: int, col: int) -> Optional[float]:
    """DataFrame の特定セルを float で返す。変換失敗時は None。"""
    try:
        val = df.iloc[row, col]
        if pd.isna(val):
            return None
        return float(val)
    except (ValueError, TypeError, IndexError):
        return None


def parse_date_from_cell(df: pd.DataFrame, row: int, col: int = 0) -> Optional[str]:
    """セルから 'YYYY/M/DD' または 'YYYY-MM-DD' 形式の日付文字列を抽出する。"""
    try:
        val = str(df.iloc[row, col])
        m = re.search(r"(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})", val)
        if m:
            y, mo, d = m.groups()
            return f"{y}-{int(mo):02d}-{int(d):02d}"
        # ISO datetime from pandas (e.g. "2026-04-27 00:00:00")
        import pandas as _pd
        cell = df.iloc[row, col]
        if hasattr(cell, "strftime"):
            return cell.strftime("%Y-%m-%d")
    except Exception:
        pass
    return None
