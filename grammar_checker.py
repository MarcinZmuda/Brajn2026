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
    # Ortografia 2026: nie+przymiotnik łącznie (LT trained on pre-2026 norms)
    "PL_NIE_Z_PRZYMIOTNIKIEM",
    "PL_NIE_RAZEM",
    "NIE_Z_IMIE",
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


import time as _lt_time
_lt_call_times = []
_LT_RATE_LIMIT = 18  # v68 M19: stay under 20 req/min public limit

def _lt_check(text: str) -> list:
    """Call LanguageTool REST API. Returns list of match dicts."""
    # v68 M19: Rate limit — public API allows 20 req/min
    now = _lt_time.time()
    _lt_call_times[:] = [t for t in _lt_call_times if now - t < 60]
    if len(_lt_call_times) >= _LT_RATE_LIMIT:
        logger.warning("[GRAMMAR] LT rate limit reached (18/min), skipping")
        return []
    _lt_call_times.append(now)
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
        logger.warning(f"[GRAMMAR] LT API returned {resp.status_code}")
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


def _fix_phantom_placeholders(text: str) -> tuple:
    """Remove phantom-placeholder legal references (v60 — Kat.7).

    GPT sometimes generates "odpowiednich przepisów prawa" or "właściwych
    przepisów" instead of a concrete article reference. This is a YMYL
    violation (phantom-placeholder). Remove the filler phrase.
    """
    count = 0
    fixed = text

    # Patterns: "z odpowiednich przepisów prawa", "odpowiednich przepisów prawa"
    # Also: "właściwych przepisów prawa", "stosownych przepisów"
    _PHANTOM_PATTERNS = [
        (r'\s*z\s+odpowiednich\s+przepisów\s+prawa\s*', ' '),
        (r'\s*odpowiednich\s+przepisów\s+prawa\s*', ' '),
        (r'\s*z\s+właściwych\s+przepisów\s+prawa\s*', ' '),
        (r'\s*właściwych\s+przepisów\s+prawa\s*', ' '),
        (r'\s*z\s+stosownych\s+przepisów\s*', ' '),
        (r'\s*stosownych\s+przepisów\s*', ' '),
        # "w reżimie karnym" → "w trybie karnym" (stilted jargon)
        (r'w\s+reżimie\s+karnym', 'w trybie karnym'),
        (r'reżim(?:ie|u|em)?\s+karny(?:m|ch|ego)?', 'tryb karny'),
        (r'reżim(?:ie|u|em)?\s+wykroczeniowy(?:m|ch|ego)?', 'tryb wykroczeniowy'),
        (r'reżim(?:ie|u|em)?\s+ubezpieczeniowy(?:m|ch|ego)?', 'system ubezpieczeniowy'),
        (r'reżim(?:y|ów|om|ami|ach)?\s+sankcji', 'zasady karania'),
        (r'odmienne\s+reżimy', 'odmienne zasady'),
        (r'reżim(?:ie|u|em|y|ów|om|ami|ach)?\b', 'tryb'),
    ]

    for pattern, replacement in _PHANTOM_PATTERNS:
        new_text = re.sub(pattern, replacement, fixed, flags=re.IGNORECASE)
        if new_text != fixed:
            count += 1
            fixed = new_text

    # Clean up double spaces and orphaned punctuation
    fixed = re.sub(r'  +', ' ', fixed)
    fixed = re.sub(r'\.\s*\.', '.', fixed)

    return fixed, count


# ================================================================
# POLISH DIACRITICS FIXER — common AI errors with ą/ę/ć/ł/ń/ó/ś/ź/ż
# ================================================================

# Common diacritical mistakes made by LLMs in Polish
# Format: (wrong, correct) — case-insensitive matching
_DIACRITICAL_FIXES = [
    # Missing ę in accusative/locative
    (r'\bskóre\b', 'skórę'),
    (r'\bSkóre\b', 'Skórę'),
    (r'\bskore\b', 'skórę'),
    (r'\bceche\b', 'cechę'),
    (r'\bdobe\b', 'dobę'),
    (r'\bprobe\b', 'próbę'),
    (r'\bdroge\b', 'drogę'),
    (r'\bocene\b', 'ocenę'),
    (r'\bprace\b', 'pracę'),
    (r'\bstrone\b', 'stronę'),
    (r'\bkare\b', 'karę'),
    (r'\bochrone\b', 'ochronę'),
    (r'\bbariére\b', 'barierę'),
    (r'\bbariere\b', 'barierę'),
    # Missing ó
    (r'\bskora\b', 'skóra'),
    (r'\bSkora\b', 'Skóra'),
    (r'\bgora\b', 'góra'),
    (r'\bGora\b', 'Góra'),
    (r'\bwlokna\b', 'włókna'),
    # Missing ł
    (r'\bwlasciw', 'właściw'),
    (r'\bpolacz', 'połącz'),
    (r'\bwplyw', 'wpływ'),
    (r'\bWplyw', 'Wpływ'),
]

# Capitalization fixes: compound names where second part should keep its case
_CAPITALIZATION_PATTERNS = [
    # Vitamin names: "Witamina C" not "witamina c" after period, but keep "witamina C" mid-sentence
    (r'(?<=[.!?]\s)witamina\s+([a-eA-E](?:\d+)?)\b', lambda m: 'Witamina ' + m.group(1).upper()),
    # "witamina c" → "witamina C" (the letter should always be uppercase)
    (r'\bwitamina\s+([a-e])(\d*)\b', lambda m: 'witamina ' + m.group(1).upper() + m.group(2)),
    (r'\bWitamina\s+([a-e])(\d*)\b', lambda m: 'Witamina ' + m.group(1).upper() + m.group(2)),
    # Kwas + name: "kwas hialuronowy" is fine, but "Kwas Hialuronowy" mid-sentence is wrong
    # pH should always be "pH" not "PH" or "Ph"
    (r'\b[Pp][Hh]\b', 'pH'),
    # SPF should be uppercase
    (r'\bspf\b', 'SPF'),
    # UV should be uppercase
    (r'\buv[ab]?\b', lambda m: m.group(0).upper()),
]


def _fix_diacritics(text: str) -> tuple:
    """Fix common Polish diacritical errors. Returns (text, fix_count, details)."""
    fixed = text
    details = []

    for pattern, replacement in _DIACRITICAL_FIXES:
        matches = list(re.finditer(pattern, fixed))
        if matches:
            repl = replacement if isinstance(replacement, str) else replacement
            new_text = re.sub(pattern, repl, fixed)
            if new_text != fixed:
                for m in matches:
                    details.append({"from": m.group(0), "to": repl if isinstance(repl, str) else "fixed", "rule": "DIACRITICS"})
                fixed = new_text

    for pattern, replacement in _CAPITALIZATION_PATTERNS:
        new_text = re.sub(pattern, replacement, fixed)
        if new_text != fixed:
            details.append({"from": "(capitalization)", "to": "(fixed)", "rule": "CAPITALIZATION"})
            fixed = new_text

    return fixed, len(details), details


def _fix_keyword_concatenation(text: str) -> tuple:
    """Detect and fix keyword concatenation (v62.1 — conservative).
    
    ONLY catches the specific pattern where two MULTI-WORD keyword phrases
    are glued together creating obvious nonsense, e.g.:
      "jazda po alkoholu pod wpływem alkoholu" 
      "zakaz prowadzenia pojazdów zakaz prowadzenia"
    
    Does NOT touch single repeated words — those are normal in Polish legal text.
    
    v62.0 was too aggressive (7-word window, single words) and destroyed 
    legitimate sentences. This version requires:
      1. A repeated PHRASE (≥2 words), not single word
      2. The phrases must be adjacent or separated by max 2 words
    """
    count = 0
    fixed = text
    
    # Pattern: detect when two multi-word phrases share a key noun
    # and are directly adjacent, creating obvious stuffing
    # e.g. "jazda po alkoholu pod wpływem alkoholu" →
    #       phrase1="jazda po alkoholu" + phrase2="pod wpływem alkoholu" 
    #       share "alkoholu" at boundary
    
    # For now: DISABLED — the risk of false positives in Polish inflected text
    # is too high. The budget scaler + prompt softening should handle density.
    # Re-enable only after testing on 20+ articles with manual review.
    
    return fixed, count


def auto_fix(text: str) -> dict:
    """
    Auto-fix grammar + diacritics + remove AI phrases.

    Returns:
        {
            "corrected": str,
            "grammar_fixes": int,
            "grammar_details": list,
            "phrases_removed": list,
            "diacritical_fixes": int,
        }
    """
    if not text or len(text.strip()) < 50:
        return {"corrected": text, "grammar_fixes": 0, "grammar_details": [], "phrases_removed": [], "diacritical_fixes": 0}

    # Step 1: LanguageTool grammar fixes
    matches = _lt_check(text)
    corrected, fix_count, details = _apply_fixes(text, matches)

    # Step 2: Polish diacritical fixes (catches what LT misses)
    corrected, diac_count, diac_details = _fix_diacritics(corrected)
    if diac_count > 0:
        details.extend(diac_details)
        logger.info(f"[GRAMMAR] Diacritics: {diac_count} fixes ({', '.join(d['from']+'→'+d['to'] for d in diac_details[:5])})")

    # Step 2b: Phantom-placeholder removal (v60 — Kat.7 defense-in-depth)
    corrected, phantom_count = _fix_phantom_placeholders(corrected)
    if phantom_count > 0:
        fix_count += phantom_count
        details.append({"from": "odpowiednich przepisów prawa", "to": "(usunięto phantom-placeholder)", "rule": "PHANTOM_PLACEHOLDER"})
        logger.info(f"[GRAMMAR] Phantom-placeholders removed: {phantom_count}")

    # Step 2c: Keyword concatenation detector (v62 — anti-stuffing)
    # Catches "Jazda po alkoholu pod wpływem alkoholu" where same word
    # repeats within 7-word window (sign of glued keywords)
    corrected, concat_count = _fix_keyword_concatenation(corrected)
    if concat_count > 0:
        fix_count += concat_count
        details.append({"from": "(keyword concat)", "to": "(split or deduped)", "rule": "KEYWORD_CONCAT"})
        logger.info(f"[GRAMMAR] Keyword concatenation fixes: {concat_count}")

    # Step 3: Remove AI-filler phrases
    corrected, removed = _remove_banned(corrected)

    total_fixes = fix_count + diac_count
    if total_fixes > 0 or removed:
        logger.info(f"[GRAMMAR] Auto-fix: {fix_count} grammar, {diac_count} diacritics, {len(removed)} phrases removed")

    return {
        "corrected": corrected,
        "grammar_fixes": fix_count,
        "grammar_details": details[:20],
        "phrases_removed": removed,
        "diacritical_fixes": diac_count,
    }
