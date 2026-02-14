"""Scenario definitions and mappings for portfolio stress testing (KIK-365).

This module contains data-only definitions extracted from scenario_analysis.py:
- SCENARIOS: preset scenario definitions (8 scenarios)
- SCENARIO_ALIASES: natural language aliases for scenario lookup
- _TARGET_TO_SECTORS: scenario target to sector mapping
- _SUFFIX_TO_REGION: ticker suffix to region mapping
- _ETF_ASSET_CLASS: ETF ticker to asset class mapping
"""

from typing import Optional


# ---------------------------------------------------------------------------
# プリセットシナリオ定義
# ---------------------------------------------------------------------------

SCENARIOS = {
    "triple_decline": {
        "name": "トリプル安（株安・債券安・円安）",
        "trigger": "財政不安・格下げ",
        "base_shock": -0.20,
        "effects": {
            "primary": [
                {"target": "日本株全般", "impact": -0.12, "reason": "海外勢売り"},
                {"target": "円建て", "impact": -0.10, "reason": "円安15円"},
            ],
            "secondary": [
                {"target": "グロース株", "impact": -0.12, "reason": "金利上昇"},
                {"target": "輸出企業", "impact": +0.06, "reason": "円安メリット"},
                {"target": "内需企業", "impact": -0.07, "reason": "コスト増"},
                {"target": "銀行", "impact": +0.06, "reason": "利ザヤ改善"},
                {"target": "金・安全資産", "impact": +0.03, "reason": "リスク回避で一部資金流入"},
                {"target": "長期債", "impact": -0.10, "reason": "債券安（トリプル安の一角）"},
            ],
            "currency": {"usd_jpy_change": +15, "impact_on_foreign": +0.097},
            "offset": ["輸出企業の円安メリット", "銀行の金利上昇メリット"],
            "time_axis": "即座→数週間で二次効果→介入で急反転リスク",
        },
    },
    "yen_depreciation": {
        "name": "ドル高円安",
        "trigger": "日米金利差拡大",
        "base_shock": -0.10,
        "effects": {
            "primary": [
                {"target": "米国株(円建て)", "impact": +0.097, "reason": "為替益"},
                {"target": "日本輸出株", "impact": +0.06, "reason": "円安メリット"},
                {"target": "日本内需株", "impact": -0.07, "reason": "コスト増"},
            ],
            "secondary": [
                {"target": "全外貨資産", "impact": -0.05, "reason": "介入→急反転リスク(165→158)"},
                {"target": "金・安全資産", "impact": +0.03, "reason": "ドル高でも金価格は底堅い"},
                {"target": "長期債", "impact": -0.03, "reason": "金利差拡大で債券価格下落"},
            ],
            "currency": {"usd_jpy_change": +10, "impact_on_foreign": +0.065},
            "offset": ["輸出企業メリット"],
            "time_axis": "段階的: 155→165(プラス) → 165→175(警戒) → 介入(急反転)",
        },
    },
    "us_recession": {
        "name": "米国リセッション",
        "trigger": "景気後退入り確認",
        "base_shock": -0.25,
        "effects": {
            "primary": [
                {"target": "米国株全般", "impact": -0.25, "reason": "企業業績悪化"},
                {"target": "シクリカル株", "impact": -0.35, "reason": "景気敏感"},
            ],
            "secondary": [
                {"target": "日本輸出株", "impact": -0.15, "reason": "需要減"},
                {"target": "ASEAN株", "impact": -0.10, "reason": "資金引き揚げ"},
                {"target": "ディフェンシブ株", "impact": -0.05, "reason": "相対的に耐性"},
                {"target": "金・安全資産", "impact": +0.08, "reason": "安全資産需要（リスク回避）"},
                {"target": "長期債", "impact": +0.10, "reason": "利下げ期待で債券価格上昇"},
            ],
            "currency": {"usd_jpy_change": -10, "impact_on_foreign": -0.065},
            "offset": ["ディフェンシブ銘柄", "円高で外貨建て資産のヘッジ効果"],
            "time_axis": "確認→半年〜1年で底打ち→金融緩和で反転",
        },
    },
    "boj_rate_hike": {
        "name": "日銀利上げ加速",
        "trigger": "インフレ持続で追加利上げ",
        "base_shock": -0.15,
        "effects": {
            "primary": [
                {"target": "グロース株", "impact": -0.15, "reason": "割引率上昇"},
                {"target": "不動産", "impact": -0.12, "reason": "金利コスト増"},
                {"target": "銀行", "impact": +0.08, "reason": "利ザヤ拡大"},
            ],
            "secondary": [
                {"target": "高配当株", "impact": -0.05, "reason": "債券との比較劣後"},
                {"target": "円建て外貨資産", "impact": -0.05, "reason": "円高"},
                {"target": "金・安全資産", "impact": -0.02, "reason": "金利上昇で機会コスト増"},
                {"target": "長期債", "impact": -0.05, "reason": "金利上昇で債券価格下落"},
            ],
            "currency": {"usd_jpy_change": -8, "impact_on_foreign": -0.052},
            "offset": ["銀行セクター上昇", "円高で輸入コスト低下"],
            "time_axis": "利上げ発表→即座に反応→半年で織り込み",
        },
    },
    "us_china_conflict": {
        "name": "米中対立激化",
        "trigger": "関税・制裁強化",
        "base_shock": -0.15,
        "effects": {
            "primary": [
                {"target": "中国関連株", "impact": -0.20, "reason": "サプライチェーン混乱"},
                {"target": "半導体", "impact": -0.15, "reason": "輸出規制"},
            ],
            "secondary": [
                {"target": "ASEAN株", "impact": +0.05, "reason": "サプライチェーン移転先"},
                {"target": "防衛関連", "impact": +0.08, "reason": "地政学リスク"},
                {"target": "金・安全資産", "impact": +0.08, "reason": "地政学リスクで安全資産需要"},
                {"target": "長期債", "impact": +0.03, "reason": "質への逃避（国債需要）"},
            ],
            "currency": {"usd_jpy_change": -3, "impact_on_foreign": -0.02},
            "offset": ["ASEANへの生産移転メリット", "防衛関連上昇"],
            "time_axis": "発表→数日で急落→数ヶ月で代替先に資金移動",
        },
    },
    "inflation_resurgence": {
        "name": "インフレ再燃",
        "trigger": "CPI再加速",
        "base_shock": -0.15,
        "effects": {
            "primary": [
                {"target": "グロース株", "impact": -0.18, "reason": "利上げ再開懸念"},
                {"target": "長期債", "impact": -0.10, "reason": "金利上昇"},
            ],
            "secondary": [
                {"target": "エネルギー株", "impact": +0.10, "reason": "原油高"},
                {"target": "素材株", "impact": +0.05, "reason": "資源価格上昇"},
                {"target": "消費関連", "impact": -0.08, "reason": "購買力低下"},
                {"target": "金・安全資産", "impact": +0.08, "reason": "インフレヘッジ需要"},
            ],
            "currency": {"usd_jpy_change": +5, "impact_on_foreign": +0.032},
            "offset": ["コモディティ関連の上昇", "インフレヘッジ資産"],
            "time_axis": "CPI発表→即座に反応→3-6ヶ月で方向性確定",
        },
    },
    "tech_crash": {
        "name": "テック暴落",
        "trigger": "AI収益化の失望・バリュエーション調整・規制強化",
        "base_shock": -0.30,
        "effects": {
            "primary": [
                {"target": "テック株", "impact": -0.35, "reason": "NASDAQ -30%、バリュエーション修正"},
                {"target": "半導体", "impact": -0.40, "reason": "AI関連の過剰期待修正"},
            ],
            "secondary": [
                {"target": "非テック株", "impact": -0.08, "reason": "リスクオフ波及"},
                {"target": "ディフェンシブ株", "impact": -0.03, "reason": "質への逃避で相対的に耐性"},
                {"target": "金・安全資産", "impact": +0.06, "reason": "安全資産需要"},
                {"target": "長期債", "impact": +0.05, "reason": "質への逃避で国債需要"},
            ],
            "currency": {"usd_jpy_change": -8, "impact_on_foreign": -0.052},
            "offset": ["ディフェンシブ銘柄の耐性", "金・債券への資金逃避", "円高による外貨資産圧縮"],
            "time_axis": "暴落→数日で急落→数週間で二次波及→数ヶ月で底値模索",
        },
    },
    "yen_appreciation": {
        "name": "円高ドル安",
        "trigger": "FRB利下げ加速＋日銀追加利上げ",
        "base_shock": -0.10,
        "effects": {
            "primary": [
                {"target": "全外貨資産", "impact": -0.13, "reason": "USD/JPY -20円 (153→133円)"},
                {"target": "日本輸出株", "impact": -0.12, "reason": "円高デメリット"},
            ],
            "secondary": [
                {"target": "日本内需株", "impact": +0.04, "reason": "輸入コスト減"},
                {"target": "金・安全資産", "impact": +0.05, "reason": "ドル安で金価格上昇"},
                {"target": "長期債", "impact": +0.03, "reason": "利下げ環境で債券需要"},
            ],
            "currency": {"usd_jpy_change": -20, "impact_on_foreign": -0.131},
            "offset": ["内需企業の輸入コスト低下", "日本国内消費改善"],
            "time_axis": "FRB利下げ決定→数日で急速な円高→数ヶ月で新均衡",
        },
    },
}

# ---------------------------------------------------------------------------
# シナリオ名のエイリアス（自然言語対応）
# ---------------------------------------------------------------------------

SCENARIO_ALIASES = {
    # triple_decline
    "トリプル安": "triple_decline",
    "triple": "triple_decline",
    "株安・円安・債券安": "triple_decline",
    # yen_depreciation
    "ドル高": "yen_depreciation",
    "ドル高円安": "yen_depreciation",
    "円安": "yen_depreciation",
    "yen": "yen_depreciation",
    "為替ショック": "yen_depreciation",
    # us_recession
    "リセッション": "us_recession",
    "recession": "us_recession",
    "景気後退": "us_recession",
    "米国リセッション": "us_recession",
    # boj_rate_hike
    "利上げ": "boj_rate_hike",
    "日銀": "boj_rate_hike",
    "日銀利上げ": "boj_rate_hike",
    "金利上昇": "boj_rate_hike",
    "boj": "boj_rate_hike",
    # us_china_conflict
    "米中": "us_china_conflict",
    "米中対立": "us_china_conflict",
    "china": "us_china_conflict",
    "地政学リスク": "us_china_conflict",
    "貿易戦争": "us_china_conflict",
    # inflation_resurgence
    "インフレ": "inflation_resurgence",
    "インフレ再燃": "inflation_resurgence",
    "inflation": "inflation_resurgence",
    "物価上昇": "inflation_resurgence",
    # tech_crash
    "テック暴落": "tech_crash",
    "tech暴落": "tech_crash",
    "ai暴落": "tech_crash",
    "ナスダック暴落": "tech_crash",
    "tech": "tech_crash",
    "テクノロジー暴落": "tech_crash",
    # yen_appreciation
    "円高ドル安": "yen_appreciation",
    "円高": "yen_appreciation",
    "ドル安": "yen_appreciation",
}

# ---------------------------------------------------------------------------
# セクター・通貨マッピング
# ---------------------------------------------------------------------------

# シナリオのtargetからセクター名への対応表
TARGET_TO_SECTORS = {
    "日本株全般": None,  # 全セクター
    "米国株全般": None,
    "グロース株": ["Technology", "Communication Services"],
    "輸出企業": ["Industrials", "Consumer Cyclical", "Technology"],
    "日本輸出株": ["Industrials", "Consumer Cyclical", "Technology"],
    "内需企業": ["Consumer Defensive", "Utilities", "Real Estate"],
    "日本内需株": ["Consumer Defensive", "Utilities", "Real Estate"],
    "銀行": ["Financial Services"],
    "不動産": ["Real Estate"],
    "高配当株": None,  # セクター横断
    "シクリカル株": ["Consumer Cyclical", "Industrials", "Basic Materials"],
    "ディフェンシブ株": ["Consumer Defensive", "Healthcare", "Utilities"],
    "ASEAN株": None,  # 地域
    "中国関連株": None,  # 地域
    "半導体": ["Technology"],
    "防衛関連": ["Industrials"],
    "エネルギー株": ["Energy"],
    "素材株": ["Basic Materials"],
    "消費関連": ["Consumer Cyclical", "Consumer Defensive"],
    "長期債": None,  # 非株式
    "円建て": None,
    "円建て外貨資産": None,
    "米国株(円建て)": None,
    "全外貨資産": None,
    "テック株": ["Technology", "Communication Services"],
    "非テック株": None,  # テック以外の全セクター（callerで判定）
    "金・安全資産": None,  # 非株式
}

# ティッカーサフィックス → 地域ラベル
SUFFIX_TO_REGION = {
    ".T": "Japan",
    ".SI": "Singapore",
    ".BK": "Thailand",
    ".KL": "Malaysia",
    ".JK": "Indonesia",
    ".PS": "Philippines",
}

# ETF → 資産クラスマッピング（ティッカーベース）
ETF_ASSET_CLASS = {
    # 金・安全資産
    "GLDM": "金・安全資産",
    "GLD": "金・安全資産",
    "IAU": "金・安全資産",
    "SGOL": "金・安全資産",
    # 長期債
    "TLT": "長期債",
    "IEF": "長期債",
    "BND": "長期債",
    "AGG": "長期債",
    "VGLT": "長期債",
    # 株式インカム
    "JEPI": "株式インカム",
    "JEPQ": "株式インカム",
    "SCHD": "株式インカム",
    "VYM": "株式インカム",
    "HDV": "株式インカム",
    "SPYD": "株式インカム",
}
