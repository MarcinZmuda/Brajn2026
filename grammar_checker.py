"""
grammar_checker.py — Auto-fix grammar via LanguageTool REST API
================================================================
v55.1: Converts LanguageTool diagnostic results into actual text fixes.
Reuses the same REST API already used by languagetool_checker.py for diagnostics.

Runs AFTER post-editorial processing (sentence shortening, anaphora) and
BEFORE scoring, so fixes appear in the final article and improve LT score.

Exported:
    auto_fix(text: str) -> dict
"""

import re
import os
import logging

logger = logging.getLogger(__name__)

_LT_API_URL = os.environ.get("LANGUAGETOOL_URL", "https://api.languagetool.org/v2/check")

# Categories safe to auto-apply (grammar, spelling, case agreement)
_SAFE_CATEGORIES = {
    "GRAMMAR", "TYPOS", "CONFUSED_WORDS",
    "AGREEMENT", "CASE", "VERB", "MORPHOLOGY",
    "MISSPELLING", "SPELL",
}

# Rules to SKIP even if category matches
_SKIP_RULES = {
    "WHITESPACE_RULE",
    "COMMA_PARENTHESIS_WHITESPACE",
    "UPPERCASE_SENTENCE_START",
    "PUNCTUATION_PARAGRAPH_END",
    "PL_WORD_REPEAT",
}

# AI-filler phrases to strip
_BANNED_PHRASES = [
    "warto zauważyć, że",
    "warto wiedzieć, że",
    "warto wspomnieć, że",
    "warto podkreślić, że",
    "należy podkreślić, że",
    "należy zaznaczyć, że",
    "co istotne,",
    "co ważne,",
    "co kluczowe,",
    "nie ulega wątpliwości, że",
    "w dzisiejszych czasach",
    "jak wiadomo,",
    "nie jest tajemnicą, że",
]


def _lt_check(text: str) -> list:
    """Call LanguageTool REST API. Returns list of match dicts."""
    try:
        import requests
        resp = requests.post(
            _LT_API_URL,
            data={
                "text": text[:8000],
                "language": "pl-PL",
                "disabledCategories": "TYPOGRAPHY",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("matches", [])
        logger.warning(f"[GRAMMAR] LT API {resp.status_code}")
        return []
    except Exception as e:
        logger.warning(f"[GRAMMAR] LT API error: {e}")
        return []


def _is_safe(match: dict) -> bool:
    """Check if a match is safe to auto-apply."""
    rule = match.get("rule", {})
    rule_id = rule.get("id", "")
    cat_id = rule.get("category", {}).get("id", "")

    if rule_id in _SKIP_RULES:
        return False
    if not match.get("replacements"):
        return False

    for cat in _SAFE_CATEGORIES:
        if cat in cat_id.upper() or cat in rule_id.upper():
            return True
    return False


def _apply_fixes(text: str, matches: list) -> tuple:
    """Apply safe fixes backwards to preserve offsets. Returns (text, count, details)."""
    safe = sorted(
        [m for m in matches if _is_safe(m)],
        key=lambda m: m.get("offset", 0),
        reverse=True,
    )

    fixes = []
    result = text
    for m in safe:
        offset = m.get("offset", 0)
        length = m.get("length", 0)
        replacements = m.get("replacements", [])
        if not replacements or offset < 0 or length <= 0:
            continue
        new_val = replacements[0].get("value", "") if isinstance(replacements[0], dict) else str(replacements[0])
        if not new_val:
            continue
        original = result[offset:offset + length]
        if original == new_val:
            continue
        result = result[:offset] + new_val + result[offset + length:]
        fixes.append({"from": original, "to": new_val, "rule": m.get("rule", {}).get("id", "")})

    return result, len(fixes), fixes


def _remove_banned(text: str) -> tuple:
    """Remove AI-filler phrases. Returns (text, removed_list)."""
    removed = []
    cleaned = text
    for phrase in _BANNED_PHRASES:
        pat = re.compile(re.escape(phrase), re.IGNORECASE)
        if pat.search(cleaned):
            cleaned = pat.sub("", cleaned)
            removed.append(phrase)
    cleaned = re.sub(r"  +", " ", cleaned)
    cleaned = re.sub(r"\.\s+([a-ząćęłńóśźż])", lambda m: ". " + m.group(1).upper(), cleaned)
    return cleaned, removed


def auto_fix(text: str) -> dict:
    """
    Auto-fix grammar + remove AI phrases.

    Returns:
        {
            "corrected": str,
            "grammar_fixes": int,
            "grammar_details": list,
            "phrases_removed": list,
        }
    """
    if not text or len(text.strip()) < 50:
        return {"corrected": text, "grammar_fixes": 0, "grammar_details": [], "phrases_removed": []}

    matches = _lt_check(text)
    corrected, fix_count, details = _apply_fixes(text, matches)
    corrected, removed = _remove_banned(corrected)

    if fix_count > 0 or removed:
        logger.info(f"[GRAMMAR] Auto-fix: {fix_count} grammar, {len(removed)} phrases removed")

    return {
        "corrected": corrected,
        "grammar_fixes": fix_count,
        "grammar_details": details[:20],
        "phrases_removed": removed,
    }
