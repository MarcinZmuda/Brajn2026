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
    """Detect and fix keyword concatenation (v62).
    
    Catches patterns where two keyword-like phrases are glued together,
    creating nonsense like "Jazda po alkoholu pod wpływem alkoholu".
    
    Detection: find content words (≥4 chars) that repeat within 7-word window.
    Fix: remove the second occurrence of the repeated phrase fragment.
    """
    count = 0
    fixed = text
    
    # Split into sentences for local analysis
    sentences = re.split(r'(?<=[.!?])\s+', fixed)
    new_sentences = []
    
    _STOP_WORDS = {
        'jest', 'nie', 'się', 'jak', 'ale', 'lub', 'oraz', 'czy', 'pod', 'nad',
        'przy', 'przez', 'dla', 'bez', 'który', 'która', 'które', 'tego', 'tym',
        'ten', 'tak', 'już', 'być', 'może', 'tylko', 'będzie', 'bardzo', 'więc',
        'jednak', 'nawet', 'także', 'również', 'gdzie', 'kiedy', 'jeśli', 'jako',
        'jego', 'jej', 'ich', 'mieć', 'jeszcze', 'wszystko', 'więcej',
    }
    
    for sent in sentences:
        words = sent.split()
        if len(words) < 6:
            new_sentences.append(sent)
            continue
        
        # Find content words (≥4 chars, not stop words, not numbers)
        content_positions = {}
        for i, w in enumerate(words):
            clean = re.sub(r'[^\wąęćłńóśźżĄĘĆŁŃÓŚŹŻ]', '', w.lower())
            if len(clean) >= 4 and clean not in _STOP_WORDS and not clean.isdigit():
                if clean in content_positions:
                    prev_pos = content_positions[clean]
                    gap = i - prev_pos
                    # Same content word within 7 words = probable concatenation
                    if gap <= 7:
                        # Remove the repeated word and surrounding context
                        # Find the shorter fragment (between occurrences) to remove
                        fragment = ' '.join(words[prev_pos+1:i+1])
                        if len(fragment.split()) <= 5:
                            # Remove fragment, keep first occurrence
                            new_words = words[:prev_pos+1] + words[i+1:]
                            sent = ' '.join(new_words)
                            words = sent.split()  # re-split after edit
                            count += 1
                            logger.info(f"[CONCAT_FIX] Removed repeated '{clean}' fragment: '{fragment}'")
                            break  # one fix per sentence to avoid cascading
                content_positions[clean] = i
        
        new_sentences.append(sent)
    
    if count > 0:
        fixed = ' '.join(new_sentences)
        # Clean up double spaces
        fixed = re.sub(r'  +', ' ', fixed)
    
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
