"""
═══════════════════════════════════════════════════════════
BRAJEN PROMPT BUILDER v1.1
═══════════════════════════════════════════════════════════
Converts raw pre_batch data into optimized, readable prompts.

v1.1 changes:
  - _fmt_keywords(): calculates remaining from actual + target_total
    (backend sends these but NOT remaining directly)
  - Shows hard_max_this_batch so Claude knows per-batch limits
  - Clearer MUST/EXTENDED/STOP formatting

Architecture:
  SYSTEM PROMPT = Expert persona + Writing techniques
  USER PROMPT   = Structured instructions from data
═══════════════════════════════════════════════════════════
"""

import json


# ════════════════════════════════════════════════════════════
# SYSTEM PROMPT BUILDER
# ════════════════════════════════════════════════════════════

def build_system_prompt(pre_batch, batch_type):
    """
    Build system prompt = expert persona + writing rules.
    Uses gpt_instructions_v39 (writing techniques from API) as the core,
    with a proper persona wrapper.
    """
    pre_batch = pre_batch or {}
    gpt_instructions = pre_batch.get("gpt_instructions_v39", "")
    gpt_prompt = pre_batch.get("gpt_prompt", "")

    parts = []

    # ── Expert persona ──
    parts.append(
        "Jesteś doświadczonym polskim copywriterem SEO z 10-letnim stażem. "
        "Piszesz naturalnie, merytorycznie i angażująco. "
        "Twój tekst nie brzmi jak AI — brzmi jak ekspert piszący dla ludzi."
    )

    # ── Writing techniques from API (if available) ──
    if gpt_instructions:
        parts.append(gpt_instructions)

    # ── Batch context from API (structure, lengths) ──
    if gpt_prompt:
        parts.append(gpt_prompt)

    # ── Core rules (always) ──
    parts.append("""ZASADY PISANIA:

• PASSAGE-FIRST: Pod każdym H2 i w intro stosuj wzorzec:
  → Zdanie 1: bezpośrednia odpowiedź/definicja (passage-ready dla Google)
  → Zdanie 2: konkret (liczba, data, przykład, dane)
  → Zdanie 3: doprecyzowanie lub wyjątek
  Dopiero potem rozwijaj temat.

• BURSTINESS (cel: CV zdań 0.35–0.45):
  20% zdań krótkich (do 8 słów) — dynamika
  55% zdań średnich (9–18 słów) — rdzeń
  25% zdań długich (19–28 słów) — głębia
  Mieszaj je nieregularnie, nie twórz wzorców.

• SPACING — minimalna odległość między powtórzeniami frazy:
  MAIN: ~60 słów | BASIC: ~80 słów | EXTENDED: ~120 słów
  Nie klasteruj kilku fraz w jednym zdaniu — rozłóż je po całej sekcji.

• FLEKSJA: Odmiany frazy liczą się jako jedno użycie!
  „zespół turnera" = „zespołu turnera" = „zespołem turnera"
  Pisz naturalnie, używaj różnych przypadków gramatycznych.

• KAUZALNOŚĆ: Wyjaśniaj DLACZEGO (przyczyny→skutki), nie tylko CO.
  Wzorce: powoduje, skutkuje, prowadzi do, zapobiega, w wyniku, ponieważ
  ❌ „Temperatura wynosi X°C." → ✅ „Wzrost temperatury powyżej 100°C powoduje wrzenie, co prowadzi do parowania."

• ANTI-AI: Unikaj fraz-klisz: "warto zauważyć", "należy podkreślić", "w dzisiejszych czasach", "kluczowe jest", "nie ulega wątpliwości", "warto podkreślić", "należy pamiętać", "kluczowym aspektem", "w kontekście". Brzmi to sztucznie.

• ANTY-POWTÓRZENIA: NIE powtarzaj tej samej informacji w różnych sekcjach!
  Jeśli zdefiniowałeś pojęcie raz, NIE definiuj go ponownie. Odwołuj się: "wspomniany wcześniej X".

• ANTY-PYTANIA-RETORYCZNE: MAX 1 pytanie retoryczne na sekcję H2.
  ❌ "Jak to wygląda w praktyce?", "Co to oznacza?", "Czy zawsze?" — to szablony AI.
  ✅ Użyj zdań przejściowych (bridge): "To prowadzi do...", "Z tym wiąże się..."

• ANTY-BRAND-STUFFING: NIE powtarzaj nazw firm/marek więcej niż 2x w artykule.
  Jeśli w encjach pojawia się firma (np. TAURON, PGE), wspomnij ją MAX 2 razy.

• ANTY-FILLER: Każde zdanie MUSI dodawać nową informację.
  ❌ „Przewodnik elektryczny przewodzi prąd." — truizm, oczywistość
  ❌ „Opór elektryczny wpływa na natężenie." — banał bez konkretu
  ❌ „To kluczowa różnica technologiczna." — puste podsumowanie
  ✅ „Miedź przewodzi prąd 6× lepiej niż żelazo, dlatego stanowi 60% okablowania domowego."
  Zamiast powtarzać definicję encji jako truizm, opisz DLACZEGO, JAK, ILE, KIEDY.

• ANTY-TRANSITIONS-FILLER: NIE używaj pustych zdań przejściowych:
  ❌ „To prowadzi do kolejnego aspektu."
  ❌ „Z tym wiąże się potrzeba zrozumienia..."
  ❌ „Wynika z tego, że..."
  ❌ „Kolejna część artykułu wyjaśnia..."
  Te zdania marnują miejsce. Zamiast nich — przejdź bezpośrednio do nowego tematu.
  Każde zdanie powinno nieść informację, a nie zapowiadać ją.

• CYTOWANIE ŹRÓDEŁ: NIE cytuj nazw encji jako źródeł informacji.
  ❌ „Wikipedia podaje, że..." (max 1× w całym artykule)
  ❌ „Według [nazwa encji z listy]..." — encje to pojęcia, nie źródła
  ❌ „[cokolwiek] potwierdza / podaje / przywołuje..."
  Podawaj fakty bezpośrednio, bez atrybuowania ich do źródeł.
  Jeśli musisz wspomnieć źródło — zrób to MAX 1 raz na cały artykuł.

• ANTY-HALUCYNACJA: NIE wymyślaj danych, których nie jesteś pewien.
  ❌ Wymyślone statystyki: „Według GUS w 2022 roku doszło do 300 wypadków..."
  ❌ Wymyślone rozporządzenia: „Rozporządzenie Ministra X z dnia Y..."
  ❌ Wymyślone daty/ceny/normy: „od 1 stycznia 2026 stawka wynosi..."
  ✅ Podawaj TYLKO fakty, które znasz z pewną wiedzą.
  ✅ Jeśli chcesz dać przykład — napisz ogólnie: „np. w Polsce napięcie sieciowe wynosi 230 V"
  ✅ Zamiast wymyślonych przepisów — opisz zasadę ogólną bez podawania numerów ustaw.

• POLSZCZYZNA (dane NKJP — Narodowy Korpus Języka Polskiego, 1,8 mld segmentów):
  → PRZECINKI — OBOWIĄZKOWE przed: że, który/a/e, ponieważ, gdyż, aby, żeby, jednak, lecz, ale.
    Brak przecinka przed "że" to NATYCHMIASTOWY sygnał sztuczności.
    W polszczyźnie przecinek występuje CZĘŚCIEJ niż litera "b" (>1,47% znaków).
  → KOLOKACJE — używaj POPRAWNYCH połączeń:
    podjąć decyzję (NIE: zrobić decyzję), odnieść sukces (NIE: mieć sukces),
    popełnić błąd (NIE: zrobić błąd), ponieść konsekwencje (NIE: mieć konsekwencje),
    wysoki poziom (NIE: duży poziom), silny ból (NIE: duży ból),
    wysokie ryzyko (NIE: duże ryzyko), mocna kawa (NIE: silna kawa),
    rzęsisty deszcz (NIE: duży deszcz), wysunąć propozycję (NIE: dać propozycję),
    odgrywać rolę (NIE: pełnić rolę), osiągnąć porozumienie (NIE: zrobić porozumienie).
  → DŁUGOŚĆ ZDAŃ — średnio 10–15 słów (styl publicystyczny).
    NIE pisz wszystkich zdań jednej długości — to sygnał AI.
  → ŚREDNIA DŁUGOŚĆ WYRAZU — 6 znaków (±0,5). Publicystyka=6,0, naukowe=6,4.
    Nie nadużywaj nominalizacji ("przeprowadzanie systematycznego monitorowania").
    Mieszaj krótkie słowa (3-4 znaki) z dłuższymi (8-10).
  → DIAKRYTYKI — naturalny tekst ma ~7% znaków ą,ę,ć,ł,ń,ó,ś,ź,ż.
    Tekst <5% lub >9% diakrytyków = statystycznie nienaturalny.
  → DWUZNAKI — ch, cz, rz, sz, dz, dź, dż stanowią ~3% tekstu.
  → SAMOGŁOSKI — A,I,O,E,U,Y = 35-38% tekstu.
  → Unikaj pleonazmów: "wzajemna współpraca", "aktualna sytuacja na dziś", "krótkie streszczenie".
  → Mieszaj przypadki gramatyczne — nie powtarzaj frazy w mianowniku.

• NATURALNOŚĆ: Pisz jak ekspert tłumaczący temat znajomemu — konkretnie, bez lania wody.

• FORMAT: Używaj wyłącznie formatu h2:/h3: dla nagłówków. Żadnego markdown, HTML ani gwiazdek.""")

    return "\n\n".join(parts)


# ════════════════════════════════════════════════════════════
# USER PROMPT BUILDER
# ════════════════════════════════════════════════════════════

import logging as _logging
_pb_logger = _logging.getLogger("prompt_builder")

# ═══════════════════════════════════════════════════════════
# SCHEMA GUARD — validates critical pre_batch fields
# Ensures backend sent everything needed. Logs warnings for
# missing fields so we catch backend API changes early.
# ═══════════════════════════════════════════════════════════

_CRITICAL_FIELDS = [
    "keywords",             # keyword list — without this, article has no SEO
    "main_keyword",         # primary keyword
    "batch_number",         # batch sequencing
]
_IMPORTANT_FIELDS = [
    "gpt_instructions_v39", # backend writing instructions
    "enhanced",             # enhanced_pre_batch AI data
    "h2_remaining",         # H2 structure
    "article_memory",       # context from previous batches
    "keyword_limits",       # STOP/EXCEEDED rules
    "coverage",             # keyword coverage state
]

def _schema_guard(pre_batch):
    """Validate pre_batch has critical fields. Log warnings for missing."""
    missing_critical = [f for f in _CRITICAL_FIELDS if f not in pre_batch or pre_batch[f] is None]
    missing_important = [f for f in _IMPORTANT_FIELDS if f not in pre_batch or pre_batch[f] is None]

    if missing_critical:
        _pb_logger.warning(
            f"⚠️ SCHEMA GUARD: Missing CRITICAL fields: {missing_critical}. "
            f"Backend may have changed API. Article quality will be degraded."
        )
    if missing_important:
        _pb_logger.info(
            f"ℹ️ Schema guard: Missing optional fields: {missing_important} "
            f"(batch {pre_batch.get('batch_number', '?')})"
        )

    # Validate enhanced sub-fields if enhanced exists
    enhanced = pre_batch.get("enhanced") or {}
    if enhanced:
        expected_enhanced = [
            "smart_instructions_formatted", "causal_context",
            "information_gain", "relations_to_establish"
        ]
        missing_enh = [f for f in expected_enhanced if not enhanced.get(f)]
        if missing_enh:
            _pb_logger.info(f"ℹ️ Enhanced missing: {missing_enh}")


def build_user_prompt(pre_batch, h2, batch_type, article_memory=None):
    """
    Main user prompt builder.
    Converts ALL pre_batch fields into readable, actionable instructions.
    Each section is wrapped in try/except so one bad field won't crash generation.
    """
    pre_batch = pre_batch or {}
    sections = []

    # ── SCHEMA GUARD: validate critical fields from backend ──
    _schema_guard(pre_batch)

    formatters = [
        # ── TIER 1: NON-NEGOTIABLE (backend hard rules) ──
        lambda: _fmt_batch_header(pre_batch, h2, batch_type),
        lambda: _fmt_keywords(pre_batch),           # MUST/STOP/EXCEEDED — hardest constraints
        lambda: _fmt_smart_instructions(pre_batch),  # enhanced_pre_batch AI instructions
        lambda: _fmt_legal_medical(pre_batch),        # YMYL — legal compliance, non-negotiable

        # ── TIER 2: BACKEND WRITE INSTRUCTIONS (gpt_instructions_v39 etc.) ──
        lambda: _fmt_semantic_plan(pre_batch, h2),
        lambda: _fmt_coverage_density(pre_batch),
        lambda: _fmt_phrase_hierarchy(pre_batch),
        lambda: _fmt_continuation(pre_batch),
        lambda: _fmt_article_memory(article_memory),
        lambda: _fmt_h2_remaining(pre_batch),

        # ── TIER 3: CONTENT CONTEXT (enrichment data) ──
        lambda: _fmt_entity_salience(pre_batch),     # entity positioning rules (salience only)
        # _fmt_entities REMOVED v45.4.1 — gpt_instructions_v39 already contains
        # curated "🧠 ENCJE:" section (max 3/batch, importance≥0.7, with HOW hints).
        # Our version duplicated it with dirtier, unfiltered data from S1.
        # _fmt_ngrams REMOVED v45.4.1 — raw statistical n-grams from competitor
        # pages often contain CSS/JS artifacts ("button button", "block embed").
        # Custom GPT never sees these and produces better text without them.
        lambda: _fmt_serp_enrichment(pre_batch),
        lambda: _fmt_causal_context(pre_batch),
        lambda: _fmt_depth_signals(pre_batch),       # depth signals when previous batch scored low
        lambda: _fmt_experience_markers(pre_batch),
        lambda: _fmt_natural_polish(pre_batch),      # v50: fleksja, spacing, anti-stuffing

        # ── TIER 4: SOFT GUIDELINES (format, style, intro) ──
        lambda: _fmt_intro_guidance(pre_batch, batch_type),
        lambda: _fmt_style(pre_batch),
        lambda: _fmt_output_format(h2, batch_type),
    ]

    for fmt in formatters:
        try:
            result = fmt()
            if result:
                sections.append(result)
        except Exception:
            pass

    return "\n\n".join(sections)


# ════════════════════════════════════════════════════════════
# SECTION FORMATTERS
# ════════════════════════════════════════════════════════════

def _fmt_batch_header(pre_batch, h2, batch_type):
    batch_number = pre_batch.get("batch_number", 1)
    total_batches = pre_batch.get("total_planned_batches", 1)
    batch_length = pre_batch.get("batch_length") or {}

    min_w = batch_length.get("min_words", 350)
    max_w = batch_length.get("max_words", 500)

    section_length = pre_batch.get("section_length_guidance") or {}
    length_hint = ""
    if section_length:
        suggested = section_length.get("suggested_words") or section_length.get("target_words")
        if suggested:
            length_hint = f"\nSugerowana długość tej sekcji: ~{suggested} słów."

    h2_instruction = ""
    if batch_type not in ("INTRO", "intro"):
        h2_instruction = f"\nZaczynaj DOKŁADNIE od: h2: {h2}"

    return f"""═══ BATCH {batch_number}/{total_batches} — {batch_type} ═══
Sekcja H2: "{h2}"
Długość: {min_w}-{max_w} słów{length_hint}{h2_instruction}"""


def _fmt_intro_guidance(pre_batch, batch_type):
    if batch_type not in ("INTRO", "intro"):
        return ""
    guidance = pre_batch.get("intro_guidance", "")

    main_kw = pre_batch.get("main_keyword") or {}
    kw_name = main_kw.get("keyword", "") if isinstance(main_kw, dict) else str(main_kw)

    parts = ["═══ WPROWADZENIE (WSTĘP ARTYKUŁU) ═══",
             "To jest PIERWSZY batch — piszesz WSTĘP artykułu.",
             "MUSISZ:",
             f'  1. Wpleć frazę główną ("{kw_name}") w PIERWSZE zdanie' if kw_name else "  1. Frazę główną umieść w pierwszym zdaniu",
             "  2. Zacząć od angażującego haka (hook) — pytanie, statystyka, scenariusz",
             "  3. Przedstawić GŁÓWNĄ TEZĘ artykułu w 1-2 zdaniach",
             "  4. Zapowiedzieć co czytelnik znajdzie dalej (bez listy H2!)",
             "  5. NIE zaczynać od definicji ani od 'W dzisiejszych czasach...'",
             "  6. NIE dodawać nagłówka h2: — wstęp nie ma nagłówka",
             "  7. Utrzymać zwięzłość — wstęp to 80-150 słów"]

    if guidance:
        if isinstance(guidance, dict):
            hook = guidance.get("hook", "")
            angle = guidance.get("angle", "")
            if hook:
                parts.append(f"\nHak otwierający: {hook}")
            if angle:
                parts.append(f"Kąt artykułu: {angle}")
        else:
            parts.append(f"\n{guidance}")

    return "\n".join(parts)


def _fmt_smart_instructions(pre_batch):
    """Smart instructions from enhanced_pre_batch — THE most valuable field."""
    enhanced = pre_batch.get("enhanced") or {}
    smart = enhanced.get("smart_instructions_formatted", "")
    if smart:
        return f"═══ INSTRUKCJE DLA TEGO BATCHA ═══\n{smart[:1000]}"
    return ""


def _parse_target_max(target_total_str):
    """
    Parse target_max from backend's target_total field.
    Backend sends target_total as "min-max" string (e.g., "2-6").
    Returns max value as int, or 0 if unparseable.
    """
    if not target_total_str:
        return 0
    if isinstance(target_total_str, (int, float)):
        return int(target_total_str)
    try:
        parts = str(target_total_str).replace("x", "").split("-")
        if len(parts) >= 2:
            return int(parts[-1].strip())
        return int(parts[0].strip())
    except (ValueError, IndexError):
        return 0


def _fmt_keywords(pre_batch):
    """
    Format keywords section with CALCULATED remaining_max.
    
    v1.1: Backend sends actual (current uses) and target_total ("min-max")
    but NOT remaining. We calculate: remaining = target_max - actual.
    Also shows hard_max_this_batch so Claude knows per-batch limits.
    """
    keywords_info = pre_batch.get("keywords") or {}
    keyword_limits = pre_batch.get("keyword_limits") or {}
    soft_caps = pre_batch.get("soft_cap_recommendations") or {}

    # ── MUST USE (with calculated remaining) ──
    must_raw = keywords_info.get("basic_must_use", [])
    must_lines = []
    for kw in must_raw:
        if isinstance(kw, dict):
            name = kw.get("keyword", "")
            
            # Calculate remaining from actual + target_total
            actual = kw.get("actual", kw.get("actual_uses", kw.get("current_count", 0)))
            target_total = kw.get("target_total", "")
            target_max = _parse_target_max(target_total) or kw.get("target_max", 0)
            hard_max = kw.get("hard_max_this_batch", "")
            use_range = kw.get("use_this_batch", "")
            
            # Explicit remaining from backend (if sent), otherwise calculate
            remaining = kw.get("remaining", kw.get("remaining_max", ""))
            if not remaining and target_max and isinstance(actual, (int, float)):
                remaining = max(0, target_max - int(actual))
            
            # Build descriptive line
            parts_line = [f'"{name}"']
            if remaining:
                parts_line.append(f"zostało {remaining}× ogółem")
            if hard_max:
                parts_line.append(f"max {hard_max}× w tym batchu")
            elif use_range:
                parts_line.append(f"cel: {use_range}× w tym batchu")
            
            must_lines.append(f'  • {" — ".join(parts_line)}')
        else:
            must_lines.append(f'  • "{kw}"')

    # ── EXTENDED (with remaining) ──
    ext_raw = keywords_info.get("extended_this_batch", [])
    ext_lines = []
    for kw in ext_raw:
        if isinstance(kw, dict):
            name = kw.get("keyword", "")
            actual = kw.get("actual", kw.get("actual_uses", 0))
            target_total = kw.get("target_total", "")
            target_max = _parse_target_max(target_total) or kw.get("target_max", 0)
            remaining = kw.get("remaining", kw.get("remaining_max", ""))
            if not remaining and target_max and isinstance(actual, (int, float)):
                remaining = max(0, target_max - int(actual))
            
            line = f'  • "{name}"'
            if remaining:
                line += f" — zostało {remaining}×"
            ext_lines.append(line)
        else:
            ext_lines.append(f'  • "{kw}"')

    # ── STOP ──
    stop_raw = keyword_limits.get("stop_keywords") or []
    stop_lines = []
    for s in stop_raw:
        if isinstance(s, dict):
            name = s.get("keyword", "")
            current = s.get("current_count", s.get("current", s.get("actual", "?")))
            max_c = s.get("max_count", s.get("max", s.get("target_max", "?")))
            stop_lines.append(f'  • "{name}" (już {current}×, limit {max_c}) — STOP!')
        else:
            stop_lines.append(f'  • "{s}"')

    # ── CAUTION ──
    caution_raw = keyword_limits.get("caution_keywords") or []
    caution_lines = []
    for c in caution_raw:
        if isinstance(c, dict):
            name = c.get("keyword", "")
            current = c.get("current_count", c.get("current", c.get("actual", "")))
            max_c = c.get("max_count", c.get("max", c.get("target_max", "")))
            line = f'  • "{name}"'
            if current and max_c:
                line += f" ({current}/{max_c})"
            line += " — max 1× w tym batchu"
            caution_lines.append(line)
        else:
            caution_lines.append(f'  • "{c}" — max 1×')

    # ── SOFT CAPS ──
    soft_notes = []
    if soft_caps:
        for kw_name, info in soft_caps.items():
            if isinstance(info, dict):
                action = info.get("action", "")
                if action and action != "OK":
                    soft_notes.append(f'  ℹ️ "{kw_name}": {action}')

    # ── Build section ──
    parts = ["═══ FRAZY KLUCZOWE ═══"]

    if must_lines:
        parts.append("🔴 OBOWIĄZKOWE (wpleć naturalnie w tekst):")
        parts.extend(must_lines)

    if ext_lines:
        parts.append("\n🟡 ROZSZERZONE (użyj jeśli pasują do kontekstu):")
        parts.extend(ext_lines)

    if stop_lines:
        parts.append("\n🛑 STOP — NIE UŻYWAJ (przekroczone limity!):")
        parts.extend(stop_lines)

    if caution_lines:
        parts.append("\n⚠️ OSTROŻNIE — użyj max 1× lub pomiń:")
        parts.extend(caution_lines)

    if soft_notes:
        parts.append("")
        parts.extend(soft_notes)

    return "\n".join(parts) if len(parts) > 1 else ""


def _fmt_semantic_plan(pre_batch, h2):
    plan = pre_batch.get("semantic_batch_plan") or {}
    if not plan:
        return ""

    parts = ["═══ CO PISAĆ W TEJ SEKCJI ═══"]

    h2_coverage = plan.get("h2_coverage") or {}
    for h2_name, info in h2_coverage.items():
        if isinstance(info, dict):
            angle = info.get("semantic_angle", "")
            must = info.get("must_phrases", [])
            if angle:
                parts.append(f'Kąt semantyczny: {angle}')
            if must:
                phrases = ", ".join(f'"{p}"' for p in must[:5])
                parts.append(f'Obowiązkowe frazy w tej sekcji: {phrases}')

    density_targets = plan.get("density_targets") or {}
    overall = density_targets.get("overall")
    if overall:
        parts.append(f'Docelowa gęstość fraz: {overall}%')

    direction = plan.get("content_direction") or plan.get("writing_direction", "")
    if direction:
        parts.append(f'Kierunek treści: {direction}')

    return "\n".join(parts) if len(parts) > 1 else ""


def _fmt_entity_salience(pre_batch):
    """Entity salience instructions — grammatical positioning, hierarchy.
    
    Based on:
    - Patent US10235423B2 (entity metrics)
    - Patent US9251473B2 (salient items in documents)
    - Dunietz & Gillick (2014) entity salience research
    - Google Cloud NLP API salience scoring
    
    v47.0: Also includes backend placement instructions from competitor analysis
    (entity_salience.py in gpt-ngram-api: salience scoring, co-occurrence, placement)
    
    Data sources:
    - pre_batch["_entity_salience_instructions"] — local positioning rules (from entity_salience.py frontend)
    - pre_batch["_backend_placement_instruction"] — backend placement from competitor analysis
    - pre_batch["_concept_instruction"] — topical concepts agent instruction
    - pre_batch["_must_cover_concepts"] — concept entities that must be covered
    """
    parts = []
    
    # 1. Local salience positioning rules
    local_instructions = pre_batch.get("_entity_salience_instructions", "")
    if local_instructions:
        parts.append(local_instructions)
    
    # 2. v47.0: Backend placement instructions (from gpt-ngram-api competitor analysis)
    backend_placement = pre_batch.get("_backend_placement_instruction", "")
    if backend_placement:
        parts.append("═══ ROZMIESZCZENIE ENCJI (z analizy konkurencji) ═══")
        parts.append(backend_placement)
    
    # 3. v47.0: Concept instruction + must-cover concepts
    concept_instr = pre_batch.get("_concept_instruction", "")
    must_concepts = pre_batch.get("_must_cover_concepts", [])
    if concept_instr:
        parts.append(concept_instr)
    elif must_concepts:
        # Build instruction from concept list if no agent instruction provided
        concept_names = [c.get("text", c) if isinstance(c, dict) else str(c) for c in must_concepts[:10]]
        parts.append(
            "═══ POJĘCIA TEMATYCZNE (z analizy konkurencji) ═══\n"
            f"Następujące pojęcia pojawiają się u konkurencji — wpleć naturalnie w tekst:\n"
            f"{', '.join(concept_names)}"
        )
    
    # 4. v50: Co-occurrence pairs — encje które MUSZĄ być blisko siebie
    cooc_pairs = pre_batch.get("_cooccurrence_pairs") or []
    if cooc_pairs:
        cooc_lines = []
        for pair in cooc_pairs[:8]:
            if isinstance(pair, dict):
                e1 = pair.get("entity1", pair.get("source", ""))
                e2 = pair.get("entity2", pair.get("target", ""))
                if e1 and e2:
                    cooc_lines.append(f'  • "{e1}" + "{e2}" — w tym samym akapicie')
            elif isinstance(pair, str) and "+" in pair:
                cooc_lines.append(f"  • {pair} — w tym samym akapicie")
        if cooc_lines:
            parts.append(
                "═══ WSPÓŁWYSTĘPOWANIE ENCJI (co-occurrence) ═══\n"
                "Następujące pary encji często pojawiają się RAZEM u konkurencji.\n"
                "Umieść je W TYM SAMYM AKAPICIE — bliskość buduje kontekst semantyczny:\n"
                + "\n".join(cooc_lines)
            )
    
    # 5. v50: First paragraph entities — encje z pierwszego akapitu top10
    first_para_ents = pre_batch.get("_first_paragraph_entities") or []
    if first_para_ents:
        fp_names = []
        for ent in first_para_ents[:6]:
            name = ent.get("entity", ent.get("text", ent)) if isinstance(ent, dict) else str(ent)
            if name:
                fp_names.append(f'"{name}"')
        if fp_names:
            parts.append(
                "PIERWSZY AKAPIT — encje tematyczne:\n"
                f"Wprowadź w pierwszym akapicie: {', '.join(fp_names)}.\n"
                "⚠️ To POJĘCIA do opisania, NIE źródła do cytowania. Nie pisz '[encja] podaje/potwierdza...'."
            )
    
    # 6. v50: H2 entities — encje tematyczne do rozmieszczenia w H2
    h2_ents = pre_batch.get("_h2_entities") or []
    if h2_ents:
        h2_names = []
        for ent in h2_ents[:8]:
            name = ent.get("entity", ent.get("text", ent)) if isinstance(ent, dict) else str(ent)
            if name:
                h2_names.append(f'"{name}"')
        if h2_names:
            parts.append(
                "ENCJE TEMATYCZNE W H2:\n"
                f"Rozłóż w tekście: {', '.join(h2_names)}.\n"
                "⚠️ To POJĘCIA do opisania, NIE źródła. Nie pisz '[encja] podaje...'."
            )
    
    return "\n\n".join(parts) if parts else ""


# _fmt_entities REMOVED v45.4.1 → v50 cleanup: function deleted.
# gpt_instructions_v39 already contains curated "🧠 ENCJE:" section
# (max 3/batch, importance≥0.7, with HOW hints). Our version duplicated it
# with dirtier, unfiltered data from S1.

# _fmt_ngrams REMOVED v45.4.1 → v50 cleanup: function deleted.
# Raw statistical n-grams from competitor pages often contain CSS/JS artifacts
# ("button button", "block embed"). Custom GPT produces better text without them.


def _fmt_serp_enrichment(pre_batch):
    serp = pre_batch.get("serp_enrichment") or {}
    enhanced = pre_batch.get("enhanced") or {}

    paa = (serp.get("paa_for_batch") or enhanced.get("paa_from_serp") or [])
    lsi = (serp.get("lsi_keywords") or [])

    if not paa and not lsi:
        return ""

    parts = ["═══ WZBOGACENIE Z SERP ═══"]

    if paa:
        parts.append("Pytania które ludzie zadają w Google (PAA) — odpowiedz na 1-2 w tekście:")
        for q in paa[:5]:
            q_text = q.get("question", q) if isinstance(q, dict) else q
            if q_text:
                parts.append(f'  ❓ {q_text}')

    if lsi:
        lsi_names = [l.get("keyword", l) if isinstance(l, dict) else l for l in lsi[:8]]
        parts.append(f'\nFrazy LSI (bliskoznaczne, wpleć naturalnie): {", ".join(lsi_names)}')

    return "\n".join(parts) if len(parts) > 1 else ""


def _fmt_continuation(pre_batch):
    continuation = pre_batch.get("continuation_v39") or {}
    enhanced = pre_batch.get("enhanced") or {}
    cont_ctx = enhanced.get("continuation_context") or {}

    last_h2 = cont_ctx.get("last_h2") or continuation.get("last_h2", "")
    last_ending = cont_ctx.get("last_paragraph_ending") or continuation.get("last_paragraph_ending", "")
    last_topic = cont_ctx.get("last_topic") or continuation.get("last_topic", "")
    transition_hint = continuation.get("transition_hint", "")

    if not last_h2 and not last_ending:
        return ""

    parts = ["═══ KONTYNUACJA ═══",
             "Poprzedni batch zakończył się na:"]

    if last_h2:
        parts.append(f'  Ostatni H2: "{last_h2}"')
    if last_ending:
        ending_preview = last_ending[:150] + ("..." if len(last_ending) > 150 else "")
        parts.append(f'  Ostatnie zdanie: "{ending_preview}"')
    if last_topic:
        parts.append(f'  Temat: {last_topic}')

    parts.append("\nZacznij PŁYNNIE — nawiąż do poprzedniego wątku, ale nie powtarzaj zakończenia.")
    if transition_hint:
        parts.append(f'Sugerowane przejście: {transition_hint}')

    return "\n".join(parts)


def _fmt_article_memory(article_memory):
    if not article_memory:
        return ""

    parts = ["═══ PAMIĘĆ ARTYKUŁU (KRYTYCZNE — nie powtarzaj!) ═══"]

    if isinstance(article_memory, dict):
        topics = article_memory.get("topics_covered") or article_memory.get("covered_topics") or []
        if topics:
            parts.append("Sekcje już napisane:")
            for t in topics[:10]:
                if isinstance(t, str):
                    parts.append(f'  ✓ {t}')
                elif isinstance(t, dict):
                    parts.append(f'  ✓ {t.get("topic", t.get("h2", ""))}')

        facts = article_memory.get("key_facts_used") or article_memory.get("facts", [])
        # v50.5 FIX 30: Also extract key_points and avoid_repetition from AI memory
        key_points = article_memory.get("key_points") or []
        avoid_rep = article_memory.get("avoid_repetition") or []
        
        all_facts = list(facts) + list(key_points)
        if all_facts:
            parts.append("\nFakty/definicje już podane (NIE POWTARZAJ — odwołuj się: 'wspomniany wcześniej'):")
            for f in all_facts[:12]:
                parts.append(f'  • {f}' if isinstance(f, str) else f'  • {json.dumps(f, ensure_ascii=False)[:100]}')

        if avoid_rep:
            parts.append("\n⛔ KONKRETNE TEMATY DO UNIKANIA (AI memory):")
            for r in avoid_rep[:8]:
                parts.append(f'  ❌ {r}')

        phrases_used = article_memory.get("phrases_used") or {}
        if phrases_used:
            high_use = [(k, v) for k, v in phrases_used.items()
                        if isinstance(v, (int, float)) and v >= 3]
            if high_use:
                parts.append("\nFrazy już często użyte (ogranicz):")
                for name, count in high_use[:8]:
                    parts.append(f'  • "{name}" — już {count}×')
        
        # v50.5 FIX 30: Add strong anti-repetition instruction
        if topics and len(topics) >= 2:
            parts.append(
                "\n⚠️ ZASADA ANTY-POWTÓRZEŃ: Jeśli pojęcie (np. prawo Ohma, definicja ampera) "
                "zostało ZDEFINIOWANE w poprzedniej sekcji, NIE definiuj go ponownie. "
                "Zamiast tego: użyj go w nowym kontekście lub odnieś się krótko: "
                "'zgodnie z omówionym wcześniej prawem Ohma'. "
                "Powtórzenie definicji = utrata punktów jakości."
            )
    elif isinstance(article_memory, str):
        parts.append(article_memory[:1500])

    return "\n".join(parts) if len(parts) > 1 else ""


def _fmt_coverage_density(pre_batch):
    coverage = pre_batch.get("coverage") or {}
    density = pre_batch.get("density") or {}
    main_kw = pre_batch.get("main_keyword") or {}
    keyword_tracking = pre_batch.get("keyword_tracking") or {}

    if not coverage and not density and not main_kw:
        return ""

    parts = ["═══ STATUS POKRYCIA FRAZ ═══"]

    if main_kw:
        kw_name = main_kw.get("keyword", "") if isinstance(main_kw, dict) else str(main_kw)
        synonyms = main_kw.get("synonyms", []) if isinstance(main_kw, dict) else []
        if kw_name:
            parts.append(f'Hasło główne: "{kw_name}"')
        if synonyms:
            parts.append(f'Synonimy (używaj zamiennie): {", ".join(synonyms[:5])}')

    current_cov = coverage.get("current", coverage.get("current_coverage"))
    target_cov = coverage.get("target", coverage.get("target_coverage"))
    if current_cov is not None and target_cov is not None:
        parts.append(f'\nPokrycie fraz: {current_cov}% z docelowych {target_cov}%')

    missing = coverage.get("missing_phrases") or coverage.get("uncovered") or []
    if missing:
        parts.append("⚠️ BRAKUJĄCE FRAZY — wpleć w tym batchu:")
        for m in missing[:8]:
            name = m.get("keyword", m) if isinstance(m, dict) else m
            parts.append(f'  → "{name}"')

    if density:
        current_d = density.get("current")
        target_range = density.get("target_range") or []
        if current_d is not None:
            range_str = f'{target_range[0]}-{target_range[1]}%' if len(target_range) >= 2 else "1.5-2.5%"
            status = "✅ w normie" if target_range and len(target_range) >= 2 and target_range[0] <= current_d <= target_range[1] else "⚠️ do korekty"
            parts.append(f'\nGęstość fraz: {current_d}% (cel: {range_str}) {status}')

        overused_d = density.get("overused") or []
        if overused_d:
            over_names = ", ".join(f'"{o}"' if isinstance(o, str) else f'"{o.get("keyword", "")}"' for o in overused_d[:5])
            parts.append(f'Nadużywane: {over_names} — użyj synonimów')

    if keyword_tracking:
        total_kw = keyword_tracking.get("total_keywords", 0)
        covered_kw = keyword_tracking.get("covered", 0)
        if total_kw and covered_kw:
            parts.append(f'\nTracking: {covered_kw}/{total_kw} fraz pokrytych')

    return "\n".join(parts) if len(parts) > 1 else ""


def _fmt_style(pre_batch):
    style = pre_batch.get("style_instructions") or pre_batch.get("style_instructions_v39") or {}

    if not style:
        return ""

    parts = ["═══ STYL ═══"]

    if isinstance(style, dict):
        tone = style.get("tone", "")
        if tone:
            parts.append(f'Ton: {tone}')

        para_len = style.get("paragraph_length", "")
        if para_len:
            parts.append(f'Długość akapitów: {para_len} słów')

        forbidden = style.get("forbidden_phrases") or style.get("avoid_phrases") or []
        if forbidden:
            parts.append(f'ZAKAZANE zwroty: {", ".join(f"{f}" for f in forbidden[:8])}')

        preferred = style.get("preferred_phrases") or style.get("use_phrases") or []
        if preferred:
            parts.append(f'Preferowane zwroty: {", ".join(preferred[:5])}')

        persona = style.get("persona", "")
        if persona:
            parts.append(f'Perspektywa: {persona}')
    elif isinstance(style, str):
        parts.append(style[:500])

    return "\n".join(parts) if len(parts) > 1 else ""


def _fmt_legal_medical(pre_batch):
    legal_ctx = pre_batch.get("legal_context") or {}
    medical_ctx = pre_batch.get("medical_context") or {}
    ymyl_enrich = pre_batch.get("_ymyl_enrichment") or {}
    ymyl_intensity = pre_batch.get("_ymyl_intensity", "full")

    parts = []

    # v50: For "light" YMYL — DON'T inject full legal/medical framework
    if ymyl_intensity == "light":
        light_note = pre_batch.get("_light_ymyl_note", "")
        if light_note:
            parts.append("═══ ASPEKT REGULACYJNY (peryferyjny — NIE główny temat!) ═══")
            parts.append(f"  {light_note}")
            parts.append("  ⚠️ OGRANICZENIE: Wspomnij o regulacjach MAX 1-2 razy w CAŁYM artykule.")
            parts.append("  NIE cytuj artykułów ustaw, NIE dodawaj sygnatur orzeczeń,")
            parts.append("  NIE dodawaj disclaimera o konsultacji z prawnikiem/lekarzem.")
            parts.append("  Artykuł jest EDUKACYJNY/TECHNICZNY, nie prawniczy/medyczny.")
        return "\n".join(parts) if parts else ""

    if legal_ctx and legal_ctx.get("active"):
        parts.append("═══ KONTEKST PRAWNY (YMYL) ═══")
        parts.append("Ten artykuł dotyczy tematyki prawnej. MUSISZ:")
        parts.append("  1. Cytować realne przepisy i orzeczenia (podane niżej)")
        parts.append("  2. Dodać disclaimer o konsultacji z prawnikiem")
        parts.append("  3. NIE wymyślać sygnatur ani dat orzeczeń")
        
        # v47.2: Claude's enrichment — specific articles and concepts
        legal_enrich = ymyl_enrich.get("legal", {})
        if legal_enrich.get("articles"):
            parts.append("")
            parts.append("PODSTAWA PRAWNA (kluczowe przepisy):")
            for art in legal_enrich["articles"][:5]:
                parts.append(f"  • {art}")
        if legal_enrich.get("acts"):
            parts.append(f"  Ustawy: {', '.join(legal_enrich['acts'][:4])}")
        if legal_enrich.get("key_concepts"):
            parts.append(f"  Kluczowe pojęcia: {', '.join(legal_enrich['key_concepts'][:6])}")
        
        parts.append("")
        parts.append("FORMATY CYTOWAŃ PRAWNYCH:")
        parts.append('  • Przepisy: "art. 13 § 1 k.c.", "art. 58 § 2 k.r.o."')
        parts.append('  • Wyroki: "wyrok SN z 12.03.2021, III CZP 45/19"')
        parts.append('  • Dziennik Ustaw: "Dz.U. 2023 poz. 1234"')
        parts.append('  Causal legal: "niedopełnienie obowiązku skutkuje...", "brak zgłoszenia prowadzi do..."')

        instruction = legal_ctx.get("legal_instruction", "")
        if instruction:
            parts.append(f'\n{instruction[:600]}')

        judgments = legal_ctx.get("top_judgments") or []
        if judgments:
            parts.append("\nOrzeczenia do zacytowania:")
            for j in judgments[:3]:
                if isinstance(j, dict):
                    sig = j.get("signature", j.get("caseNumber", ""))
                    court = j.get("court", j.get("courtName", ""))
                    date = j.get("date", j.get("judgmentDate", ""))
                    matched = j.get("matched_article", "")
                    line = f'  • {sig} — {court} ({date})'
                    if matched:
                        line += f' [dot. {matched}]'
                    parts.append(line)

        citation_hint = legal_ctx.get("citation_hint", "")
        if citation_hint:
            parts.append(f'\n{citation_hint}')

    if medical_ctx and medical_ctx.get("active"):
        if parts:
            parts.append("")
        parts.append("═══ KONTEKST MEDYCZNY (YMYL) ═══")
        parts.append("Ten artykuł dotyczy tematyki zdrowotnej. MUSISZ:")
        parts.append("  1. Cytować źródła naukowe (podane niżej)")
        parts.append("  2. NIE wymyślać statystyk ani nazw badań")
        parts.append("  3. Dodać informację o konsultacji z lekarzem")
        
        # v47.2: Claude's enrichment — specialization, evidence guidelines
        med_enrich = ymyl_enrich.get("medical", {})
        if med_enrich.get("specialization"):
            parts.append(f"\n  Specjalizacja: {med_enrich['specialization']}")
        if med_enrich.get("condition"):
            cond = med_enrich["condition"]
            latin = med_enrich.get("condition_latin", "")
            icd = med_enrich.get("icd10", "")
            parts.append(f"  Choroba/stan: {cond}" + (f" ({latin})" if latin else "") + (f" [ICD-10: {icd}]" if icd else ""))
        if med_enrich.get("key_drugs"):
            parts.append(f"  Kluczowe leki: {', '.join(med_enrich['key_drugs'][:5])}")
        if med_enrich.get("evidence_note"):
            parts.append(f"\n  ⚠️ WYTYCZNE: {med_enrich['evidence_note']}")
        
        parts.append("")
        parts.append("FORMATY CYTOWAŃ MEDYCZNYCH:")
        parts.append('  • "Smith i wsp. (2023)", "Kowalski et al. (2024)"')
        parts.append('  • "PMID:12345678", "DOI:10.1000/xyz"')
        parts.append("")
        parts.append("HIERARCHIA DOWODÓW (cytuj najwyższy dostępny):")
        parts.append("  1. Meta-analiza / Przegląd systematyczny (najsilniejszy)")
        parts.append("  2. RCT (badanie randomizowane)")
        parts.append("  3. Badanie kohortowe")
        parts.append("  4. Opis przypadku")
        parts.append("  5. Opinia eksperta (najsłabszy)")
        parts.append('  Causal medical: "nieleczone prowadzi do...", "brak terapii skutkuje..."')

        instruction = medical_ctx.get("medical_instruction", "")
        if instruction:
            parts.append(f'\n{instruction[:600]}')

        publications = medical_ctx.get("top_publications") or []
        if publications:
            parts.append("\nPublikacje do zacytowania:")
            for p in publications[:5]:
                if isinstance(p, dict):
                    title = p.get("title", "")[:80]
                    authors = p.get("authors", "")[:40]
                    year = p.get("year", "")
                    pmid = p.get("pmid", "")
                    parts.append(f'  • {authors} ({year}): "{title}" PMID:{pmid}')

    return "\n".join(parts) if parts else ""


def _fmt_experience_markers(pre_batch):
    enhanced = pre_batch.get("enhanced") or {}
    markers = enhanced.get("experience_markers") or []

    if not markers:
        return ""

    parts = ["═══ SYGNAŁY DOŚWIADCZENIA (E-E-A-T) ═══",
             "Wpleć min 1 sygnał, że autor MA doświadczenie z tematem:"]

    for m in markers[:5]:
        if isinstance(m, str):
            parts.append(f'  • {m}')
        elif isinstance(m, dict):
            parts.append(f'  • {m.get("marker", m.get("text", ""))}')

    return "\n".join(parts)


def _fmt_causal_context(pre_batch):
    enhanced = pre_batch.get("enhanced") or {}
    causal = enhanced.get("causal_context", "")
    info_gain = enhanced.get("information_gain", "")

    parts = []

    if causal:
        parts.append("═══ KONTEKST PRZYCZYNOWO-SKUTKOWY ═══")
        parts.append(f'{causal[:500]}')

    if info_gain:
        if parts:
            parts.append("")
        parts.append("═══ INFORMATION GAIN (przewaga nad konkurencją) ═══")
        parts.append(f'{info_gain[:500]}')

    return "\n".join(parts) if parts else ""


def _fmt_depth_signals(pre_batch):
    """Depth signals — inject when previous batch scored low on depth
    or always for FULL YMYL content.
    
    v50: Only force for full YMYL intensity, not light.
    Based on 10 depth signals from GPT prompt with weights.
    """
    last_depth = pre_batch.get("_last_depth_score")
    is_ymyl = pre_batch.get("_is_ymyl", False)
    ymyl_intensity = pre_batch.get("_ymyl_intensity", "none")
    is_full_ymyl = is_ymyl and ymyl_intensity == "full"
    
    # Only force depth for FULL YMYL, not light
    threshold = 40 if is_full_ymyl else 30
    if last_depth is not None and last_depth >= threshold and not is_full_ymyl:
        return ""
    
    # If no depth data at all and not full YMYL, skip
    if last_depth is None and not is_full_ymyl:
        return ""
    
    parts = ["═══ SYGNAŁY GŁĘBOKOŚCI (dodaj od najwyższej wagi) ═══"]
    
    if last_depth is not None:
        parts.append(f"⚠️ Ostatni batch: depth {last_depth}/100 (próg: {threshold}). Dodaj więcej konkretów!")
    
    parts.append("")
    # v50: Legal references only for FULL YMYL
    if is_full_ymyl:
        parts.append("WAGA 2.5: referencje prawne (art. k.c., wyroki SN, Dz.U.) + naukowe (PMID, DOI, badania)")
    parts.append('WAGA 2.0: konkretne liczby (kwoty PLN, %, okresy — NIE "około")')
    parts.append('WAGA 1.8: nazwane instytucje (konkretny sąd/urząd, NIE "właściwy sąd") + praktyczne porady (w praktyce, częsty błąd)')
    parts.append("WAGA 1.5: wyjaśnienia przyczynowe (ponieważ, w wyniku) + wyjątki (z wyjątkiem, chyba że) + konkretne daty")
    parts.append("WAGA 1.2: porównania (w odróżnieniu od) | WAGA 1.0: kroki procedur (najpierw/następnie)")
    
    return "\n".join(parts)


def _fmt_natural_polish(pre_batch):
    """v50: Natural Polish writing instructions — fleksja, spacing, anti-stuffing.

    Based on natural_polish_instructions.py (master-seo-api-main).
    Inlined here because prompt_builder runs in Brajn, not master.
    
    Prevents keyword stuffing by teaching Claude that:
    1. Polish inflected forms count as the same keyword
    2. Minimum spacing between repetitions is required
    3. Max 2 uses of same phrase per paragraph
    """
    # Get keywords from pre_batch
    keywords_info = pre_batch.get("keywords") or {}
    must_kw = keywords_info.get("basic_must_use") or []
    ext_kw = keywords_info.get("extended_this_batch") or []

    all_kw = []
    for kw in must_kw + ext_kw:
        if isinstance(kw, dict):
            name = kw.get("keyword", "")
            kw_type = kw.get("type", "BASIC").upper()
        elif isinstance(kw, str):
            name = kw
            kw_type = "BASIC"
        else:
            continue
        if name:
            all_kw.append((name, kw_type))

    if not all_kw:
        return ""

    # Spacing rules
    SPACING = {"MAIN": 60, "BASIC": 80, "EXTENDED": 120}

    parts = ["═══ NATURALNY POLSKI — ANTY-STUFFING ═══"]

    parts.append(
        "🔄 FLEKSJA: Odmiany frazy liczą się jako jedno użycie!\n"
        '   "zespół turnera" = "zespołu turnera" = "zespołem turnera"\n'
        "   Pisz naturalnie, używaj różnych przypadków gramatycznych.\n"
        "   NIE MUSISZ powtarzać frazy w mianowniku — system zaliczy każdą odmianę."
    )

    spacing_lines = []
    for name, kw_type in all_kw[:8]:
        spacing = SPACING.get(kw_type, 80)
        spacing_lines.append(f'  • "{name}" ({kw_type}) — min {spacing} słów między powtórzeniami')
    if spacing_lines:
        parts.append("📏 ODSTĘPY MIĘDZY POWTÓRZENIAMI:\n" + "\n".join(spacing_lines))

    parts.append(
        "⚠️ ZASADY:\n"
        "  • Max 2× ta sama fraza w jednym akapicie\n"
        "  • Rozkładaj frazy RÓWNOMIERNIE w tekście (nie grupuj na początku/końcu)\n"
        "  • Zamiast powtórzenia użyj: synonimu, zaimka, opisu ('ta choroba', 'omawiany zespół')\n"
        "  • Podmiot → dopełnienie → synonim → kolejny akapit → ponownie fraza"
    )

    return "\n".join(parts)


def _fmt_phrase_hierarchy(pre_batch):
    """Format phrase hierarchy: roots, extensions, strategy.
    
    Data sources (checked in order):
    1. pre_batch["enhanced"]["phrase_hierarchy"] — from enhanced_pre_batch.py
    2. pre_batch["_phrase_hierarchy"] — injected by app.py from /phrase_hierarchy endpoint
    """
    hier = (pre_batch.get("enhanced") or {}).get("phrase_hierarchy") or pre_batch.get("_phrase_hierarchy") or {}
    if not hier:
        return ""

    parts = ["═══ HIERARCHIA FRAZ ═══"]

    strategies = hier.get("strategies") or {}

    # 1. Extensions sufficient — don't repeat root standalone
    ext_suff = strategies.get("extensions_sufficient") or {}
    ext_roots = ext_suff.get("roots") or []
    if ext_roots:
        parts.append("RDZENIE POKRYTE ROZSZERZENIAMI (NIE powtarzaj samodzielnie!):")
        for root_info in ext_roots[:8]:
            if isinstance(root_info, dict):
                root = root_info.get("root", root_info.get("keyword", ""))
                extensions = root_info.get("extensions", [])
                ext_list = ", ".join(f'"{e}"' if isinstance(e, str) else f'"{e.get("keyword", "")}"' for e in extensions[:5])
                parts.append(f'  • "{root}" → używaj rozszerzeń: {ext_list}')
            elif isinstance(root_info, str):
                parts.append(f'  • "{root_info}" → używaj rozszerzeń zamiast rdzenia')

    # 2. Mixed — some standalone + extensions
    mixed = strategies.get("mixed") or {}
    mixed_roots = mixed.get("roots") or []
    if mixed_roots:
        parts.append("RDZENIE MIESZANE (kilka samodzielnych użyć + rozszerzenia):")
        for root_info in mixed_roots[:8]:
            if isinstance(root_info, dict):
                root = root_info.get("root", root_info.get("keyword", ""))
                standalone = root_info.get("standalone_uses", "1-2")
                extensions = root_info.get("extensions", [])
                ext_list = ", ".join(f'"{e}"' if isinstance(e, str) else f'"{e.get("keyword", "")}"' for e in extensions[:5])
                parts.append(f'  • "{root}" → {standalone}× samodzielnie + rozszerzenia: {ext_list}')
            elif isinstance(root_info, str):
                parts.append(f'  • "{root_info}" → kilka samodzielnie + rozszerzenia')

    # 3. Need standalone — extensions insufficient
    standalone = strategies.get("need_standalone") or {}
    standalone_roots = standalone.get("roots") or []
    if standalone_roots:
        parts.append("RDZENIE WYMAGAJĄCE SAMODZIELNYCH UŻYĆ:")
        for root_info in standalone_roots[:8]:
            if isinstance(root_info, dict):
                root = root_info.get("root", root_info.get("keyword", ""))
                target = root_info.get("remaining", root_info.get("target", "?"))
                parts.append(f'  • "{root}" → użyj samodzielnie jeszcze ~{target}×')
            elif isinstance(root_info, str):
                parts.append(f'  • "{root_info}" → użyj samodzielnie')

    # 4. Entity phrases (if available)
    entity_phrases = hier.get("entity_phrases") or []
    if entity_phrases:
        ep_list = ", ".join(f'"{e}"' if isinstance(e, str) else f'"{e.get("keyword", "")}"' for e in entity_phrases[:6])
        parts.append(f"FRAZY ENCYJNE (wpleć naturalnie): {ep_list}")

    # 5. Triplet phrases (if available)
    triplet_phrases = hier.get("triplet_phrases") or []
    if triplet_phrases:
        tp_list = ", ".join(f'"{t}"' if isinstance(t, str) else f'"{t.get("keyword", "")}"' for t in triplet_phrases[:6])
        parts.append(f"FRAZY TRIPLETOWE (relacje do wplecenia): {tp_list}")

    if len(parts) <= 1:
        return ""

    return "\n".join(parts)


def _fmt_h2_remaining(pre_batch):
    h2_remaining = pre_batch.get("h2_remaining") or []
    if not h2_remaining:
        return ""

    h2_list = ", ".join(f'"{h}"' for h in h2_remaining[:6])
    return f"═══ PLAN ═══\nPozostałe sekcje H2 w artykule: {h2_list}\nNie zachodź na ich tematy — zostaną pokryte później."


def _fmt_output_format(h2, batch_type):
    if batch_type in ("INTRO", "intro"):
        return f"""═══ FORMAT ODPOWIEDZI ═══
Pisz TYLKO treść wstępu. NIE zaczynaj od "h2:" — wstęp nie ma nagłówka.
80-150 słów. Frazę główną wpleć w PIERWSZE zdanie.
NIE dodawaj komentarzy, wyjaśnień — TYLKO treść wstępu."""
    
    return f"""═══ FORMAT ODPOWIEDZI ═══
Pisz TYLKO treść tego batcha. Zaczynaj dokładnie od:

h2: {h2}

Potem: akapity tekstu (40-150 słów każdy), opcjonalnie h3: [podsekcja].
NIE dodawaj komentarzy, wyjaśnień, podsumowań — TYLKO treść artykułu."""


# ════════════════════════════════════════════════════════════
# FAQ PROMPT BUILDER
# ════════════════════════════════════════════════════════════

def build_faq_system_prompt(pre_batch=None):
    """System prompt for FAQ generation."""
    base = (
        "Jesteś doświadczonym polskim copywriterem SEO. "
        "Piszesz sekcję FAQ — zwięzłe, konkretne odpowiedzi na pytania użytkowników. "
        "Każda odpowiedź ma szansę trafić do Google Featured Snippet — pisz bezpośrednio i merytorycznie."
    )

    gpt_instructions = ""
    if pre_batch:
        gpt_instructions = pre_batch.get("gpt_instructions_v39", "")

    if gpt_instructions:
        return base + "\n\n" + gpt_instructions
    return base


def build_faq_user_prompt(paa_data, pre_batch=None):
    """User prompt for FAQ generation."""
    # Normalize: if paa_data is a list (raw PAA questions), wrap it
    if isinstance(paa_data, list):
        paa_data = {"serp_paa": paa_data}
    elif not isinstance(paa_data, dict):
        paa_data = {}
    paa_questions = paa_data.get("serp_paa") or []
    unused = paa_data.get("unused_keywords") or {}
    avoid = paa_data.get("avoid_in_faq") or []
    if isinstance(avoid, dict):
        avoid = avoid.get("topics") or []
    elif not isinstance(avoid, list):
        avoid = []
    instructions_raw = paa_data.get("instructions", "")
    if isinstance(instructions_raw, dict):
        parts = []
        for k, v in instructions_raw.items():
            if isinstance(v, str):
                parts.append(f"• {v}")
            elif isinstance(v, dict):
                for sk, sv in v.items():
                    if isinstance(sv, str):
                        parts.append(f"• {sk}: {sv}")
        instructions = "\n".join(parts)
    elif isinstance(instructions_raw, str):
        instructions = instructions_raw
    else:
        instructions = ""

    enhanced_paa = []
    if pre_batch:
        enhanced = pre_batch.get("enhanced") or {}
        if not isinstance(enhanced, dict):
            enhanced = {}
        enhanced_paa = enhanced.get("paa_from_serp") or []
        if not isinstance(enhanced_paa, list):
            enhanced_paa = []

    keyword_limits = {}
    if pre_batch:
        keyword_limits = pre_batch.get("keyword_limits") or {}
        if not isinstance(keyword_limits, dict):
            keyword_limits = {}
    stop_raw = keyword_limits.get("stop_keywords") or []
    stop_names = [s.get("keyword", s) if isinstance(s, dict) else s for s in stop_raw]

    style = {}
    if pre_batch:
        style = pre_batch.get("style_instructions") or {}

    sections = []

    sections.append("""═══ SEKCJA FAQ ═══
Napisz sekcję FAQ. Zaczynaj DOKŁADNIE od:
h2: Najczęściej zadawane pytania""")

    all_paa = list(dict.fromkeys(paa_questions + enhanced_paa))
    if all_paa:
        sections.append("Pytania z Google (People Also Ask) — to NAPRAWDĘ pytają użytkownicy:")
        for i, q in enumerate(all_paa[:8], 1):
            q_text = q.get("question", q) if isinstance(q, dict) else q
            if q_text and q_text.strip():
                sections.append(f'  {i}. {q_text}')
        sections.append("Wybierz 4-6 najlepszych. Możesz przeformułować, ale zachowaj sens.")

    if unused:
        if isinstance(unused, dict):
            unused_list = []
            for cat, items in unused.items():
                if isinstance(items, list):
                    unused_list.extend(items[:5])
                elif isinstance(items, str):
                    unused_list.append(items)
            if unused_list:
                names = ", ".join(f'"{u}"' if isinstance(u, str) else f'"{u.get("keyword", "")}"' for u in unused_list[:8])
                sections.append(f'\nFrazy jeszcze nieużyte — wpleć w odpowiedzi: {names}')
        elif isinstance(unused, list):
            names = ", ".join(f'"{u}"' for u in unused[:8])
            sections.append(f'\nFrazy jeszcze nieużyte — wpleć w odpowiedzi: {names}')

    if avoid:
        topics = ", ".join(f'"{a}"' if isinstance(a, str) else f'"{a.get("topic", "")}"' for a in avoid[:8])
        sections.append(f'\nNIE powtarzaj tematów już pokrytych w artykule: {topics}')

    if stop_names:
        sections.append(f'\n🛑 STOP — NIE UŻYWAJ: {", ".join(f"{s}" for s in stop_names[:5])}')

    if style:
        forbidden = style.get("forbidden_phrases") or []
        if forbidden:
            sections.append(f'ZAKAZANE zwroty: {", ".join(forbidden[:5])}')

    if pre_batch and pre_batch.get("article_memory"):
        mem = pre_batch["article_memory"]
        if isinstance(mem, dict):
            topics = mem.get("topics_covered") or []
            if topics:
                topic_names = [t if isinstance(t, str) else t.get("topic", "") for t in topics[:6]]
                sections.append(f'\nTematy z artykułu (nie powtarzaj): {", ".join(topic_names)}')

    if instructions:
        sections.append(f'\n{instructions}')

    sections.append("""
═══ FORMAT ═══
h2: Najczęściej zadawane pytania

h3: [Pytanie — 5-10 słów, zaczynaj od Jak/Czy/Co/Dlaczego/Ile]
[Odpowiedź 60-120 słów]
→ Zdanie 1: BEZPOŚREDNIA odpowiedź
→ Zdanie 2-3: rozwinięcie z konkretem
→ Zdanie 4: praktyczna wskazówka lub wyjątek

Napisz 4-6 pytań. Pisz TYLKO treść, bez komentarzy.""")

    return "\n\n".join(sections)


# ════════════════════════════════════════════════════════════
# H2 PLAN PROMPT BUILDER
# ════════════════════════════════════════════════════════════

def build_h2_plan_system_prompt():
    """System prompt for H2 plan generation."""
    return (
        "Jesteś ekspertem SEO z 10-letnim doświadczeniem w planowaniu architektury treści. "
        "Tworzysz logiczne, wyczerpujące struktury nagłówków H2, które pokrywają temat kompleksowo "
        "i dają przewagę nad konkurencją dzięki pokryciu luk treściowych."
    )


def build_h2_plan_user_prompt(main_keyword, mode, s1_data, all_user_phrases, user_h2_hints=None):
    """Build readable H2 plan prompt from S1 analysis data."""
    s1_data = s1_data or {}
    competitor_h2 = s1_data.get("competitor_h2_patterns") or []
    suggested_h2s = (s1_data.get("content_gaps") or {}).get("suggested_new_h2s", [])
    content_gaps = s1_data.get("content_gaps") or {}
    causal_triplets = s1_data.get("causal_triplets") or {}
    paa = s1_data.get("paa") or s1_data.get("paa_questions") or []

    sections = []

    mode_desc = "standard = pełny artykuł" if mode == "standard" else "fast = krótki artykuł, max 3 sekcje"
    sections.append(f"""HASŁO GŁÓWNE: {main_keyword}
TRYB: {mode} ({mode_desc})""")

    if competitor_h2:
        lines = ["═══ WZORCE H2 KONKURENCJI (najczęstsze tematy sekcji) ═══"]
        for i, h in enumerate(competitor_h2[:20], 1):
            if isinstance(h, dict):
                pattern = h.get("pattern", h.get("h2", str(h)))
                count = h.get("count", "")
                lines.append(f"  {i}. {pattern}" + (f" ({count}×)" if count else ""))
            elif isinstance(h, str):
                lines.append(f"  {i}. {h}")
        sections.append("\n".join(lines))

    if suggested_h2s:
        lines = ["═══ SUGEROWANE NOWE H2 (luki — tego NIKT z konkurencji nie pokrywa) ═══"]
        for h in suggested_h2s[:10]:
            h_text = h if isinstance(h, str) else h.get("h2", h.get("title", str(h)))
            lines.append(f"  • {h_text}")
        sections.append("\n".join(lines))

    # Content gaps — ordered by priority (GPT prompt: PAA_UNANSWERED > DEPTH_MISSING > SUBTOPIC_MISSING)
    gap_priority_map = {
        "paa_unanswered": ("🔴 HIGH", "PAA bez odpowiedzi"),
        "depth_missing": ("🟡 MED-HIGH", "Brak głębi"),
        "subtopic_missing": ("🟢 MED", "Brakujący podtemat"),
        "gaps": ("", "Luka"),
    }
    all_gaps = []
    for key in ("paa_unanswered", "depth_missing", "subtopic_missing", "gaps"):
        priority, label = gap_priority_map.get(key, ("", ""))
        items = content_gaps.get(key) or []
        for item in items[:5]:
            gap_text = item if isinstance(item, str) else item.get("gap", item.get("topic", str(item)))
            if gap_text and gap_text not in [g[0] for g in all_gaps]:
                all_gaps.append((gap_text, priority, label))
    if all_gaps:
        lines = ["═══ LUKI TREŚCIOWE (tematy do pokrycia — priorytet od najwyższego) ═══"]
        for gap_text, priority, label in all_gaps[:10]:
            prefix = f"[{priority}] " if priority else ""
            lines.append(f"  • {prefix}{gap_text}")
        sections.append("\n".join(lines))

    if paa:
        lines = ["═══ PYTANIA PAA (People Also Ask z Google) ═══"]
        for q in paa[:8]:
            q_text = q.get("question", q) if isinstance(q, dict) else q
            if q_text:
                lines.append(f"  ❓ {q_text}")
        sections.append("\n".join(lines))

    triplet_list = (causal_triplets.get("chains") or causal_triplets.get("singles")
                    or causal_triplets.get("triplets") or [])[:8]
    if triplet_list:
        lines = ["═══ PRZYCZYNOWE ZALEŻNOŚCI (cause→effect z konkurencji) ═══",
                 "Confidence: 🔴 ≥0.9 UŻYJ | 🟡 ≥0.6 gdy pasuje | 🟢 <0.6 opcjonalnie",
                 "is_chain=True (A→B→C) = najcenniejsze — buduj logiczny przepływ"]
        for t in triplet_list:
            if isinstance(t, dict):
                cause = t.get("cause", t.get("subject", ""))
                effect = t.get("effect", t.get("object", ""))
                conf = t.get("confidence", 0)
                is_chain = t.get("is_chain", False)
                
                # Priority indicator
                if conf >= 0.9:
                    ind = "🔴"
                elif conf >= 0.6:
                    ind = "🟡"
                else:
                    ind = "🟢"
                chain_tag = " [CHAIN]" if is_chain else ""
                conf_str = f" ({conf:.1f})" if conf else ""
                lines.append(f"  {ind} {cause} → {effect}{conf_str}{chain_tag}")
            elif isinstance(t, str):
                lines.append(f"  • {t}")
        sections.append("\n".join(lines))

    if user_h2_hints:
        h2_hints_list = "\n".join(f'  • "{h}"' for h in user_h2_hints[:10])
        sections.append(f"""═══ FRAZY H2 UŻYTKOWNIKA ═══

Użytkownik podał te frazy z myślą o nagłówkach H2.
Wykorzystaj je w nagłówkach tam, gdzie brzmią naturalnie po polsku.
Nie musisz użyć każdej — ale nie ignoruj ich. Dopasuj z wyczuciem.

Jeśli fraza brzmi sztucznie jako nagłówek — przeformułuj lub pomiń (trafi do treści).

FRAZY H2:
{h2_hints_list}""")

    if all_user_phrases:
        phrases_text = ", ".join(f'"{p}"' for p in all_user_phrases[:15])
        sections.append(f"""═══ KONTEKST TEMATYCZNY (frazy BASIC/EXTENDED) ═══

Poniższe frazy będą użyte W TREŚCI artykułu (nie w nagłówkach).
Podaję je żebyś wiedział jaki zakres tematyczny artykuł musi pokryć
i zaplanował H2 tak, by każda fraza miała naturalną sekcję:

{phrases_text}""")

    fast_note = "Tryb fast: DOKŁADNIE 3 sekcje + FAQ (4 H2 łącznie)." if mode == "fast" else ""
    
    # v50.5 FIX 29: Dynamic H2 count based on recommended article length
    # Instead of hard-coded "6-9 H2", scale H2 count to match content needs.
    # Each H2 section generates ~200-400 words. Too many H2s → article bloat.
    length_analysis = s1_data.get("length_analysis") or {}
    rec_length = length_analysis.get("recommended") or s1_data.get("recommended_length") or 0
    median_length = length_analysis.get("median") or s1_data.get("median_length") or 0
    
    if mode != "fast":
        # Use recommended length (or median × 2 as fallback) to determine H2 count
        target = rec_length or (median_length * 2) or 1500
        if target <= 500:
            h2_range = "2-3"
            h2_min, h2_max = 2, 3
        elif target <= 1000:
            h2_range = "3-4"
            h2_min, h2_max = 3, 4
        elif target <= 2000:
            h2_range = "4-6"
            h2_min, h2_max = 4, 6
        elif target <= 3500:
            h2_range = "5-7"
            h2_min, h2_max = 5, 7
        else:
            h2_range = "6-9"
            h2_min, h2_max = 6, 9
        
        fast_note = (
            f"Tryb standard: {h2_range} sekcji + FAQ ({h2_min+1}-{h2_max+1} H2 łącznie).\n"
            f"   UWAGA: Rekomendowana długość artykułu: ~{target} słów (mediana konkurencji: {median_length}).\n"
            f"   Każda sekcja H2 = ~{target // (h2_max + 1)}-{target // h2_min} słów.\n"
            f"   NIE GENERUJ więcej niż {h2_max + 1} H2 (wliczając FAQ)!"
        )
    
    h2_hint_rule = ("Uwzględnij frazy H2 użytkownika w nagłówkach, o ile brzmią naturalnie."
                    if user_h2_hints else "Dobierz nagłówki na podstawie S1 i luk treściowych.")

    sections.append(f"""═══ ZASADY ═══

1. LICZBA H2: {fast_note}
2. OSTATNI H2 MUSI być: "Najczęściej zadawane pytania"
3. Pokryj najważniejsze wzorce z konkurencji + luki treściowe (przewaga nad konkurencją)
4. {h2_hint_rule}
5. Logiczna narracja — od ogółu do szczegółu, chronologicznie, lub problemowo
6. NIE powtarzaj hasła głównego dosłownie w każdym H2
7. H2 muszą brzmieć naturalnie po polsku — żadnego keyword stuffingu

═══ FORMAT ODPOWIEDZI ═══

Odpowiedz TYLKO JSON array, bez markdown, bez komentarzy:
["H2 pierwszy", "H2 drugi", ..., "Najczęściej zadawane pytania"]""")

    return "\n\n".join(sections)
