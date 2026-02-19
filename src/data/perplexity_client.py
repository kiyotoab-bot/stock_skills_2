"""Perplexity API (Sonar Pro / Deep Research) client for web research (KIK-426).

Uses the Perplexity Chat Completions API (OpenAI-compatible) for web search
with citations. Sonar Pro for fast research, Deep Research for exhaustive analysis.

API key is read from the PERPLEXITY_API_KEY environment variable.
When the key is not set, is_available() returns False and
all search functions return empty results (graceful degradation).
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


_API_URL = "https://api.perplexity.ai/chat/completions"
_MODEL_SONAR_PRO = "sonar-pro"
_MODEL_DEEP_RESEARCH = "sonar-deep-research"
_error_warned = [False]

# ---------------------------------------------------------------------------
# Empty result constants
# ---------------------------------------------------------------------------

EMPTY_STOCK = {
    "summary": "",
    "recent_developments": [],
    "analyst_consensus": "",
    "risks_and_concerns": [],
    "catalysts": [],
    "raw_response": "",
    "citations": [],
}

EMPTY_INDUSTRY = {
    "overview": "",
    "trends": [],
    "key_players": [],
    "growth_outlook": "",
    "risks": [],
    "raw_response": "",
    "citations": [],
}

EMPTY_MARKET = {
    "summary": "",
    "key_drivers": [],
    "sentiment": "",
    "outlook": "",
    "risks": [],
    "raw_response": "",
    "citations": [],
}

EMPTY_BUSINESS = {
    "overview": "",
    "segments": [],
    "revenue_model": "",
    "competitive_position": "",
    "growth_strategy": [],
    "risks": [],
    "raw_response": "",
    "citations": [],
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def is_available() -> bool:
    """Check if Perplexity API is available (PERPLEXITY_API_KEY is set)."""
    return bool(os.environ.get("PERPLEXITY_API_KEY"))


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _get_api_key() -> Optional[str]:
    """Return the API key or None."""
    return os.environ.get("PERPLEXITY_API_KEY")


def _is_japanese_stock(symbol: str) -> bool:
    """Return True if *symbol* looks like a JPX ticker (.T or .S suffix)."""
    return symbol.upper().endswith((".T", ".S"))


def _contains_japanese(text: str) -> bool:
    """Return True if *text* contains Japanese characters."""
    return any(0x3000 <= ord(c) <= 0x9FFF for c in text)


def _call_api(
    messages: list[dict],
    model: str = _MODEL_SONAR_PRO,
    timeout: int = 30,
) -> dict:
    """Call the Perplexity Chat Completions API.

    Parameters
    ----------
    messages : list[dict]
        OpenAI-compatible messages array.
    model : str
        Model name (sonar-pro or sonar-deep-research).
    timeout : int
        Request timeout in seconds.

    Returns
    -------
    dict
        Keys: text (str), citations (list[str]).
        Empty on error.
    """
    api_key = _get_api_key()
    if not api_key:
        return {"text": "", "citations": []}

    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": model,
            "messages": messages,
        }

        response = requests.post(
            _API_URL,
            headers=headers,
            json=payload,
            timeout=timeout,
        )

        if response.status_code != 200:
            if not _error_warned[0]:
                print(
                    f"[perplexity_client] API error: "
                    f"status={response.status_code} (subsequent errors suppressed)",
                    file=sys.stderr,
                )
                _error_warned[0] = True
            return {"text": "", "citations": []}

        data = response.json()

        # Extract text from chat completion response
        text = ""
        choices = data.get("choices", [])
        if choices:
            message = choices[0].get("message", {})
            text = message.get("content", "")

        # Extract citations
        citations = data.get("citations", [])
        if not isinstance(citations, list):
            citations = []

        return {"text": text, "citations": citations}

    except requests.exceptions.Timeout:
        if not _error_warned[0]:
            print(
                "[perplexity_client] Timeout (subsequent errors suppressed)",
                file=sys.stderr,
            )
            _error_warned[0] = True
        return {"text": "", "citations": []}
    except requests.exceptions.RequestException as e:
        if not _error_warned[0]:
            print(
                f"[perplexity_client] Request error: {e} (subsequent errors suppressed)",
                file=sys.stderr,
            )
            _error_warned[0] = True
        return {"text": "", "citations": []}
    except Exception as e:
        if not _error_warned[0]:
            print(
                f"[perplexity_client] Unexpected error: {e} (subsequent errors suppressed)",
                file=sys.stderr,
            )
            _error_warned[0] = True
        return {"text": "", "citations": []}


def _parse_json_response(raw_text: str) -> dict:
    """Extract a JSON object from *raw_text*.

    Finds the first ``{`` and last ``}`` and attempts ``json.loads``.
    Returns an empty dict on failure.
    """
    try:
        json_start = raw_text.find("{")
        json_end = raw_text.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            return json.loads(raw_text[json_start:json_end])
    except (json.JSONDecodeError, ValueError):
        pass
    return {}


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_stock_messages(symbol: str, company_name: str = "") -> list[dict]:
    """Build messages for stock research."""
    name_part = f" ({company_name})" if company_name else ""
    if _is_japanese_stock(symbol) or _contains_japanese(company_name):
        content = (
            f"{symbol}{name_part} について、最新のWeb情報をもとに以下を調査してください。\n\n"
            f"1. 直近の重要な動向まとめ\n"
            f"2. 最近の注目ニュース・出来事\n"
            f"3. アナリストのコンセンサス\n"
            f"4. リスク・懸念材料\n"
            f"5. 今後の材料・カタリスト\n\n"
            f"JSON形式で回答:\n"
            f'{{\n'
            f'  "summary": "全体まとめ",\n'
            f'  "recent_developments": ["動向1", "動向2"],\n'
            f'  "analyst_consensus": "アナリスト見解の要約",\n'
            f'  "risks_and_concerns": ["リスク1", "リスク2"],\n'
            f'  "catalysts": ["材料1", "材料2"]\n'
            f'}}'
        )
    else:
        content = (
            f"Research {symbol}{name_part} using the latest web information. Provide:\n\n"
            f"1. Summary of recent key developments\n"
            f"2. Notable recent news and events\n"
            f"3. Analyst consensus view\n"
            f"4. Key risks and concerns\n"
            f"5. Upcoming catalysts\n\n"
            f"Respond in JSON:\n"
            f'{{\n'
            f'  "summary": "overall summary",\n'
            f'  "recent_developments": ["dev1", "dev2"],\n'
            f'  "analyst_consensus": "analyst consensus summary",\n'
            f'  "risks_and_concerns": ["risk1", "risk2"],\n'
            f'  "catalysts": ["catalyst1", "catalyst2"]\n'
            f'}}'
        )
    return [{"role": "user", "content": content}]


def _build_industry_messages(theme: str) -> list[dict]:
    """Build messages for industry research."""
    if _contains_japanese(theme):
        content = (
            f"「{theme}」業界・テーマについて、最新のWeb情報をもとに以下を調査してください。\n\n"
            f"1. 業界概要と現状\n"
            f"2. 最新トレンド\n"
            f"3. 主要プレイヤー\n"
            f"4. 成長見通し\n"
            f"5. リスク要因\n\n"
            f"JSON形式で回答:\n"
            f'{{\n'
            f'  "overview": "業界概要",\n'
            f'  "trends": ["トレンド1", "トレンド2"],\n'
            f'  "key_players": ["プレイヤー1", "プレイヤー2"],\n'
            f'  "growth_outlook": "成長見通し",\n'
            f'  "risks": ["リスク1", "リスク2"]\n'
            f'}}'
        )
    else:
        content = (
            f"Research the \"{theme}\" industry/theme using the latest web information. Provide:\n\n"
            f"1. Industry overview and current state\n"
            f"2. Latest trends\n"
            f"3. Key players\n"
            f"4. Growth outlook\n"
            f"5. Risk factors\n\n"
            f"Respond in JSON:\n"
            f'{{\n'
            f'  "overview": "industry overview",\n'
            f'  "trends": ["trend1", "trend2"],\n'
            f'  "key_players": ["player1", "player2"],\n'
            f'  "growth_outlook": "growth outlook summary",\n'
            f'  "risks": ["risk1", "risk2"]\n'
            f'}}'
        )
    return [{"role": "user", "content": content}]


def _build_market_messages(market: str) -> list[dict]:
    """Build messages for market research."""
    content = (
        f"「{market}」の最新マーケット概況をWeb情報をもとに調査してください。\n\n"
        f"1. 市場の現状まとめ\n"
        f"2. 主な変動要因\n"
        f"3. 投資家センチメント\n"
        f"4. 今後の見通し\n"
        f"5. リスク要因\n\n"
        f"JSON形式で回答:\n"
        f'{{\n'
        f'  "summary": "市場概要",\n'
        f'  "key_drivers": ["要因1", "要因2"],\n'
        f'  "sentiment": "センチメントの要約",\n'
        f'  "outlook": "今後の見通し",\n'
        f'  "risks": ["リスク1", "リスク2"]\n'
        f'}}'
    )
    return [{"role": "user", "content": content}]


def _build_business_messages(symbol: str, company_name: str = "") -> list[dict]:
    """Build messages for business model deep research."""
    name_part = f" ({company_name})" if company_name else ""
    if _is_japanese_stock(symbol) or _contains_japanese(company_name):
        content = (
            f"{symbol}{name_part} のビジネスモデルについて、徹底的にWeb情報を調査してください。\n\n"
            f"1. 事業概要（何で稼いでいるか）\n"
            f"2. 事業セグメント構成\n"
            f"3. 収益モデル\n"
            f"4. 競争ポジション（業界内の立ち位置）\n"
            f"5. 成長戦略\n"
            f"6. ビジネスリスク\n\n"
            f"JSON形式で回答:\n"
            f'{{\n'
            f'  "overview": "事業概要",\n'
            f'  "segments": [\n'
            f'    {{"name": "セグメント名", "revenue_share": "売上比率", "description": "概要"}}\n'
            f'  ],\n'
            f'  "revenue_model": "収益モデルの説明",\n'
            f'  "competitive_position": "競争ポジションの説明",\n'
            f'  "growth_strategy": ["戦略1", "戦略2"],\n'
            f'  "risks": ["リスク1", "リスク2"]\n'
            f'}}'
        )
    else:
        content = (
            f"Conduct thorough research on the business model of {symbol}{name_part}. Provide:\n\n"
            f"1. Business overview (how the company makes money)\n"
            f"2. Business segments\n"
            f"3. Revenue model\n"
            f"4. Competitive position in the industry\n"
            f"5. Growth strategy\n"
            f"6. Business risks\n\n"
            f"Respond in JSON:\n"
            f'{{\n'
            f'  "overview": "business overview",\n'
            f'  "segments": [\n'
            f'    {{"name": "Segment Name", "revenue_share": "e.g. 40%", "description": "overview"}}\n'
            f'  ],\n'
            f'  "revenue_model": "revenue model description",\n'
            f'  "competitive_position": "competitive position description",\n'
            f'  "growth_strategy": ["strategy1", "strategy2"],\n'
            f'  "risks": ["risk1", "risk2"]\n'
            f'}}'
        )
    return [{"role": "user", "content": content}]


# ---------------------------------------------------------------------------
# Public search functions
# ---------------------------------------------------------------------------

def search_stock(
    symbol: str,
    company_name: str = "",
    timeout: int = 30,
) -> dict:
    """Research a stock via Perplexity Sonar Pro.

    Parameters
    ----------
    symbol : str
        Ticker symbol (e.g. "7203.T", "AAPL").
    company_name : str
        Company name for prompt accuracy.
    timeout : int
        Request timeout in seconds.

    Returns
    -------
    dict
        See EMPTY_STOCK for the schema. Includes citations list.
    """
    messages = _build_stock_messages(symbol, company_name)
    raw = _call_api(messages, model=_MODEL_SONAR_PRO, timeout=timeout)

    text = raw.get("text", "")
    citations = raw.get("citations", [])

    if not text:
        return dict(EMPTY_STOCK)

    result = dict(EMPTY_STOCK)
    result["raw_response"] = text
    result["citations"] = citations

    parsed = _parse_json_response(text)
    if not parsed:
        return result

    if isinstance(parsed.get("summary"), str):
        result["summary"] = parsed["summary"]
    if isinstance(parsed.get("recent_developments"), list):
        result["recent_developments"] = parsed["recent_developments"]
    if isinstance(parsed.get("analyst_consensus"), str):
        result["analyst_consensus"] = parsed["analyst_consensus"]
    if isinstance(parsed.get("risks_and_concerns"), list):
        result["risks_and_concerns"] = parsed["risks_and_concerns"]
    if isinstance(parsed.get("catalysts"), list):
        result["catalysts"] = parsed["catalysts"]

    return result


def search_industry(
    theme: str,
    timeout: int = 30,
) -> dict:
    """Research an industry or theme via Perplexity Sonar Pro.

    Parameters
    ----------
    theme : str
        Industry name or theme (e.g. "semiconductor", "EV", "AI").
    timeout : int
        Request timeout in seconds.

    Returns
    -------
    dict
        See EMPTY_INDUSTRY for the schema. Includes citations list.
    """
    messages = _build_industry_messages(theme)
    raw = _call_api(messages, model=_MODEL_SONAR_PRO, timeout=timeout)

    text = raw.get("text", "")
    citations = raw.get("citations", [])

    if not text:
        return dict(EMPTY_INDUSTRY)

    result = dict(EMPTY_INDUSTRY)
    result["raw_response"] = text
    result["citations"] = citations

    parsed = _parse_json_response(text)
    if not parsed:
        return result

    if isinstance(parsed.get("overview"), str):
        result["overview"] = parsed["overview"]
    if isinstance(parsed.get("trends"), list):
        result["trends"] = parsed["trends"]
    if isinstance(parsed.get("key_players"), list):
        result["key_players"] = parsed["key_players"]
    if isinstance(parsed.get("growth_outlook"), str):
        result["growth_outlook"] = parsed["growth_outlook"]
    if isinstance(parsed.get("risks"), list):
        result["risks"] = parsed["risks"]

    return result


def search_market(
    market: str,
    timeout: int = 30,
) -> dict:
    """Research a market or index via Perplexity Sonar Pro.

    Parameters
    ----------
    market : str
        Market name or index (e.g. "Nikkei 225", "S&P500").
    timeout : int
        Request timeout in seconds.

    Returns
    -------
    dict
        See EMPTY_MARKET for the schema. Includes citations list.
    """
    messages = _build_market_messages(market)
    raw = _call_api(messages, model=_MODEL_SONAR_PRO, timeout=timeout)

    text = raw.get("text", "")
    citations = raw.get("citations", [])

    if not text:
        return dict(EMPTY_MARKET)

    result = dict(EMPTY_MARKET)
    result["raw_response"] = text
    result["citations"] = citations

    parsed = _parse_json_response(text)
    if not parsed:
        return result

    if isinstance(parsed.get("summary"), str):
        result["summary"] = parsed["summary"]
    if isinstance(parsed.get("key_drivers"), list):
        result["key_drivers"] = parsed["key_drivers"]
    if isinstance(parsed.get("sentiment"), str):
        result["sentiment"] = parsed["sentiment"]
    if isinstance(parsed.get("outlook"), str):
        result["outlook"] = parsed["outlook"]
    if isinstance(parsed.get("risks"), list):
        result["risks"] = parsed["risks"]

    return result


def search_business(
    symbol: str,
    company_name: str = "",
    timeout: int = 120,
) -> dict:
    """Research a company's business model via Perplexity Deep Research.

    Uses sonar-deep-research for exhaustive multi-step analysis.

    Parameters
    ----------
    symbol : str
        Ticker symbol (e.g. "7751.T", "AAPL").
    company_name : str
        Company name for prompt accuracy.
    timeout : int
        Request timeout in seconds (longer for deep research).

    Returns
    -------
    dict
        See EMPTY_BUSINESS for the schema. Includes citations list.
    """
    messages = _build_business_messages(symbol, company_name)
    raw = _call_api(messages, model=_MODEL_DEEP_RESEARCH, timeout=timeout)

    text = raw.get("text", "")
    citations = raw.get("citations", [])

    if not text:
        return dict(EMPTY_BUSINESS)

    result = dict(EMPTY_BUSINESS)
    result["raw_response"] = text
    result["citations"] = citations

    parsed = _parse_json_response(text)
    if not parsed:
        return result

    if isinstance(parsed.get("overview"), str):
        result["overview"] = parsed["overview"]

    segments = parsed.get("segments")
    if isinstance(segments, list):
        validated = []
        for seg in segments:
            if isinstance(seg, dict):
                validated.append({
                    "name": seg.get("name", "") if isinstance(seg.get("name"), str) else "",
                    "revenue_share": seg.get("revenue_share", "") if isinstance(seg.get("revenue_share"), str) else "",
                    "description": seg.get("description", "") if isinstance(seg.get("description"), str) else "",
                })
        result["segments"] = validated

    if isinstance(parsed.get("revenue_model"), str):
        result["revenue_model"] = parsed["revenue_model"]
    if isinstance(parsed.get("competitive_position"), str):
        result["competitive_position"] = parsed["competitive_position"]
    if isinstance(parsed.get("growth_strategy"), list):
        result["growth_strategy"] = parsed["growth_strategy"]
    if isinstance(parsed.get("risks"), list):
        result["risks"] = parsed["risks"]

    return result
