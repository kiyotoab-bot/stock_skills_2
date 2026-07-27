"""EDINET 書類一覧取得・フィルタリング。"""

from datetime import date as _date
from typing import Optional

from src.data.edinet_client._cache import get as cache_get
from src.data.edinet_client._cache import is_fresh, set as cache_set
from src.data.edinet_client._common import TTL_DOCUMENTS, _get_json, is_available
from src.data.edinet_client._company import lookup, observe

# 大量保有報告書のdocDescription パターン
_LARGE_SHAREHOLDING_KEYWORDS = ["大量保有報告書", "変更報告書"]


def _today() -> str:
    return _date.today().isoformat()


def get_document_list(target_date: Optional[str] = None) -> list[dict]:
    """指定日の EDINET 提出書類一覧を返す。

    Args:
        target_date: "YYYY-MM-DD" 形式。None の場合は本日。

    Returns:
        書類メタデータのリスト。API 未設定・失敗時は []。
    """
    d = target_date or _today()
    cache_key = f"edinet:docs:{d}"

    if is_fresh(cache_key, TTL_DOCUMENTS):
        return cache_get(cache_key) or []

    if not is_available():
        return []

    # type=2: 書類情報あり（xbrlFlag等）
    data = _get_json("/documents.json", {"date": d, "type": "2"})
    if not data:
        # type=1 でリトライ（API key があっても type=2 が失敗するケース）
        data = _get_json("/documents.json", {"date": d, "type": "1"})
    if not data:
        return []

    results = data.get("results") or []
    cache_set(cache_key, results)

    # 観測した会社情報を永続マップに保存
    for doc in results:
        observe(
            doc.get("edinetCode"),
            doc.get("filerName"),
            doc.get("secCode"),
        )

    return results


def get_large_shareholding(target_date: Optional[str] = None) -> dict:
    """大量保有報告書・変更報告書を取得して返す。

    Returns:
        {
            "date": "YYYY-MM-DD",
            "filings": [
                {
                    "doc_id": str,
                    "filer_edinet": str,
                    "filer_name": str | None,
                    "filer_ticker": str | None,
                    "target_edinet": str | None,
                    "target_name": str | None,
                    "target_ticker": str | None,
                    "submit_time": str,
                    "doc_type": str,
                    "pdf_flag": bool,
                }
            ],
            "count": int,
            "available": bool,
            "error": str | None,
        }
    """
    d = target_date or _today()

    if not is_available():
        return {
            "date": d, "filings": [], "count": 0,
            "available": False, "error": "EDINET_API_KEY not set",
        }

    all_docs = get_document_list(d)
    filings = []
    for doc in all_docs:
        desc = doc.get("docDescription") or ""
        if not any(kw in desc for kw in _LARGE_SHAREHOLDING_KEYWORDS):
            continue

        filer_edinet  = doc.get("edinetCode")
        target_edinet = doc.get("issuerEdinetCode")

        # filerName はAPIレスポンスに直接含まれる
        filer_name_api = doc.get("filerName")
        sec_code_api   = doc.get("secCode")
        filer_ticker   = (
            f"{sec_code_api}.T"
            if sec_code_api and sec_code_api.isdigit()
            else lookup(filer_edinet)["ticker"]
        )
        target_info = lookup(target_edinet)

        filings.append({
            "doc_id":        doc.get("docID"),
            "filer_edinet":  filer_edinet,
            "filer_name":    filer_name_api,
            "filer_ticker":  filer_ticker,
            "target_edinet": target_edinet,
            "target_name":   target_info["name"],
            "target_ticker": target_info["ticker"],
            "submit_time":   doc.get("submitDateTime"),
            "doc_type":      desc,
            "pdf_flag":      doc.get("pdfFlag") == "1",
        })

    return {
        "date": d,
        "filings": filings,
        "count": len(filings),
        "available": True,
        "error": None,
    }


def get_disclosures(
    target_date: Optional[str] = None,
    keyword: Optional[str] = None,
    ticker: Optional[str] = None,
) -> dict:
    """汎用書類検索。keyword または ticker（issuerEdinetCode 経由）でフィルタ。

    Args:
        target_date: 対象日。
        keyword: docDescription に含む文字列（例: "有価証券報告書"）。
        ticker: 対象銘柄ティッカー（例: "5401.T"）。issuerEdintetCode でマッチ。

    Returns:
        get_large_shareholding と同スキーマ。
    """
    d = target_date or _today()

    if not is_available():
        return {
            "date": d, "filings": [], "count": 0,
            "available": False, "error": "EDINET_API_KEY not set",
        }

    all_docs = get_document_list(d)

    # ticker → edinet_code の逆引き（company_map から）
    target_edinet_filter: Optional[str] = None
    if ticker:
        from src.data.edinet_client._company import get_company_map
        code = ticker.replace(".T", "").replace(".JP", "")
        for ec, info in get_company_map().items():
            if info.get("securities_code") == code:
                target_edinet_filter = ec
                break

    filings = []
    for doc in all_docs:
        desc = doc.get("docDescription") or ""
        if keyword and keyword not in desc:
            continue
        if target_edinet_filter and doc.get("issuerEdinetCode") != target_edinet_filter:
            continue

        filer_edinet   = doc.get("edinetCode")
        target_edinet  = doc.get("issuerEdinetCode")
        filer_name_api = doc.get("filerName")
        sec_code_api   = doc.get("secCode")
        filer_ticker   = (
            f"{sec_code_api}.T"
            if sec_code_api and sec_code_api.isdigit()
            else lookup(filer_edinet)["ticker"]
        )
        target_info = lookup(target_edinet)

        filings.append({
            "doc_id":        doc.get("docID"),
            "filer_edinet":  filer_edinet,
            "filer_name":    filer_name_api,
            "filer_ticker":  filer_ticker,
            "target_edinet": target_edinet,
            "target_name":   target_info["name"],
            "target_ticker": target_info["ticker"],
            "submit_time":   doc.get("submitDateTime"),
            "doc_type":      desc,
            "pdf_flag":      doc.get("pdfFlag") == "1",
        })

    return {
        "date": d, "filings": filings, "count": len(filings),
        "available": True, "error": None,
    }
