"""
languagetool_checker.py — LanguageTool integration for BRAJEN SEO
==================================================================
Provides corpus-based grammar, collocation, punctuation and style checking
for Polish text using the LanguageTool library.

Requires: language-tool-python (and Java 8+ runtime on the server)

Exported functions:
    check_text(text: str) -> dict
    get_summary(text: str) -> dict
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ─── LanguageTool initialization ──────────────────────────────────────────────

_lt_tool = None
_LT_LANG = "pl-PL"


def _get_tool():
    """Lazy-initialize LanguageTool. Returns None if unavailable."""
    global _lt_tool
    if _lt_tool is not None:
        return _lt_tool
    try:
        import language_tool_python
        _lt_tool = language_tool_python.LanguageTool(_LT_LANG)
        logger.info("[LT] ✅ LanguageTool initialized for pl-PL")
        return _lt_tool
    except Exception as e:
        logger.warning(f"[LT] ⚠️ LanguageTool unavailable: {e}")
        return None


# ─── Category mapping ─────────────────────────────────────────────────────────

_CATEGORY_MAP = {
    "GRAMMAR":        "GRAMMAR",
    "AGREEMENT":      "GRAMMAR",
    "CASE":           "GRAMMAR",
    "VERB":           "GRAMMAR",
    "MORPHOLOGY":     "GRAMMAR",
    "COLLOCATION":    "COLLOCATIONS",
    "SEMANTICS":      "COLLOCATIONS",
    "CONFUSED_WORDS": "COLLOCATIONS",
    "PUNCTUATION":    "PUNCTUATION",
    "TYPOGRAPHY":     "PUNCTUATION",
    "STYLE":          "STYLE",
    "REDUNDANCY":     "REDUNDANCY",
    "CLICHE":         "STYLE",
    "FORMAL":         "STYLE",
    "TYPOS":          "TYPOS",
    "SPELL":          "TYPOS",
    "MISSPELLING":    "TYPOS",
}

_CATEGORY_LABELS = {
    "GRAMMAR":      "Gramatyka",
    "COLLOCATIONS": "Kolokacje",
    "PUNCTUATION":  "Interpunkcja",
    "STYLE":        "Styl",
    "REDUNDANCY":   "Redundancja",
    "TYPOS":        "Literówki",
    "OTHER":        "Inne",
}

_PENALTY_PER_ISSUE = {
    "GRAMMAR":      4,
    "COLLOCATIONS": 3,
    "PUNCTUATION":  2,
    "STYLE":        1,
    "REDUNDANCY":   1,
    "TYPOS":        2,
    "OTHER":        1,
}


def _map_category(rule_issue_type: str, rule_category_id: str) -> str:
    for key, cat in _CATEGORY_MAP.items():
        if key in rule_category_id.upper() or key in rule_issue_type.upper():
            return cat
    return "OTHER"


def _calculate_score(issues_by_cat: dict, total_words: int) -> int:
    raw_penalty = sum(
        count * _PENALTY_PER_ISSUE.get(cat, 1)
        for cat, count in issues_by_cat.items()
    )
    word_factor = max(1.0, total_words / 500)
    normalized_penalty = raw_penalty / word_factor
    return max(0, 100 - int(normalized_penalty))


# ─── Main public functions ────────────────────────────────────────────────────

def check_text(text: str) -> dict:
    """
    Run LanguageTool on the given Polish text.

    Returns dict with keys:
        api_available (bool), score (int 0-100), total_issues (int),
        categories (dict), issues (list), collocation_issues (list),
        grammar_issues (list), punctuation_issues (list), style_issues (list)
    """
    tool = _get_tool()

    empty = {
        "api_available": False,
        "score": 0,
        "total_issues": 0,
        "categories": {"GRAMMAR": 0, "COLLOCATIONS": 0, "PUNCTUATION": 0,
                       "STYLE": 0, "REDUNDANCY": 0, "TYPOS": 0},
        "issues": [],
        "collocation_issues": [],
        "grammar_issues": [],
        "punctuation_issues": [],
        "style_issues": [],
    }

    if not tool or not text or not text.strip():
        return empty

    try:
        MAX_CHARS = 8000
        text_to_check = text[:MAX_CHARS] if len(text) > MAX_CHARS else text
        matches = tool.check(text_to_check)

        categories = {"GRAMMAR": 0, "COLLOCATIONS": 0, "PUNCTUATION": 0,
                      "STYLE": 0, "REDUNDANCY": 0, "TYPOS": 0}

        all_issues = []
        for m in matches:
            cat_id = getattr(m, "category", "") or ""
            issue_type = getattr(m, "ruleIssueType", "") or ""
            cat = _map_category(issue_type, cat_id)

            if cat in categories:
                categories[cat] += 1

            replacements = list(m.replacements[:4]) if m.replacements else []
            context = re.sub(r"\s+", " ", getattr(m, "context", "") or "").strip()

            all_issues.append({
                "category":      cat,
                "category_name": _CATEGORY_LABELS.get(cat, cat),
                "message":       m.message,
                "context":       context,
                "replacements":  replacements,
                "rule_id":       m.ruleId,
                "offset":        m.offset,
                "length":        m.errorLength,
            })

        _pri = {"GRAMMAR": 0, "COLLOCATIONS": 1, "TYPOS": 2,
                "PUNCTUATION": 3, "STYLE": 4, "REDUNDANCY": 5, "OTHER": 6}
        all_issues.sort(key=lambda x: (_pri.get(x["category"], 6), x["offset"]))

        total_words = len(text_to_check.split())
        score = _calculate_score(categories, total_words)

        return {
            "api_available":    True,
            "score":            score,
            "total_issues":     len(all_issues),
            "categories":       categories,
            "issues":           all_issues[:20],
            "collocation_issues": [i for i in all_issues if i["category"] == "COLLOCATIONS"],
            "grammar_issues":     [i for i in all_issues if i["category"] == "GRAMMAR"],
            "punctuation_issues": [i for i in all_issues if i["category"] == "PUNCTUATION"],
            "style_issues":       [i for i in all_issues if i["category"] in ("STYLE", "REDUNDANCY")],
        }

    except Exception as e:
        logger.error(f"[LT] check_text error: {e}")
        return {**empty, "error": str(e)}


def get_summary(text: str) -> dict:
    """
    One-line summary of LanguageTool results for dashboards and logs.

    Returns dict with keys:
        available (bool), score (int), total_issues (int),
        top_category (str|None), brief (str)
    """
    result = check_text(text)

    if not result.get("api_available"):
        return {"available": False, "score": 0, "total_issues": 0,
                "top_category": None, "brief": "LanguageTool niedostępny"}

    cats = result.get("categories", {})
    top_cat = max(cats, key=lambda k: cats[k]) if cats else None
    top_label = _CATEGORY_LABELS.get(top_cat, top_cat) if top_cat else "—"
    total = result.get("total_issues", 0)
    score = result.get("score", 0)

    brief = (f"Brak błędów ✅ (score {score}/100)" if total == 0
             else f"{total} uw. | głównie: {top_label} | score {score}/100")

    return {
        "available":    True,
        "score":        score,
        "total_issues": total,
        "top_category": top_cat,
        "brief":        brief,
    }
