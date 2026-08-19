"""Note manager -- dual-write to JSON files and Neo4j (KIK-397, KIK-429).

Notes are investment memos (thesis, observation, concern, review, target)
attached to specific stocks or to categories (portfolio, market, general).
The JSON file is the master; Neo4j is a view.
"""

import json
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Optional


_NOTES_DIR = "data/notes"
# order-check は PO9（発注後の注文突合・KIK-752）が要求する記録。
# ここに無いと save_note が弾き、check_order_verification が
# 永久に FAIL のままになる（要求する成果物を作れないチェックになる）。
_VALID_TYPES = {"thesis", "observation", "concern", "review", "target",
                "lesson", "journal", "exit-rule", "order-check"}
_VALID_CATEGORIES = {"stock", "portfolio", "market", "general"}

# 構造化フィールドを受け付けるノート種別（KIK-757）。
#
# ⚠️ trigger / expected_action は **target でも必須**。
#    checklist_review.check_followthrough（FT1）は target ノートのこの2つを
#    日付で洗って「○日に再評価すると書いて実行していない項目」を検出する。
#    2026-08-11 まで lesson 限定で、target では黙って捨てられていたため、
#    FT1 は 43件の target すべてに対して空文字を読み、**一度も発火できなかった**。
#    FT1 自体が「7/28 に 7259.T を 8/3 再評価と書いて実行しなかった」事故の
#    再発防止として作られたものなので、これは検査の不在に等しい。
_FIELD_TYPES = {
    "trigger":            {"lesson", "target", "exit-rule"},
    "expected_action":    {"lesson", "target", "exit-rule"},
    "stop_loss":          {"exit-rule"},
    "take_profit":        {"exit-rule"},
    "key_kpis":           {"thesis"},
    "sell_triggers":      {"thesis", "target"},
    "hold_conditions":    {"thesis", "target"},
    "thesis_status":      {"thesis"},
    "conviction_override": {"thesis"},
    "override_reason":    {"thesis"},
    # KIK-767: 済んだ target を閉じる。どの note_type からでも閉じられる
    # （実行の記録は observation にも lesson にもなるため）
    "resolves":           {"observation", "lesson", "target", "review", "thesis"},
}


def _notes_dir(base_dir: str = _NOTES_DIR) -> Path:
    d = Path(base_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_note(
    symbol: Optional[str] = None,
    note_type: str = "observation",
    content: str = "",
    source: str = "",
    category: Optional[str] = None,
    base_dir: str = _NOTES_DIR,
    trigger: Optional[str] = None,
    expected_action: Optional[str] = None,
    stop_loss: Optional[str] = None,
    take_profit: Optional[str] = None,
    # KIK-715: Thesis management structured fields (all optional)
    key_kpis: Optional[list] = None,
    sell_triggers: Optional[list] = None,
    hold_conditions: Optional[list] = None,
    thesis_status: Optional[str] = None,  # active / attention / review_needed
    conviction_override: Optional[bool] = None,
    override_reason: Optional[str] = None,
    # KIK-767: 済んだ target の id を入れると FT1 がその項目を閉じる
    resolves: Optional[str] = None,
) -> dict:
    """Save a note to JSON file and Neo4j.

    Parameters
    ----------
    symbol : str, optional
        Stock ticker (e.g., "7203.T"). If provided, category is set to "stock".
    note_type : str
        One of: thesis, observation, concern, review, target, lesson.
    content : str
        The note text.
    source : str
        Where this note came from (e.g., "manual", "health-check", "report").
    category : str, optional
        Note category: "stock", "portfolio", "market", "general".
        Auto-set to "stock" when symbol is provided.
        Defaults to "general" when neither symbol nor category is given.
    base_dir : str
        Notes directory.
    trigger : str, optional
        What triggered this lesson (KIK-534). Only stored for type="lesson".
    expected_action : str, optional
        What action should be taken next time (KIK-534). Only stored for type="lesson".

    Returns
    -------
    dict
        The saved note record.
    """
    if note_type not in _VALID_TYPES:
        raise ValueError(f"Invalid note type: {note_type}. Must be one of {_VALID_TYPES}")

    # Resolve category
    if symbol:
        resolved_category = "stock"
    elif category and category in _VALID_CATEGORIES:
        resolved_category = category
    elif note_type == "journal" and not category:
        resolved_category = "general"
    else:
        resolved_category = "general"

    if resolved_category != "stock" and category and category not in _VALID_CATEGORIES:
        raise ValueError(f"Invalid category: {category}. Must be one of {_VALID_CATEGORIES}")

    today = date.today().isoformat()
    now = datetime.now().isoformat(timespec="seconds")

    # Build ID and filename based on symbol or category
    if symbol:
        note_id = f"note_{today}_{symbol}_{uuid.uuid4().hex[:8]}"
        safe_symbol = symbol.replace(".", "_").replace("/", "_")
        filename = f"{today}_{safe_symbol}_{note_type}.json"
    else:
        note_id = f"note_{today}_{resolved_category}_{uuid.uuid4().hex[:8]}"
        filename = f"{today}_{resolved_category}_{note_type}.json"

    note = {
        "id": note_id,
        "date": today,
        "timestamp": now,
        "symbol": symbol or "",
        "category": resolved_category,
        "type": note_type,
        "content": content,
        "source": source,
    }

    # KIK-757: 構造化フィールドを種別で受け付ける。
    # **合わない組み合わせは黙って捨てず ValueError を投げる。**
    # 2026-08-11 まで捨てていたため、渡した側は保存された前提で進んでいた。
    _VALID_THESIS_STATUS = {"active", "attention", "review_needed"}
    given = {
        "trigger": trigger, "expected_action": expected_action,
        "stop_loss": stop_loss, "take_profit": take_profit,
        "key_kpis": key_kpis, "sell_triggers": sell_triggers,
        "hold_conditions": hold_conditions, "thesis_status": thesis_status,
        "conviction_override": conviction_override, "override_reason": override_reason,
        "resolves": resolves,
    }
    rejected = [
        f"{k}（{note_type} では保存されない。"
        f"{'/'.join(sorted(_FIELD_TYPES[k]))} で使う）"
        for k, v in given.items()
        if v is not None and v != "" and note_type not in _FIELD_TYPES[k]
    ]
    if rejected:
        raise ValueError(
            f"note_type='{note_type}' に指定できないフィールド: " + " / ".join(rejected)
        )

    if thesis_status is not None and thesis_status not in _VALID_THESIS_STATUS:
        raise ValueError(
            f"Invalid thesis_status: {thesis_status}. "
            f"Must be one of {_VALID_THESIS_STATUS}"
        )

    for key, value in given.items():
        if value is not None and value != "":
            note[key] = value
        if conviction_override is not None:
            note["conviction_override"] = conviction_override
        if override_reason:
            note["override_reason"] = override_reason

    # KIK-564: Lesson conflict detection (before save)
    lesson_conflicts: list[dict] = []
    if note_type == "lesson":
        try:
            lesson_conflicts = check_lesson_conflicts(note, base_dir=base_dir)
        except Exception:
            pass  # graceful degradation

    # KIK-473: journal type auto-detects symbols from content
    detected_symbols: list[str] = []
    if note_type == "journal" and not symbol and content:
        try:
            from src.data.ticker_utils import extract_all_symbols
            detected_symbols = extract_all_symbols(content)[:3]
        except Exception:
            pass
        if detected_symbols:
            note["detected_symbols"] = detected_symbols

    # 1. Write to JSON file (master)
    d = _notes_dir(base_dir)
    path = d / filename

    # Append to existing file if same date/symbol-or-category/type, else create new
    existing = []
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            existing = data if isinstance(data, list) else [data]
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append(note)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    # 2. Write to Neo4j (view) -- graceful degradation
    try:
        from src.data.graph_store import merge_note
        from src.data.history import _build_embedding
        sem_summary, emb = _build_embedding(
            "note", symbol=symbol or "", note_type=note_type, content=content,
            trigger=note.get("trigger", ""),
            expected_action=note.get("expected_action", ""),
        )
        merge_note(
            note_id=note_id,
            note_date=today,
            note_type=note_type,
            content=content,
            symbol=symbol or None,
            source=source,
            category=resolved_category,
            semantic_summary=sem_summary,
            embedding=emb,
        )
        # KIK-473: Create ABOUT relationships for detected symbols in journal notes
        if detected_symbols:
            from src.data.graph_store import _get_mode, _get_driver
            if _get_mode() != "off":
                driver = _get_driver()
                if driver is not None:
                    with driver.session() as session:
                        for ds in detected_symbols:
                            session.run(
                                "MATCH (n:Note {id: $note_id}) "
                                "MERGE (s:Stock {symbol: $symbol}) "
                                "MERGE (n)-[:ABOUT]->(s)",
                                note_id=note_id, symbol=ds,
                            )
    except Exception:
        pass  # Neo4j unavailable, JSON is the master

    # KIK-434: AI graph linking (graceful degradation)
    try:
        from src.data.graph_store.linker import link_note
        if detected_symbols:
            for ds in detected_symbols:
                link_note(note_id, ds, note_type, content)
        else:
            link_note(note_id, symbol, note_type, content)
    except Exception:
        pass

    # KIK-571: Lesson community classification
    if note_type == "lesson":
        try:
            from src.data.lesson_community import classify_lesson, merge_lesson_community
            community = classify_lesson(content, trigger or "")
            merge_lesson_community(note_id, community)
            note["_lesson_community"] = community
        except Exception:
            pass  # graceful degradation

    # KIK-564: Attach conflicts to return value
    if lesson_conflicts:
        note["_conflicts"] = lesson_conflicts

    return note


def load_notes(
    symbol: Optional[str] = None,
    note_type: Optional[str] = None,
    category: Optional[str] = None,
    base_dir: str = _NOTES_DIR,
) -> list[dict]:
    """Load notes from JSON files.

    Parameters
    ----------
    symbol : str, optional
        Filter by stock symbol.
    note_type : str, optional
        Filter by note type.
    category : str, optional
        Filter by category ("stock", "portfolio", "market", "general").
    base_dir : str
        Notes directory.

    Returns
    -------
    list[dict]
        Notes sorted by date descending.
    """
    d = Path(base_dir)
    if not d.exists():
        return []

    all_notes = []
    for fp in d.glob("*.json"):
        try:
            with open(fp, encoding="utf-8") as f:
                data = json.load(f)
            notes = data if isinstance(data, list) else [data]
            all_notes.extend(notes)
        except (json.JSONDecodeError, OSError):
            continue

    # Filter
    if symbol:
        all_notes = [n for n in all_notes if n.get("symbol") == symbol]
    if note_type:
        all_notes = [n for n in all_notes if n.get("type") == note_type]
    if category:
        all_notes = [n for n in all_notes if n.get("category") == category]

    # Sort by date descending
    all_notes.sort(key=lambda n: n.get("date", ""), reverse=True)
    return all_notes


# ---------------------------------------------------------------------------
# Lesson conflict detection (KIK-564)
# ---------------------------------------------------------------------------

def check_lesson_conflicts(
    new_lesson: dict,
    base_dir: str = _NOTES_DIR,
    similarity_threshold: float = 0.5,
) -> list[dict]:
    """Check if a new lesson conflicts with existing lessons (KIK-564/570).

    Delegates to lesson_conflict.find_conflicts() for unified detection.
    """
    existing = load_notes(note_type="lesson", base_dir=base_dir)
    if not existing:
        return []
    try:
        from src.data.lesson_conflict import find_conflicts
        return find_conflicts(new_lesson, existing, similarity_threshold)
    except ImportError:
        return []


# Backward-compatible aliases (used by auto_context and tests)
def _keyword_similarity(text_a: str, text_b: str) -> float:
    """CJK-aware keyword similarity (KIK-570 delegates to lesson_conflict)."""
    try:
        from src.data.lesson_conflict import keyword_similarity
        return keyword_similarity(text_a, text_b)
    except ImportError:
        # Fallback: space-split only
        words_a = set(text_a.lower().split())
        words_b = set(text_b.lower().split())
        if not words_a or not words_b:
            return 0.0
        return len(words_a & words_b) / len(words_a | words_b)


def _embedding_similarity(text_a: str, text_b: str) -> Optional[float]:
    """Cosine similarity via TEI (KIK-570 delegates to lesson_conflict)."""
    try:
        from src.data.lesson_conflict import embedding_similarity
        return embedding_similarity(text_a, text_b)
    except ImportError:
        return None


def get_exit_rules(
    symbol: Optional[str] = None,
    base_dir: str = _NOTES_DIR,
) -> list[dict]:
    """Load exit-rule notes, optionally filtered by symbol (KIK-566).

    Returns list of exit-rule notes sorted by date descending.
    Each note has stop_loss and/or take_profit fields.
    """
    return load_notes(note_type="exit-rule", symbol=symbol, base_dir=base_dir)


def _note_key(note: dict) -> str:
    """Sort key for notes: timestamp if present, else date.

    ``load_notes`` sorts by ``date`` only, so notes saved on the same day tie.
    Stop levels are revised intraday (e.g. 2026-08-04 に 8031.T を ¥4,651 →
    ¥4,497 へ改訂), so the tie must be broken by ``timestamp``.
    """
    return f"{note.get('date', '')}T{note.get('timestamp', '')}"


def _closed_positions(trade_dir: str) -> dict[str, str]:
    """売り切った銘柄と、その最終売却日を返す（KIK-764）.

    「売り切った」= 買い株数の合計 - 売り株数の合計 <= 0 かつ売却履歴がある。
    取引履歴が読めなければ **空を返す**。読めないことを「全部手仕舞い済み」と
    誤読すると、保有中の銘柄のストップを消してしまう。安全側は「消さない」。
    """
    try:
        from src.data.monthly_check import load_trades
        trades = load_trades(trade_dir)
    except Exception:
        return {}

    net: dict[str, float] = {}
    last_sell: dict[str, str] = {}
    for t in trades:
        sym, date = t.get("symbol"), t.get("date")
        if not sym or not date:
            continue
        try:
            shares = float(t.get("shares") or 0)
        except (TypeError, ValueError):
            shares = 0.0
        if t.get("action") == "buy":
            net[sym] = net.get(sym, 0.0) + shares
        else:
            net[sym] = net.get(sym, 0.0) - shares
            if date > last_sell.get(sym, ""):
                last_sell[sym] = date
    return {s: d for s, d in last_sell.items() if net.get(s, 0.0) <= 0}


def get_stop_levels(base_dir: str = _NOTES_DIR,
                    trade_dir: str = "data/history/trade") -> dict[str, dict]:
    """Extract the current stop-loss level per symbol from exit-rule notes.

    Returns ``{symbol: {"stop": float|None, "date": str, "raw": str,
    "conviction": bool, "closed": bool, "closed_on": str|None}}``.

    - Only the **latest** exit-rule note per symbol is used.
    - ``stop`` is ``None`` when ``stop_loss`` is free text that cannot be parsed
      as a number (legacy notes such as ``"終値ベース 直近高値-8%ラチェット 現3553"``).
      The entry is still returned so callers can warn instead of silently
      dropping a position from monitoring.
    - Symbols whose latest ``thesis`` note carries ``conviction_override`` are
      returned with ``conviction=True`` and ``stop=None``: an old exit-rule note
      must not resurrect a stop the user has explicitly revoked
      (e.g. 7453.T 良品計画 は 2026-08-03 に無条件保有へ変更済み).
    - **手仕舞い済みの銘柄は ``closed=True`` / ``stop=None`` で返す**（KIK-764）。
      ノートには「ストップを外した」を書く手段が無く（``stop_loss`` が空の
      exit-rule ノートは読み飛ばされるので、新しいノートを足しても古い値が勝つ）、
      売却後もストップが台帳に残り続けていた。2026-08-17 の棚卸しで
      14件中7件が手仕舞い済みだった。

      危険なのは残ること自体ではなく、**買い直したときに古い簿価ベースの
      ストップが現行値として復活する**こと。6758.T ソニーは簿価フロア ¥3,400 の
      ストップが残ったまま WL の再監視対象で、現値は ¥3,780 だった。

      判定は「最終売却日 > exit-rule ノートの日付 かつ 差引株数 <= 0」。
      日付条件があるので、**一部売却したあとにストップを引き直した銘柄は消えない**
      （6701.T は 2026-08-04 に半分売却したが 08-15 に再設定しており対象外）。
      ノートは消さない。履歴は残したまま、監視対象から外す。
    """
    latest_exit: dict[str, dict] = {}
    for note in load_notes(note_type="exit-rule", base_dir=base_dir):
        sym = note.get("symbol")
        if not sym or not note.get("stop_loss"):
            continue
        if sym not in latest_exit or _note_key(note) > _note_key(latest_exit[sym]):
            latest_exit[sym] = note

    # Conviction overrides win when they are newer than the exit-rule note.
    conviction: dict[str, dict] = {}
    for note in load_notes(note_type="thesis", base_dir=base_dir):
        sym = note.get("symbol")
        if not sym or not note.get("conviction_override"):
            continue
        if sym not in conviction or _note_key(note) > _note_key(conviction[sym]):
            conviction[sym] = note

    closed_on = _closed_positions(trade_dir)

    result: dict[str, dict] = {}
    for sym, note in latest_exit.items():
        conv = conviction.get(sym)
        if conv is not None and _note_key(conv) > _note_key(note):
            result[sym] = {
                "stop": None, "date": conv.get("date", ""),
                "raw": "", "conviction": True,
                "closed": False, "closed_on": None,
            }
            continue
        raw = str(note.get("stop_loss", "")).strip()
        try:
            stop = float(raw.replace(",", ""))
        except ValueError:
            stop = None
        note_date = note.get("date", "")
        sold_on = closed_on.get(sym)
        # 売却がノートより**後**のときだけ手仕舞い扱い。逆だと、一部売却の
        # あとにストップを引き直した銘柄まで消える
        is_closed = bool(sold_on and note_date and sold_on > note_date)
        result[sym] = {
            "stop": None if is_closed else stop,
            "date": note_date, "raw": raw, "conviction": False,
            "closed": is_closed, "closed_on": sold_on if is_closed else None,
        }

    # A conviction symbol with no exit-rule note at all is not "monitored",
    # so it is intentionally absent from the result.
    return result


def check_exit_rule(
    symbol: str,
    pnl_pct: float,
    base_dir: str = _NOTES_DIR,
) -> Optional[dict]:
    """Check if a position has hit any exit-rule threshold (KIK-566).

    Parameters
    ----------
    symbol : str
        Ticker symbol.
    pnl_pct : float
        Current P&L percentage (e.g., -15.0 means -15%).

    Returns
    -------
    Optional[dict]
        {type: "stop_loss"|"take_profit", threshold: str, reason: str}
        or None if no threshold hit.
    """
    rules = get_exit_rules(symbol=symbol, base_dir=base_dir)
    if not rules:
        return None

    # Use the most recent rule
    rule = rules[0]
    reason = (rule.get("content") or "")[:100]

    # Check stop_loss
    sl = rule.get("stop_loss", "")
    if sl:
        sl_val = _parse_threshold(sl)
        if sl_val is not None and pnl_pct <= sl_val:
            return {"type": "stop_loss", "threshold": sl, "reason": reason}

    # Check take_profit
    tp = rule.get("take_profit", "")
    if tp:
        tp_val = _parse_threshold(tp)
        if tp_val is not None and pnl_pct >= tp_val:
            return {"type": "take_profit", "threshold": tp, "reason": reason}

    return None


def _parse_threshold(value: str) -> Optional[float]:
    """Parse a threshold string like '-15%' or '+20%' into a float."""
    if not value:
        return None
    s = value.strip().replace("%", "").replace("％", "")
    try:
        return float(s)
    except ValueError:
        return None


_VALID_PERSISTENCE = {"permanent", "situational", "seasonal", "expired"}


def update_lesson_metadata(
    note_id: str,
    *,
    trigger: Optional[str] = None,
    expected_action: Optional[str] = None,
    key_kpis: Optional[list] = None,
    persistence: Optional[str] = None,
    base_dir: str = _NOTES_DIR,
) -> Optional[dict]:
    """Update structured metadata fields on an existing lesson note (KIK-738/KIK-739).

    Modifiable fields:
      - trigger, expected_action, key_kpis (KIK-738)
      - persistence: one of permanent | situational | seasonal | expired (KIK-739)

    Other fields (content, date, symbol, etc.) are preserved as master truth.
    Returns the updated note dict, or None if not found / invalid.

    Pass None for a field to leave it unchanged. Pass an empty string/list to
    explicitly clear it (rarely useful — usually you want to add).
    """
    if persistence is not None and persistence not in _VALID_PERSISTENCE:
        return None

    d = Path(base_dir)
    if not d.exists():
        return None

    updated = None
    for fp in d.glob("*.json"):
        try:
            with open(fp, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        notes = data if isinstance(data, list) else [data]
        modified = False
        for n in notes:
            if not isinstance(n, dict) or n.get("id") != note_id:
                continue
            if n.get("type") != "lesson":
                # Only lesson notes have these structured metadata fields
                return None
            if trigger is not None:
                n["trigger"] = trigger
            if expected_action is not None:
                n["expected_action"] = expected_action
            if key_kpis is not None:
                n["key_kpis"] = list(key_kpis)
            if persistence is not None:
                n["persistence"] = persistence
            updated = n
            modified = True
            break
        if modified:
            payload = notes if isinstance(data, list) else notes[0]
            try:
                with open(fp, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
            except OSError:
                return None
            break

    # Best-effort Neo4j sync (graceful degradation)
    if updated is not None:
        try:
            from src.data.graph_store import _get_mode, _get_driver
            if _get_mode() != "off":
                driver = _get_driver()
                if driver is not None:
                    driver.execute_query(
                        "MATCH (n:Note {id: $nid}) "
                        "SET n.trigger = $trig, n.expected_action = $action, "
                        "n.key_kpis = $kpis, n.persistence = $persistence",
                        nid=note_id,
                        trig=updated.get("trigger") or "",
                        action=updated.get("expected_action") or "",
                        kpis=updated.get("key_kpis") or [],
                        persistence=updated.get("persistence") or "",
                        database_="neo4j",
                    )
        except Exception:
            pass

    return updated


def delete_note(
    note_id: str,
    base_dir: str = _NOTES_DIR,
) -> bool:
    """Delete a note by ID from JSON files.

    Returns True if found and deleted.
    """
    d = Path(base_dir)
    if not d.exists():
        return False

    found = False
    for fp in d.glob("*.json"):
        try:
            with open(fp, encoding="utf-8") as f:
                data = json.load(f)
            notes = data if isinstance(data, list) else [data]
            filtered = [n for n in notes if n.get("id") != note_id]
            if len(filtered) < len(notes):
                if filtered:
                    with open(fp, "w", encoding="utf-8") as f:
                        json.dump(filtered, f, ensure_ascii=False, indent=2)
                else:
                    fp.unlink()
                found = True
                break
        except (json.JSONDecodeError, OSError):
            continue

    # Delete from Neo4j (view) -- graceful degradation
    try:
        from src.data.graph_store import _get_mode, _get_driver
        if _get_mode() != "off":
            driver = _get_driver()
            if driver is not None:
                driver.execute_query(
                    "MATCH (n:Note {id: $nid}) DETACH DELETE n",
                    nid=note_id, database_="neo4j",
                )
    except Exception:
        pass

    return found
