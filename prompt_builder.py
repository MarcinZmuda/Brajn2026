# prompt_builder.py
# BRAJN Prompt Builder v3.2
# - Short sentence enforcement (max 22 words)
# - Proper HTML table structure
# - Stable API-compatible
# - Works with app.py v45+

from typing import Dict, Any, List, Optional


# ==========================================================
# ===================== SYSTEM PROMPT ======================
# ==========================================================

def build_system_prompt(pre_batch: Dict[str, Any], batch_type: str) -> str:
    pre_batch = pre_batch or {}
    detected_category = pre_batch.get("detected_category", "")
    is_ymyl = detected_category in ("prawo", "medycyna", "finanse")

    parts: List[str] = []

    parts.append("""<role>
Jesteś redaktorem eksperckim.
Piszesz rzeczowo, logicznie i bez marketingowego tonu.
Brzmisz jak praktyk z doświadczeniem.
</role>""")

    parts.append("""<goal>
Artykuł ma:
• odpowiedzieć bezpośrednio na intencję,
• uporządkować wiedzę,
• wyjaśnić mechanizmy i konsekwencje,
• wnosić realną wartość.
SEO jest efektem jakości, nie celem nadrzędnym.
</goal>""")

    if is_ymyl:
        parts.append("""<epistemology>
TEMAT YMYL.

Nie wymyślaj:
• artykułów ustaw,
• sygnatur wyroków,
• progów liczbowych,
• dat,
• danych statystycznych.

Zachowuj ton analityczny.
Unikaj dygresji i ocen wartościujących.
Jeśli nie masz pewności — pomiń szczegół.
</epistemology>""")

    parts.append("""<structure>
• Używaj H2 logicznie.
• Sekcje zaczynaj odpowiedzią.
• Akapit: 2–4 zdania.
• Listy HTML przy 3+ elementach.
• Tabela HTML przy porównaniach.

ZASADY TABEL:
• Zawsze używaj <table>, <thead>, <tbody>.
• Każdy <tr>, <th> i <td> w osobnej linii.
• Nie zapisuj tabeli w jednej linii.
• Nie używaj markdownowych tabel.
</structure>""")

    parts.append("""<style>
• Średnia długość zdania: 12–18 słów.
• Maksymalnie 22 słowa w jednym zdaniu.
• Jedno zdanie = jedna funkcja (definicja / mechanizm / konsekwencja).
• Unikaj zdań z więcej niż 2 przecinkami.
• Jeśli zdanie ma >22 słów — podziel je.
• Mieszaj długość zdań, ale bez konstrukcji łańcuchowych.
</style>""")

    parts.append("""<anti_ai>
Zakazane:
• "warto zauważyć"
• "należy podkreślić"
• "w tym kontekście"
• "podsumowując"
• placeholder typu "odpowiednie przepisy"
</anti_ai>""")

    parts.append("""<format>
Nagłówki: h2: / h3:
Bez markdown.
Bez komentarzy meta.
Zwróć wyłącznie treść.
</format>""")

    return "\n\n".join(parts)


# ==========================================================
# ===================== USER PROMPT ========================
# ==========================================================

def build_user_prompt(
    pre_batch: Dict[str, Any],
    h2: Optional[str],
    batch_type: str,
    article_memory: Optional[str] = None
) -> str:

    keyword = pre_batch.get("main_keyword", "")
    h2_sections = pre_batch.get("h2_sections", [])
    keyphrases = pre_batch.get("keyphrases", [])
    entities = pre_batch.get("entities", [])

    parts: List[str] = []

    parts.append(f"Temat artykułu: {keyword}")

    if h2_sections:
        parts.append("\nStruktura H2:")
        for section in h2_sections:
            parts.append(f"- {section}")

    if keyphrases:
        parts.append("\nFrazy do naturalnego użycia:")
        for kp in keyphrases:
            parts.append(f"- {kp}")

    if entities:
        parts.append("\nEncje do uwzględnienia (jeśli uzasadnione merytorycznie):")
        for e in entities:
            parts.append(f"- {e}")

    parts.append("""
Instrukcje:
1. Zachowaj spójność logiczną.
2. Nie powtarzaj identycznych otwarć.
3. Nie wymuszaj fraz.
4. W YMYL zachowaj styl analityczny.
5. Jeśli temat YMYL — dodaj krótki disclaimer (2–3 zdania).
""")

    parts.append("""
Kontrola długości:
• Jeśli zdanie przekracza 22 słowa — podziel je.
• Nie łącz definicji i konsekwencji w jednym zdaniu.
""")

    parts.append("""
Formatowanie tabel:
• Używaj <table>, <thead>, <tbody>.
• Każdy wiersz w osobnej linii.
""")

    return "\n".join(parts)


# ==========================================================
# ======================= FAQ ==============================
# ==========================================================

def build_faq_system_prompt(pre_batch: Optional[Dict[str, Any]] = None) -> str:
    return """Jesteś ekspertem.
Odpowiadaj krótko i konkretnie.
Maksymalnie 3–4 zdania na odpowiedź.
Unikaj ogólników i marketingu."""


def build_faq_user_prompt(paa_data: List[str], pre_batch: Optional[Dict[str, Any]] = None) -> str:
    parts = ["Odpowiedz na poniższe pytania w formacie h3: + akapit.\n"]
    for q in paa_data:
        parts.append(f"- {q}")
    return "\n".join(parts)


# ==========================================================
# ======================= H2 PLAN ==========================
# ==========================================================

def build_h2_plan_system_prompt() -> str:
    return """Jesteś strategiem SEO.
Zaproponuj logiczny plan H2 odpowiadający intencji użytkownika.
Unikaj duplikatów i zbędnych sekcji."""


def build_h2_plan_user_prompt(
    main_keyword: str,
    mode: str,
    s1_data: Dict[str, Any],
    all_user_phrases: List[str],
    user_h2_hints: Optional[List[str]] = None
) -> str:

    parts = [f"Główne zapytanie: {main_keyword}"]

    if user_h2_hints:
        parts.append("\nSugestie użytkownika:")
        for h in user_h2_hints:
            parts.append(f"- {h}")

    parts.append("\nZaproponuj plan H2.")
    return "\n".join(parts)


# ==========================================================
# ===================== CATEGORY ===========================
# ==========================================================

def build_category_system_prompt(pre_batch: Dict[str, Any]) -> str:
    return """Jesteś redaktorem kategorii produktowej.
Opisuj logicznie i rzeczowo.
Używaj krótkich zdań.
Używaj tabel w poprawnym HTML (<thead>/<tbody>)."""


def build_category_user_prompt(pre_batch: Dict[str, Any]) -> str:
    category = pre_batch.get("main_keyword", "")
    entities = pre_batch.get("entities", [])

    parts = [f"Opis kategorii: {category}"]

    if entities:
        parts.append("\nUwzględnij encje (jeśli pasują):")
        for e in entities:
            parts.append(f"- {e}")

    parts.append("\nZachowaj strukturę i przejrzystość.")
    return "\n".join(parts)


# ==========================================================
# ===================== HELPERS ============================
# ==========================================================

def validate_keyword_soft(text: str, keyword: str) -> bool:
    limit = int(len(text) * 0.25)
    return keyword.lower() in text[:limit].lower()


def add_ymyl_disclaimer(text: str) -> str:
    disclaimer = """
h2: Informacja
Treść ma charakter informacyjny i nie stanowi porady indywidualnej.
W przypadku konkretnej sytuacji należy skonsultować się ze specjalistą.
"""
    return text.strip() + "\n\n" + disclaimer.strip()
