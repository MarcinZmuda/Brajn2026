"""
===============================================================================
🇵🇱 POLISH NLP VALIDATOR v1.0 — Walidacja naturalności tekstu polskiego
===============================================================================
Bazuje na danych z:
- Narodowy Korpus Języka Polskiego (NKJP, 1,8 mld segmentów)
- IPI PAN corpus (25 mln wyrazów)
- Badania Moździerza (2020) na 90 000 słów
- IFJ PAN (2023) — interpunkcja w 7 językach
- System Jasnopis (SWPS + PAN)

Mierzy 12 parametrów i zwraca score 0-100.
Uruchamiany w KROK 10 (Export) jako dodatkowa analiza.

Autor: Brajn2026
Data: 2025
===============================================================================
"""

import re
import math
from typing import Dict, List, Tuple, Optional
from collections import Counter


# ================================================================
# 📊 NKJP REFERENCE VALUES
# ================================================================

NKJP_TARGETS = {
    "avg_word_length": {"target": 6.0, "tolerance": 0.5, "unit": "znaków"},
    "avg_sentence_length": {"target": 12.0, "min": 8, "max": 18, "unit": "słów"},
    "diacritics_ratio": {"target": 0.069, "tolerance": 0.015, "unit": "%"},
    "vowel_ratio": {"target": 0.365, "tolerance": 0.025, "unit": "%"},
    "digraph_ratio": {"target": 0.03, "tolerance": 0.01, "unit": "%"},
    "comma_density": {"target": 0.015, "min": 0.01, "max": 0.025, "unit": "%"},
    "fog_pl": {"target": 9.0, "min": 7, "max": 12, "unit": ""},
}

# Polish diacritics
_DIACRITICS = set("ąęćłńóśźżĄĘĆŁŃÓŚŹŻ")

# Polish vowels (including Y)
_VOWELS = set("aeiouyąęóAEIOUYĄĘÓ")

# Polish digraphs
_DIGRAPHS = ["ch", "cz", "dz", "dź", "dż", "rz", "sz"]

# Obligatory comma conjunctions
_COMMA_CONJUNCTIONS = [
    "że", "który", "która", "które", "którego", "której", "którym", "którą",
    "ponieważ", "gdyż", "aby", "żeby", "jednak", "lecz", "ale",
    "chociaż", "choć", "mimo że", "dlatego że", "podczas gdy",
    "zanim", "dopóki", "odkąd", "skoro",
]

# Wrong collocations → correct ones
# NOTE: This is a LIGHTWEIGHT FALLBACK only.
# Primary collocation checking is done by LanguageTool (languagetool_checker.py)
# which uses Morfologik dictionary (3.5M forms) and NKJP-based corpus rules.
# This dict catches the most common AI-generated errors when LT API is unavailable.
_WRONG_COLLOCATIONS = {
    "zrobić decyzję": "podjąć decyzję",
    "mieć sukces": "odnieść sukces",
    "zrobić błąd": "popełnić błąd",
    "mieć konsekwencje": "ponieść konsekwencje",
    "duży poziom": "wysoki poziom",
    "duży ból": "silny ból",
    "duże ryzyko": "wysokie ryzyko",
    "silna kawa": "mocna kawa",
    "duży deszcz": "rzęsisty deszcz",
    "dać propozycję": "wysunąć propozycję",
    "pełnić rolę": "odgrywać rolę",
    "zrobić porozumienie": "osiągnąć porozumienie",
    "mieć nadzieję": "żywić nadzieję",
    "mieć podejrzenia": "nabrać podejrzeń",
    "robić wrażenie": "wywierać wrażenie",
    "dać odpowiedź": "udzielić odpowiedzi",
    "duża szansa": "wielka szansa",
    "wziąść": "wziąć",
    "poszłem": "poszedłem",
    "włanczać": "włączać",
    "wzajemna współpraca": "współpraca",
    "aktualna sytuacja na dziś": "obecna sytuacja",
    "krótkie streszczenie": "streszczenie",
    "cofnąć się do tyłu": "cofnąć się",
    "kontynuować dalej": "kontynuować",
    "spadek w dół": "spadek",
    "podnieść do góry": "podnieść",
}


# ================================================================
# 🔧 HELPER FUNCTIONS
# ================================================================

def _split_sentences(text: str) -> List[str]:
    """Split text into sentences. Polish-aware."""
    # Remove H2/H3 headers
    clean = re.sub(r'^h[23]:\s*.*$', '', text, flags=re.MULTILINE)
    # Split on sentence-ending punctuation
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-ZĄĆĘŁŃÓŚŹŻ])', clean)
    # Filter empties and very short
    return [s.strip() for s in sentences if s.strip() and len(s.strip()) > 10]


def _split_words(text: str) -> List[str]:
    """Extract words from text."""
    clean = re.sub(r'^h[23]:\s*', '', text, flags=re.MULTILINE)
    return re.findall(r'[a-ząćęłńóśźżA-ZĄĆĘŁŃÓŚŹŻ]+', clean)


def _count_syllables_pl(word: str) -> int:
    """Count syllables in Polish word (vowel-based heuristic)."""
    word_lower = word.lower()
    vowels = "aeiouyąęó"
    count = 0
    prev_vowel = False
    for char in word_lower:
        is_vowel = char in vowels
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    return max(1, count)


# ================================================================
# 📐 METRIC FUNCTIONS
# ================================================================

def measure_avg_word_length(words: List[str]) -> float:
    """Average word length in characters. NKJP target: 6.0 ±0.5."""
    if not words:
        return 0
    return sum(len(w) for w in words) / len(words)


def measure_avg_sentence_length(sentences: List[str]) -> float:
    """Average sentence length in words. NKJP target: 10-15."""
    if not sentences:
        return 0
    lengths = [len(re.findall(r'\S+', s)) for s in sentences]
    return sum(lengths) / len(lengths)


def measure_sentence_length_cv(sentences: List[str]) -> float:
    """Coefficient of variation of sentence lengths. Target: 0.35-0.45."""
    if len(sentences) < 3:
        return 0
    lengths = [len(re.findall(r'\S+', s)) for s in sentences]
    avg = sum(lengths) / len(lengths)
    if avg == 0:
        return 0
    variance = sum((l - avg) ** 2 for l in lengths) / len(lengths)
    return math.sqrt(variance) / avg


def measure_diacritics_ratio(text: str) -> float:
    """Ratio of diacritical characters. NKJP target: 6.9% ±1.5%."""
    alpha_chars = [c for c in text if c.isalpha()]
    if not alpha_chars:
        return 0
    diacritics_count = sum(1 for c in alpha_chars if c in _DIACRITICS)
    return diacritics_count / len(alpha_chars)


def measure_vowel_ratio(text: str) -> float:
    """Ratio of vowels in text. NKJP target: 35-38%."""
    alpha_chars = [c for c in text if c.isalpha()]
    if not alpha_chars:
        return 0
    vowel_count = sum(1 for c in alpha_chars if c in _VOWELS)
    return vowel_count / len(alpha_chars)


def measure_digraph_ratio(text: str) -> float:
    """Ratio of Polish digraphs (ch,cz,dz,dź,dż,rz,sz). Target: ~3%."""
    text_lower = text.lower()
    total_chars = len([c for c in text_lower if c.isalpha()])
    if total_chars < 100:
        return 0
    digraph_count = 0
    for dg in _DIGRAPHS:
        digraph_count += text_lower.count(dg) * len(dg)
    return digraph_count / total_chars


def measure_comma_density(text: str) -> float:
    """Comma density. Polish target: >1.47% of characters."""
    if len(text) < 100:
        return 0
    return text.count(",") / len(text)


def check_comma_before_conjunctions(text: str) -> Dict:
    """Check if commas appear before obligatory conjunctions.
    Returns ratio (0-1) and list of violations.
    """
    violations = []
    total_checks = 0
    correct = 0

    text_lower = text.lower()

    for conj in _COMMA_CONJUNCTIONS:
        # Find all occurrences of conjunction
        pattern = re.compile(r'(\S)\s+' + re.escape(conj) + r'\b', re.IGNORECASE)
        for match in pattern.finditer(text_lower):
            char_before = match.group(1)
            total_checks += 1
            if char_before == ',':
                correct += 1
            else:
                # Get context
                start = max(0, match.start() - 30)
                end = min(len(text), match.end() + 20)
                context = text[start:end].replace('\n', ' ')
                violations.append({
                    "conjunction": conj,
                    "context": f"...{context}...",
                    "expected": f", {conj}"
                })

    return {
        "total_checked": total_checks,
        "correct": correct,
        "ratio": correct / max(1, total_checks),
        "violations": violations[:10],  # Limit to 10 examples
    }


def compute_fog_pl(sentences: List[str], words: List[str]) -> float:
    """Compute FOG-PL readability index.
    FOG-PL = 0.4 × (words/sentences + 100 × hard_words/words)
    Hard words in Polish: ≥4 syllables (not 3 like English).
    Target: 8-9 for general audience.
    """
    if not sentences or not words:
        return 0
    avg_sentence_len = len(words) / len(sentences)
    hard_words = sum(1 for w in words if _count_syllables_pl(w) >= 4)
    hard_ratio = hard_words / max(1, len(words))
    return 0.4 * (avg_sentence_len + 100 * hard_ratio)


def check_collocations(text: str) -> List[Dict]:
    """Detect wrong collocations. Returns list of issues found."""
    text_lower = text.lower()
    issues = []
    for wrong, correct in _WRONG_COLLOCATIONS.items():
        count = text_lower.count(wrong.lower())
        if count > 0:
            issues.append({
                "wrong": wrong,
                "correct": correct,
                "count": count,
            })
    return issues


def measure_hapax_ratio(words: List[str]) -> float:
    """Hapax legomena ratio — vocabulary richness.
    NKJP: 40-60% of word types appear only once in large texts.
    Higher = richer vocabulary = more natural.
    """
    if not words:
        return 0
    freq = Counter(w.lower() for w in words)
    hapax = sum(1 for w, c in freq.items() if c == 1)
    return hapax / max(1, len(freq))


def measure_type_token_ratio(words: List[str]) -> float:
    """Type-Token Ratio — vocabulary diversity.
    Higher = more diverse vocabulary.
    """
    if not words:
        return 0
    types = len(set(w.lower() for w in words))
    return types / len(words)


# ================================================================
# 🎯 MAIN VALIDATOR
# ================================================================

def validate_polish_text(text: str, style: str = "publicystyczny") -> Dict:
    """
    Full NLP validation of Polish text against NKJP corpus norms.

    Args:
        text: Article text (with h2:/h3: headers)
        style: "publicystyczny" | "naukowy" | "kolokwialny"

    Returns:
        Dict with score (0-100), metrics, issues, and recommendations.
    """
    if not text or len(text) < 200:
        return {"score": 0, "error": "Text too short for analysis"}

    sentences = _split_sentences(text)
    words = _split_words(text)

    if len(words) < 50:
        return {"score": 0, "error": "Too few words for analysis"}

    # ── Compute all metrics ──
    metrics = {}

    # 1. Word length
    avg_wl = measure_avg_word_length(words)
    metrics["avg_word_length"] = round(avg_wl, 2)

    # 2. Sentence length
    avg_sl = measure_avg_sentence_length(sentences)
    metrics["avg_sentence_length"] = round(avg_sl, 1)

    # 3. Sentence CV (burstiness)
    cv = measure_sentence_length_cv(sentences)
    metrics["sentence_length_cv"] = round(cv, 3)

    # 4. Diacritics
    diac = measure_diacritics_ratio(text)
    metrics["diacritics_ratio"] = round(diac, 4)
    metrics["diacritics_pct"] = round(diac * 100, 2)

    # 5. Vowels
    vowels = measure_vowel_ratio(text)
    metrics["vowel_ratio"] = round(vowels, 4)
    metrics["vowel_pct"] = round(vowels * 100, 2)

    # 6. Digraphs
    digr = measure_digraph_ratio(text)
    metrics["digraph_ratio"] = round(digr, 4)
    metrics["digraph_pct"] = round(digr * 100, 2)

    # 7. Comma density
    comma_d = measure_comma_density(text)
    metrics["comma_density"] = round(comma_d, 4)
    metrics["comma_density_pct"] = round(comma_d * 100, 2)

    # 8. Comma before conjunctions
    comma_check = check_comma_before_conjunctions(text)
    metrics["comma_conjunction_ratio"] = round(comma_check["ratio"], 3)
    metrics["comma_conjunction_violations"] = len(comma_check["violations"])

    # 9. FOG-PL
    fog = compute_fog_pl(sentences, words)
    metrics["fog_pl"] = round(fog, 1)

    # 10. Collocations
    collocation_issues = check_collocations(text)
    metrics["collocation_errors"] = len(collocation_issues)

    # 11. Hapax ratio (vocabulary richness)
    hapax = measure_hapax_ratio(words)
    metrics["hapax_ratio"] = round(hapax, 3)

    # 12. Type-token ratio
    ttr = measure_type_token_ratio(words)
    metrics["type_token_ratio"] = round(ttr, 3)

    # 13. Text stats
    metrics["total_words"] = len(words)
    metrics["total_sentences"] = len(sentences)
    metrics["total_chars"] = len(text)

    # ── SCORING (0-100) ──
    score = 100
    issues = []

    # Word length (max -10)
    wl_diff = abs(avg_wl - 6.0)
    if wl_diff > 1.0:
        score -= 10
        issues.append(f"Średnia długość wyrazu {avg_wl:.1f} (NKJP: 6.0 ±0.5)")
    elif wl_diff > 0.5:
        score -= 5
        issues.append(f"Średnia długość wyrazu {avg_wl:.1f} — lekkie odchylenie od NKJP 6.0")

    # Sentence length (max -10)
    if avg_sl < 6 or avg_sl > 22:
        score -= 10
        issues.append(f"Średnia długość zdania {avg_sl:.0f} słów (cel: 10-15)")
    elif avg_sl < 8 or avg_sl > 18:
        score -= 5
        issues.append(f"Średnia długość zdania {avg_sl:.0f} — na granicy naturalności")

    # Sentence CV / burstiness (max -10)
    if cv < 0.2:
        score -= 10
        issues.append(f"Zbyt monotonne zdania (CV={cv:.2f}, cel: 0.35-0.45)")
    elif cv > 0.6:
        score -= 8
        issues.append(f"Za duża zmienność zdań (CV={cv:.2f}, cel: 0.35-0.45) — efekt Frankenstein")
    elif cv < 0.3 or cv > 0.5:
        score -= 3

    # Diacritics (max -15)
    if diac < 0.05:
        score -= 15
        issues.append(f"Za mało diakrytyków: {diac*100:.1f}% (NKJP: 6.9% ±1.5%)")
    elif diac > 0.09:
        score -= 10
        issues.append(f"Za dużo diakrytyków: {diac*100:.1f}% (NKJP: 6.9% ±1.5%)")
    elif abs(diac - 0.069) > 0.015:
        score -= 5

    # Vowels (max -5)
    if vowels < 0.33 or vowels > 0.40:
        score -= 5
        issues.append(f"Udział samogłosek {vowels*100:.1f}% — poza normą NKJP 35-38%")

    # Comma density (max -10)
    if comma_d < 0.008:
        score -= 10
        issues.append(f"Za mało przecinków ({comma_d*100:.2f}%) — tekst polski wymaga gęstej interpunkcji")
    elif comma_d < 0.01:
        score -= 5
        issues.append(f"Niska gęstość przecinków ({comma_d*100:.2f}%)")

    # Comma before conjunctions (max -15)
    if comma_check["total_checked"] > 0:
        if comma_check["ratio"] < 0.7:
            score -= 15
            issues.append(f"Brak przecinków przed spójnikami: {comma_check['ratio']*100:.0f}% poprawnych ({comma_check['total_checked']} sprawdzonych)")
        elif comma_check["ratio"] < 0.9:
            score -= 8
            issues.append(f"Niekompletne przecinki przed spójnikami: {comma_check['ratio']*100:.0f}% poprawnych")

    # FOG-PL (max -10)
    if style == "publicystyczny":
        if fog > 14:
            score -= 8
            issues.append(f"FOG-PL={fog:.1f} — tekst za trudny dla ogółu (cel: 8-12)")
        elif fog < 5:
            score -= 5
            issues.append(f"FOG-PL={fog:.1f} — tekst zbyt prosty")

    # Collocations (max -10, -3 per error)
    if collocation_issues:
        penalty = min(10, len(collocation_issues) * 3)
        score -= penalty
        for ci in collocation_issues[:3]:
            issues.append(f"Błędna kolokacja: \"{ci['wrong']}\" → \"{ci['correct']}\" ({ci['count']}×)")

    # Hapax ratio — bonus for vocabulary richness
    if hapax < 0.3:
        score -= 5
        issues.append(f"Niskie bogactwo słownikowe (hapax={hapax:.1%}) — zbyt powtarzalny tekst")

    score = max(0, min(100, score))

    # ── Recommendations ──
    recommendations = []
    if diac < 0.05:
        recommendations.append("Diakrytyki za niskie - sprawdz czy tekst uzywa polskich znakow (a nie ASCII)")
    if comma_check["ratio"] < 0.9 and comma_check["violations"]:
        top_conjs = set(v["conjunction"] for v in comma_check["violations"][:5])
        recommendations.append(f"Dodaj przecinki przed: {', '.join(top_conjs)}")
    if cv < 0.25:
        recommendations.append("Wprowadź większą wariację długości zdań — mieszaj krótkie (5-8 słów) z długimi (18-25)")
    if collocation_issues:
        recommendations.append("Popraw kolokacje — patrz lista issues")
    if avg_wl > 7.0:
        recommendations.append("Za dużo długich słów — zastąp nominalizacje czasownikami")
    if fog > 14:
        recommendations.append("Uprość tekst: krótsze zdania, mniej słów 4+ sylabowych")

    return {
        "score": score,
        "metrics": metrics,
        "issues": issues,
        "recommendations": recommendations,
        "collocation_issues": collocation_issues,
        "comma_violations": comma_check["violations"],
        "nkjp_reference": {
            "avg_word_length": "6.0 znaków (publicystyka)",
            "avg_sentence_length": "10-15 słów",
            "diacritics": "6.9% ±1.5%",
            "vowels": "35-38%",
            "fog_pl_general": "8-9",
            "comma_before_conjunctions": "100%",
        }
    }


# ================================================================
# 📊 QUICK SUMMARY (for pipeline integration)
# ================================================================

def get_polish_nlp_summary(text: str) -> Dict:
    """Compact summary for dashboard/export. Returns score + key issues."""
    result = validate_polish_text(text)
    return {
        "polish_nlp_score": result["score"],
        "avg_word_length": result["metrics"].get("avg_word_length", 0),
        "avg_sentence_length": result["metrics"].get("avg_sentence_length", 0),
        "diacritics_pct": result["metrics"].get("diacritics_pct", 0),
        "fog_pl": result["metrics"].get("fog_pl", 0),
        "comma_ratio": result["metrics"].get("comma_conjunction_ratio", 0),
        "collocation_errors": result["metrics"].get("collocation_errors", 0),
        "sentence_cv": result["metrics"].get("sentence_length_cv", 0),
        "issues_count": len(result["issues"]),
        "top_issues": result["issues"][:5],
    }
