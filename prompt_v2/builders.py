"""
═══════════════════════════════════════════════════════════
PROMPT V2 — BUILDERS (drop-in replacement for prompt_builder.py)
═══════════════════════════════════════════════════════════
Identyczny interfejs:
  build_system_prompt(pre_batch, batch_type)
  build_user_prompt(pre_batch, h2, batch_type, article_memory=None)
  build_faq_system_prompt(pre_batch=None)
  build_faq_user_prompt(paa_data, pre_batch=None)
  build_h2_plan_system_prompt()
  build_h2_plan_user_prompt(main_keyword, mode, s1_data, all_user_phrases, user_h2_hints=None)
  build_category_system_prompt(pre_batch, batch_type, category_data=None)
  build_category_user_prompt(pre_batch, h2, batch_type, article_memory=None, category_data=None)

Zmiany vs v1:
  1. System prompt: Konstytucja + polszczyzna + few-shot (zamiast listy zakazów)
  2. User prompt: dane PRZED instrukcjami, thinking block, voice anchor
  3. Entity context: filtrowany (max 3 bloki), naturalniejszy format
  4. Keywords: natural language zamiast bullet list
  5. Article outline: pełna struktura (co napisane, co teraz, co dalej)
═══════════════════════════════════════════════════════════
"""

import json
import logging

from prompt_v2.constants import (
    PERSONAS, CONSTITUTION, POLISH_RULES, FORBIDDEN_SHORT,
    WRITING_RULES, ENTITY_RULES, SOURCES_YMYL, SOURCES_GENERAL,
    CATEGORY_STYLE, CATEGORY_EXAMPLES, DEFAULT_EXAMPLE,
    REAL_WORLD_ANCHORS,
)
from prompt_v2.style_samples import format_samples_block
from prompt_v2.config import feature_enabled

try:
    from shared_constants import (
        SENTENCE_AVG_TARGET, SENTENCE_AVG_TARGET_MIN, SENTENCE_AVG_TARGET_MAX,
        SENTENCE_SOFT_MAX, SENTENCE_HARD_MAX, SENTENCE_AVG_MAX_ALLOWED,
    )
except ImportError:
    SENTENCE_AVG_TARGET = 13
    SENTENCE_AVG_TARGET_MIN = 8
    SENTENCE_AVG_TARGET_MAX = 20
    SENTENCE_SOFT_MAX = 30
    SENTENCE_HARD_MAX = 40
    SENTENCE_AVG_MAX_ALLOWED = 22

_pb_logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════
# HELPERS (shared with v1)
# ════════════════════════════════════════════════════════════

def _word_trim(text, max_chars):
    if not text or len(text) <= max_chars:
        return text
    trimmed = text[:max_chars]
    nl = chr(10)
    last_break = max(trimmed.rfind(" "), trimmed.rfind(nl), trimmed.rfind(". "))
    if last_break > max_chars // 2:
        trimmed = trimmed[:last_break]
    return trimmed.rstrip(" ,;:") + "..."


def _find_variants(keyword, variant_dict):
    if not keyword or not variant_dict:
        return []
    kw_lower = keyword.lower().strip()
    for key, variants in variant_dict.items():
        if key.lower().strip() == kw_lower:
            return variants
    kw_stems = set(w[:4] for w in kw_lower.split() if len(w) >= 4)
    if not kw_stems:
        return []
    for key, variants in variant_dict.items():
        key_stems = set(w[:4] for w in key.lower().split() if len(w) >= 4)
        if kw_stems and key_stems and kw_stems & key_stems:
            return variants
    return []


def _parse_target_max(target_total_str):
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


_CRITICAL_FIELDS = ["keywords", "main_keyword", "batch_number"]
_IMPORTANT_FIELDS = [
    "gpt_instructions_v39", "enhanced", "h2_remaining",
    "article_memory", "keyword_limits", "coverage",
]


def _schema_guard(pre_batch):
    missing = [f for f in _CRITICAL_FIELDS if f not in pre_batch or pre_batch[f] is None]
    if missing:
        _pb_logger.warning(f"[prompt_v2] Missing critical fields: {missing}")


# ════════════════════════════════════════════════════════════
# SYSTEM PROMPT — ARTICLE (v2)
# ════════════════════════════════════════════════════════════

def build_system_prompt(pre_batch, batch_type):
    """
    v2 System Prompt — stały per artykuł.
    Struktura:
      1. Persona (3-4 zdania)
      2. Konstytucja (8 zasad pozytywnych)
      3. Zasady pisania (skompresowane z v1)
      4. Reguły polszczyzny (po polsku!)
      5. Entity SEO (wzorce wplatania)
      6. Anty-AI (krótka lista zakazów)
      7. Źródła (YMYL/ogólne)
      8. Styl kategorii
      9. Przykład TAK/NIE
     10. ** FEW-SHOT SAMPLES ** (NOWE!)
    """
    pre_batch = pre_batch or {}
    parts = []

    detected_category = pre_batch.get("detected_category", "")
    is_ymyl = detected_category in ("prawo", "medycyna", "finanse")

    # ═══ 1. PERSONA (skrócona) ═══
    persona = PERSONAS.get(detected_category, PERSONAS["inne"])
    parts.append(f"<tożsamość>\n{persona}\nTon: pewny, konkretny, rzeczowy. 3. osoba. ZAKAZ 2. osoby (ty/Twój).\n</tożsamość>")

    # ═══ 2. KONSTYTUCJA (NOWE — pozytywne zasady) ═══
    if feature_enabled("positive_constitution"):
        parts.append(CONSTITUTION)

    # ═══ 3. ZASADY PISANIA (zachowane z v1, skompresowane) ═══
    parts.append(WRITING_RULES)

    # ═══ 3.5 PRAKTYKA (anty-encyklopedia) ═══
    parts.append(REAL_WORLD_ANCHORS)

    # ═══ 4. REGUŁY POLSZCZYZNY (NOWE — po polsku!) ═══
    if feature_enabled("polish_language_block"):
        parts.append(POLISH_RULES)

    # ═══ 5. ENTITY SEO (naturalniejsze wplatanie) ═══
    parts.append(ENTITY_RULES)

    # ═══ 6. ANTY-AI (krótka lista) ═══
    if feature_enabled("short_forbidden_list"):
        parts.append(FORBIDDEN_SHORT)
    else:
        # Fallback to longer v1-style list
        parts.append(FORBIDDEN_SHORT)

    # ═══ 7. ŹRÓDŁA ═══
    if is_ymyl:
        parts.append(SOURCES_YMYL)
    else:
        parts.append(SOURCES_GENERAL)

    # ═══ 8. STYL KATEGORII (per-kategoria) ═══
    cat_style = CATEGORY_STYLE.get(detected_category, "")
    if cat_style:
        parts.append(f"<styl_kategorii>\n{cat_style}\n</styl_kategorii>")

    # ═══ 9. PRZYKŁAD TAK/NIE ═══
    example_text = CATEGORY_EXAMPLES.get(detected_category, DEFAULT_EXAMPLE)
    parts.append(f"<przyklad>\n{example_text}\n</przyklad>")

    # ═══ 10. FEW-SHOT SAMPLES (NOWE — game changer!) ═══
    if feature_enabled("few_shot_examples"):
        batch_number = pre_batch.get("batch_number", 1)
        samples_block = format_samples_block(
            category=detected_category or "inne",
            count=2,
            seed=batch_number  # different samples per batch, reproducible
        )
        parts.append(samples_block)

    return "\n\n".join(parts)


# ════════════════════════════════════════════════════════════
# USER PROMPT — ARTICLE (v2)
# ════════════════════════════════════════════════════════════

def build_user_prompt(pre_batch, h2, batch_type, article_memory=None):
    """
    v2 User Prompt — nowa kolejność: DANE → KONTEKST → INSTRUKCJE.
    Dokumentacja Anthropic: dane referencyjne PRZED instrukcjami = +30% jakości.
    """
    pre_batch = pre_batch or {}
    sections = []

    _schema_guard(pre_batch)

    # ═══ WARSTWA 1: DANE REFERENCYJNE (na górze — cache'owalne) ═══

    # Article outline (NOWE)
    if feature_enabled("article_outline"):
        outline = _fmt_article_outline(pre_batch, h2, batch_type)
        if outline:
            sections.append(outline)

    # Voice anchor (NOWE)
    if feature_enabled("voice_anchor"):
        voice = _fmt_voice_anchor(pre_batch)
        if voice:
            sections.append(voice)

    # Entity context (filtrowany)
    entity_ctx = _fmt_entity_context_v3(pre_batch) if feature_enabled("filtered_s1") else _fmt_entity_context_v2_compat(pre_batch)
    if entity_ctx:
        sections.append(entity_ctx)

    # SERP enrichment
    serp = _fmt_serp_enrichment(pre_batch)
    if serp:
        sections.append(serp)

    # Article memory
    memory = _fmt_article_memory(article_memory)
    if memory:
        sections.append(memory)

    # Legal/Medical (YMYL)
    legal_med = _fmt_legal_medical(pre_batch)
    if legal_med:
        sections.append(legal_med)

    # ═══ WARSTWA 2: INSTRUKCJE (na dole) ═══

    # Batch header
    header = _fmt_batch_header(pre_batch, h2, batch_type)
    if header:
        sections.append(header)

    # Keywords (natural language format)
    if feature_enabled("natural_keyword_format"):
        kw = _fmt_keywords_natural(pre_batch)
    else:
        kw = _fmt_keywords_compat(pre_batch)
    if kw:
        sections.append(kw)

    # Intro guidance (only for INTRO batch)
    intro = _fmt_intro_guidance(pre_batch, batch_type)
    if intro:
        sections.append(intro)

    # Planning instruction (NOWE — thinking block)
    if feature_enabled("thinking_block"):
        planning = _fmt_planning_instruction(pre_batch, batch_type)
        if planning:
            sections.append(planning)

    # Output format (always last)
    fmt = _fmt_output_format(h2, batch_type)
    if fmt:
        sections.append(fmt)

    return "\n\n".join(s for s in sections if s)


# ════════════════════════════════════════════════════════════
# NEW V2 FORMATTERS
# ════════════════════════════════════════════════════════════

def _fmt_article_outline(pre_batch, current_h2, batch_type):
    """Pełna struktura artykułu — co napisane, co teraz, co dalej."""
    h2_remaining = pre_batch.get("h2_remaining") or []
    batch_num = pre_batch.get("batch_number", 1)

    # Reconstruct done sections from article_memory
    memory = pre_batch.get("article_memory") or {}
    topics_done = []
    if isinstance(memory, dict):
        topics_raw = memory.get("topics_covered") or memory.get("covered_topics") or []
        for t in topics_raw:
            if isinstance(t, str):
                topics_done.append(t)
            elif isinstance(t, dict):
                topics_done.append(t.get("topic", t.get("h2", "")))

    lines = ["<outline>"]

    # Show completed sections
    if batch_num > 1 and batch_type not in ("INTRO", "intro"):
        lines.append("✅ Lead — NAPISANE")
    for done in topics_done[:10]:
        if done:
            lines.append(f"✅ H2: {done} — NAPISANE")

    # Current section
    if batch_type in ("INTRO", "intro"):
        lines.append("→ Lead — TERAZ PISZESZ")
    elif current_h2:
        lines.append(f"→ H2: {current_h2} — TERAZ PISZESZ")

    # Remaining sections
    for h2 in h2_remaining:
        if h2 and h2 != current_h2:
            lines.append(f"⬜ H2: {h2}")

    # Word count progress
    total_words = 0
    if isinstance(memory, dict):
        facts = memory.get("key_facts_used") or []
        total_words = len(facts) * 50  # rough estimate
    continuation = pre_batch.get("continuation_v39") or {}
    if continuation.get("total_words"):
        total_words = continuation["total_words"]

    target = pre_batch.get("target_article_length", 0)
    if total_words and target:
        lines.append(f"Postęp: ~{total_words}/{target} słów")

    lines.append("</outline>")
    return "\n".join(lines) if len(lines) > 2 else ""


def _fmt_voice_anchor(pre_batch):
    """Kotwica głosu — style anchor z batcha 1 + ostatnie zdania."""
    parts = []
    batch_num = pre_batch.get("batch_number", 1)

    # Style anchor from batch 1 (frozen for entire article)
    style_anchor = pre_batch.get("_voice_style_anchor", "")
    if style_anchor and batch_num > 2:
        parts.append(
            f"<style_anchor>\n"
            f"Styl artykułu (utrzymaj TEN styl do końca):\n"
            f"\"{_word_trim(style_anchor, 300)}\"\n"
            f"</style_anchor>"
        )

    # Last sentences from previous batch (continuation)
    voice_last = pre_batch.get("_voice_last_sentences", "")
    if not voice_last:
        cont = pre_batch.get("continuation_v39") or {}
        enhanced = pre_batch.get("enhanced") or {}
        cont_ctx = enhanced.get("continuation_context") or {}
        voice_last = cont_ctx.get("last_paragraph_ending") or cont.get("last_paragraph_ending", "")

    if voice_last and batch_num > 1:
        parts.append(
            f"<kontynuacja>\n"
            f"Ostatni akapit (kontynuuj TYM SAMYM stylem, nie powtarzaj):\n"
            f"\"{_word_trim(voice_last, 250)}\"\n"
            f"Przejdź PŁYNNIE — gdyby ktoś czytał ciągiem, nie powinien zauważyć granicy.\n"
            f"</kontynuacja>"
        )

    return "\n\n".join(parts) if parts else ""


def _fmt_entity_context_v3(pre_batch):
    """
    v3 Entity Context — filtrowany, max 3 bloki.
    Mniej danych = lepsze wplecenie w narrację.
    """
    parts = []
    s1_ctx = pre_batch.get("_s1_context") or {}

    _raw_main = pre_batch.get("main_keyword") or {}
    main_name = _raw_main.get("keyword", "") if isinstance(_raw_main, dict) else str(_raw_main)

    # ── Block 1: Synonyms ──
    if main_name:
        sv = pre_batch.get("_search_variants") or {}
        peryfrazy = sv.get("peryfrazy", [])
        _entity_seo = (pre_batch.get("s1_data") or {}).get("entity_seo") or pre_batch.get("entity_seo") or {}
        synonyms = peryfrazy[:5] or [str(s) for s in _entity_seo.get("entity_synonyms", [])[:5]]
        if synonyms:
            parts.append(f"<encje_sekcji>\nSynonimy frazy głównej: {', '.join(synonyms)}")
        else:
            parts.append("<encje_sekcji>")

    # ── Block 2: Lead entity + concepts (max 6 items total) ──
    lead = s1_ctx.get("lead_entity")
    concepts = s1_ctx.get("concepts", [])
    e_gaps = s1_ctx.get("entity_gaps", [])

    concept_items = []
    if lead and lead.lower() != main_name.lower():
        concept_items.append(f"🎯 Encja wiodąca: {lead} — PODMIOT w min. 2 zdaniach")
    all_to_weave = concepts[:4]
    for g in e_gaps[:2]:
        if g not in all_to_weave:
            all_to_weave.append(f"{g} [luka]")
    if all_to_weave:
        concept_items.append(f"Wpleć naturalnie: {', '.join(all_to_weave[:6])}")
    if concept_items:
        parts.append("\n".join(concept_items))

    # ── Block 3: EAV facts (max 5, filtered per H2) ──
    eav = s1_ctx.get("eav", [])
    if eav:
        eav_lines = ["Fakty do wplecenia W ZDANIACH (nie listuj):"]
        for e in eav[:5]:
            marker = "🎯" if e.get("is_primary") else "•"
            eav_lines.append(f'  {marker} {e.get("entity","")} → {e.get("attribute","")} → {e.get("value","")}')
        parts.append("\n".join(eav_lines))

    # ── Block 4: Co-occurrence (max 3 pairs) ──
    cooc = s1_ctx.get("cooc", [])
    if cooc:
        parts.append(f"Encje razem w akapicie: {' | '.join(cooc[:3])}")

    # ── Block 5: Content gaps (max 3) ──
    gaps = s1_ctx.get("gaps", [])
    if gaps:
        parts.append(f"Luki TOP10 (dodaj information gain): {', '.join(gaps[:3])}")

    # Close tag
    if parts:
        parts.append("</encje_sekcji>")

    # ── Semantic angle (if available) ──
    plan = pre_batch.get("semantic_batch_plan") or {}
    if plan:
        h2_coverage = plan.get("h2_coverage") or {}
        for h2_name, info in h2_coverage.items():
            if isinstance(info, dict):
                angle = info.get("semantic_angle", "")
                if angle:
                    parts.append(f"Kąt sekcji: {angle}")
                    break

    # ── Information gain (from master API) ──
    enhanced = pre_batch.get("enhanced") or {}
    info_gain = enhanced.get("information_gain", "")
    if info_gain:
        parts.append(f"Przewaga nad konkurencją: {_word_trim(info_gain, 200)}")

    # ── Fallback: if _s1_context empty ──
    if not s1_ctx:
        must_concepts = pre_batch.get("_must_cover_concepts") or []
        old_eav = pre_batch.get("_eav_triples") or []
        old_gaps = pre_batch.get("_entity_gaps") or []
        if must_concepts:
            names = [c.get("text", c) if isinstance(c, dict) else str(c) for c in must_concepts[:6]]
            parts.append(f"Wpleć: {', '.join(n for n in names if n)}")
        if old_eav:
            eav_lines = ["Fakty (wpleć w zdania):"]
            for e in old_eav[:4]:
                eav_lines.append(f'  • {e.get("entity","")} → {e.get("attribute","")} → {e.get("value","")}')
            parts.append("\n".join(eav_lines))
        if old_gaps:
            gap_names = [g.get("entity", "") for g in old_gaps if g.get("priority") == "high"][:3]
            if gap_names:
                parts.append(f"Luki: {', '.join(gap_names)}")

    return "\n\n".join(parts) if parts else ""


def _fmt_entity_context_v2_compat(pre_batch):
    """Fallback — compatible with v1 _fmt_entity_context_v2."""
    # Import from original if available, otherwise minimal version
    try:
        from prompt_builder import _fmt_entity_context_v2
        return _fmt_entity_context_v2(pre_batch)
    except ImportError:
        return _fmt_entity_context_v3(pre_batch)


def _fmt_keywords_natural(pre_batch):
    """
    v2 Keywords — natural language format.
    Frazy jako „tematy do poruszenia" zamiast checklista.
    """
    keywords_info = pre_batch.get("keywords") or {}
    keyword_limits = pre_batch.get("keyword_limits") or {}

    _kw_global_remaining = pre_batch.get("_kw_global_remaining", None)
    _main_kw_budget_exhausted = (_kw_global_remaining is not None and _kw_global_remaining == 0)
    _raw_main_kw = pre_batch.get("main_keyword") or {}
    main_kw = _raw_main_kw.get("keyword", "") if isinstance(_raw_main_kw, dict) else str(_raw_main_kw)

    entity_variants = pre_batch.get("_entity_variants") or \
        (pre_batch.get("_search_variants") or {}).get("secondary", {})

    # ── Collect must-use ──
    must_raw = keywords_info.get("basic_must_use", [])
    must_items = []
    for kw in must_raw:
        if isinstance(kw, dict):
            name = kw.get("keyword", "")
            if _main_kw_budget_exhausted and name and main_kw and name.lower() == main_kw.lower():
                continue
            hard_max = kw.get("hard_max_this_batch", "")
            hint = f" (max {hard_max}×)" if hard_max else ""
            must_items.append((name, hint))
        else:
            must_items.append((str(kw), ""))

    # ── Extended ──
    ext_raw = keywords_info.get("extended_this_batch", [])
    ext_items = []
    for kw in ext_raw:
        name = kw.get("keyword", kw) if isinstance(kw, dict) else str(kw)
        ext_items.append(name)

    # ── Stop ──
    stop_raw = keyword_limits.get("stop_keywords") or []
    stop_items = []
    for s in stop_raw:
        if isinstance(s, dict):
            name = s.get("keyword", "")
            variants = _find_variants(name, entity_variants)
            replacements = f" — zamiast napisz: {', '.join(variants[:3])}" if variants else ""
            stop_items.append((name, replacements))
        else:
            variants = _find_variants(str(s), entity_variants)
            replacements = f" — zamiast napisz: {', '.join(variants[:3])}" if variants else ""
            stop_items.append((str(s), replacements))

    # Handle exhausted main keyword
    _kw_force_ban = pre_batch.get("_kw_force_ban", False)
    if (_kw_force_ban or _main_kw_budget_exhausted) and main_kw:
        must_items = [(n, h) for n, h in must_items if main_kw.lower() not in n.lower()]
        variants = _find_variants(main_kw, entity_variants)
        replacements = f" — zamiast napisz: {', '.join(variants[:3])}" if variants else ""
        stop_items.append((main_kw, replacements))

    # ── Caution ──
    caution_raw = keyword_limits.get("caution_keywords") or []
    caution_names = []
    for c in caution_raw:
        name = c.get("keyword", c) if isinstance(c, dict) else str(c)
        if name:
            caution_names.append(name)

    # ── Build natural language block ──
    parts = ["<frazy>"]

    if must_items:
        parts.append("W tej sekcji poruszyj tematy:")
        for name, hint in must_items:
            if name:
                parts.append(f'— \u201e{name}\u201d{hint}')

    if ext_items:
        ext_str = ", ".join(f'\u201e{e}\u201d' for e in ext_items[:6] if e)
        parts.append(f"\nJeśli naturalnie pasują, wpleć też: {ext_str}")

    if stop_items:
        parts.append("\nNIE UŻYWAJ (limit wyczerpany):")
        for name, replacements in stop_items:
            if name:
                parts.append(f'  \u274c \u201e{name}\u201d{replacements}')

    if caution_names:
        parts.append(f"\nOstrożnie (max 1\u00d7): {', '.join(chr(8222) + n + chr(8221) for n in caution_names)}")

    # Anti-stuffing reminder
    parts.append("\nFLEKSJA: odmiana przez przypadki = jedno użycie. Max 2× ta sama fraza w akapicie.")

    # Anaphora variants
    sv = pre_batch.get("_search_variants") or {}
    peryfrazy = sv.get("peryfrazy", [])
    if main_kw and peryfrazy:
        parts.append(f'Zamienniki \u201e{main_kw}\u201d: {", ".join(peryfrazy[:4])}')
    elif main_kw:
        _entity_seo = (pre_batch.get("s1_data") or {}).get("entity_seo") or pre_batch.get("entity_seo") or {}
        syns = _entity_seo.get("entity_synonyms", [])[:4]
        if syns:
            parts.append(f'Zamienniki \u201e{main_kw}\u201d: {", ".join(str(s) for s in syns)}')

    parts.append("</frazy>")
    return "\n".join(parts) if len(parts) > 2 else ""


def _fmt_keywords_compat(pre_batch):
    """Fallback — v1-compatible keyword format."""
    try:
        from prompt_builder import _fmt_keywords
        return _fmt_keywords(pre_batch)
    except ImportError:
        return _fmt_keywords_natural(pre_batch)


def _fmt_planning_instruction(pre_batch, batch_type):
    """Guided chain-of-thought — Claude planuje przed pisaniem."""
    if batch_type in ("INTRO", "intro"):
        return (
            "<instrukcja>\n"
            "NAJPIERW zaplanuj w <thinking> (nie będzie widoczne):\n"
            "1. Jaki konkretny fakt lub liczbę podam w PIERWSZYM zdaniu?\n"
            "2. Czym jest fraza główna i dlaczego czytelnik powinien czytać dalej?\n"
            "3. Jakim zdaniem naturalnie przejdę do pierwszej sekcji H2?\n\n"
            "POTEM napisz lead w <article_section>.\n"
            "</instrukcja>"
        )

    return (
        "<instrukcja>\n"
        "NAJPIERW zaplanuj w <thinking> (nie będzie widoczne):\n"
        "1. Jaki konkret (liczba, fakt, przykład) otworzy tę sekcję?\n"
        "2. Gdzie naturalnie wplecę encję wiodącą i frazy kluczowe?\n"
        "3. Jakim faktem zakończę sekcję (NIE morałem)?\n"
        "4. Czy mam różnorodność zdań (krótkie + średnie + długie)?\n\n"
        "POTEM napisz tekst w <article_section>.\n"
        "</instrukcja>"
    )


# ════════════════════════════════════════════════════════════
# SHARED FORMATTERS (compatible with v1)
# ════════════════════════════════════════════════════════════

def _fmt_batch_header(pre_batch, h2, batch_type):
    batch_number = pre_batch.get("batch_number", 1)
    total_batches = pre_batch.get("total_planned_batches", 1)
    batch_length = pre_batch.get("batch_length") or {}

    if batch_type in ("INTRO", "intro"):
        return f"═══ BATCH {batch_number}/{total_batches}: INTRO ═══\nDługość: 120-200 słów"

    min_w = batch_length.get("min_words", 350)
    max_w = batch_length.get("max_words", 500)

    section_length = pre_batch.get("section_length_guidance") or {}
    length_hint = ""
    if section_length:
        suggested = section_length.get("suggested_words") or section_length.get("target_words")
        if suggested:
            length_hint = f"\nSugerowana długość: ~{suggested} słów."

    return (
        f"═══ BATCH {batch_number}/{total_batches}: {batch_type} ═══\n"
        f"Sekcja H2: {h2}\n"
        f"Długość: {min_w}-{max_w} słów{length_hint}\n"
        f"Zaczynaj DOKŁADNIE od: h2: {h2}"
    )


def _fmt_article_memory(article_memory):
    if not article_memory:
        return ""

    parts = ["<pamięć_artykułu>"]

    if isinstance(article_memory, dict):
        topics = article_memory.get("topics_covered") or article_memory.get("covered_topics") or []
        if topics:
            parts.append("Sekcje już napisane (NIE POWTARZAJ ich treści):")
            for t in topics[:10]:
                if isinstance(t, str):
                    parts.append(f'  ✓ {t}')
                elif isinstance(t, dict):
                    parts.append(f'  ✓ {t.get("topic", t.get("h2", ""))}')

        facts = article_memory.get("key_facts_used") or article_memory.get("facts", [])
        key_points = article_memory.get("key_points") or []
        all_facts = list(facts) + list(key_points)
        if all_facts:
            parts.append("\nFakty już podane (NIE POWTARZAJ):")
            for f in all_facts[:12]:
                parts.append(f'  • {f}' if isinstance(f, str) else f'  • {json.dumps(f, ensure_ascii=False)[:100]}')

        avoid_rep = article_memory.get("avoid_repetition") or []
        if avoid_rep:
            parts.append("\nUŻYTE ZDANIA — nie powtarzaj dosłownie:")
            for r in avoid_rep[:8]:
                parts.append(f'  ❌ „{r}"')

    elif isinstance(article_memory, str):
        parts.append(_word_trim(article_memory, 1500))

    parts.append("</pamięć_artykułu>")
    return "\n".join(parts) if len(parts) > 2 else ""


def _fmt_serp_enrichment(pre_batch):
    serp = pre_batch.get("serp_enrichment") or {}
    enhanced = pre_batch.get("enhanced") or {}

    paa = serp.get("paa_for_batch") or enhanced.get("paa_from_serp") or []
    lsi = serp.get("lsi_keywords") or []
    chips = serp.get("refinement_chips") or []

    if not paa and not lsi and not chips:
        return ""

    parts = ["<serp>"]
    if chips:
        parts.append(f"Podtematy Google: {', '.join(str(c) for c in chips[:8])}")
    if paa:
        q_strs = []
        for q in paa[:4]:
            q_text = q.get("question", q) if isinstance(q, dict) else q
            if q_text:
                q_strs.append(str(q_text))
        if q_strs:
            parts.append("Pytania PAA (odpowiedz na 1-2):\n  " + "\n  ".join(q_strs))
    if lsi:
        _ext_kws = pre_batch.get("keywords", {}).get("extended_this_batch", [])
        _ext_names = {(k.get("keyword", k) if isinstance(k, dict) else str(k)).lower().strip()
                      for k in _ext_kws}
        lsi_names = []
        for l in lsi[:8]:
            name = l.get("keyword", l) if isinstance(l, dict) else l
            if str(name).lower().strip() not in _ext_names:
                lsi_names.append(str(name))
        if lsi_names:
            parts.append(f"LSI: {', '.join(lsi_names)}")

    parts.append("</serp>")
    return "\n".join(parts) if len(parts) > 2 else ""


def _fmt_legal_medical(pre_batch):
    """Legal/Medical context — imported from v1 for full compatibility."""
    try:
        from prompt_builder import _fmt_legal_medical as v1_legal_medical
        return v1_legal_medical(pre_batch)
    except ImportError:
        # Minimal fallback
        legal_ctx = pre_batch.get("legal_context") or {}
        medical_ctx = pre_batch.get("medical_context") or {}
        if not legal_ctx.get("active") and not medical_ctx.get("active"):
            return ""
        parts = []
        if legal_ctx.get("active"):
            parts.append("═══ KONTEKST PRAWNY (YMYL) ═══")
            parts.append("NIE wymyślaj sygnatur, dat orzeczeń ani numerów artykułów.")
            instruction = legal_ctx.get("legal_instruction", "")
            if instruction:
                parts.append(instruction[:600])
        if medical_ctx.get("active"):
            parts.append("═══ KONTEKST MEDYCZNY (YMYL) ═══")
            parts.append("NIE wymyślaj statystyk ani nazw badań.")
            instruction = medical_ctx.get("medical_instruction", "")
            if instruction:
                parts.append(instruction[:600])
        return "\n".join(parts) if parts else ""


def _fmt_intro_guidance(pre_batch, batch_type):
    """Intro guidance — imported from v1 for full compatibility."""
    if batch_type not in ("INTRO", "intro"):
        return ""
    try:
        from prompt_builder import _fmt_intro_guidance_v2
        return _fmt_intro_guidance_v2(pre_batch, batch_type)
    except ImportError:
        main_kw = pre_batch.get("main_keyword") or {}
        kw_name = main_kw.get("keyword", "") if isinstance(main_kw, dict) else str(main_kw)
        parts = ["═══ LEAD (WSTĘP) ═══"]
        parts.append("120-200 słów. NIE zaczynaj od h2:. Lead nie ma nagłówka.")
        if kw_name:
            parts.append(f'Zacznij od sedna: czym jest „{kw_name}" i dlaczego czytelnik powinien czytać dalej.')
        parts.append("Kontekst praktyczny + konkretny fakt liczbowy w PIERWSZYM akapicie.")
        parts.append("NIE zapowiadaj co będzie dalej. NIE pisz 'w tym artykule dowiesz się'.")
        return "\n".join(parts)


def _fmt_output_format(h2, batch_type):
    if batch_type in ("INTRO", "intro"):
        return (
            "═══ FORMAT ODPOWIEDZI ═══\n"
            "Zaplanuj w <thinking>, napisz w <article_section>.\n"
            "120-200 słów. Frazę główną wpleć w PIERWSZE zdanie.\n"
            "NIE zaczynaj od h2:. Lead nie ma nagłówka.\n"
            "TYLKO treść leadu — zero meta-komentarzy."
        )

    return (
        f"═══ FORMAT ODPOWIEDZI ═══\n"
        f"Zaplanuj w <thinking>, napisz w <article_section>.\n"
        f"Zaczynaj od:\n\n"
        f"h2: {h2}\n\n"
        f"Akapity po 3-5 zdań. Opcjonalnie h3: [podsekcja].\n"
        f"Gdy masz 3+ warunków/kroków → lista <ul><li> (max 1-2 w artykule).\n"
        f"Gdy porównujesz dane liczbowe → tabela <table> (max 1 w artykule).\n"
        f"Każdy h2:/h3: na OSOBNEJ linii z pustą linią powyżej.\n"
        f"Zero markdown (**, __, #). Zero tagów HTML (<h2>, <h3>, <b>).\n"
        f"TYLKO treść artykułu — zero meta-komentarzy."
    )


# ════════════════════════════════════════════════════════════
# FAQ PROMPT BUILDER (zachowany z v1 + drobne ulepszenia)
# ════════════════════════════════════════════════════════════

def build_faq_system_prompt(pre_batch=None):
    detected_category = ""
    if pre_batch:
        detected_category = pre_batch.get("detected_category", "")

    base = (
        "Jesteś doświadczonym polskim copywriterem SEO. "
        "Piszesz sekcję FAQ: zwięzłe, konkretne odpowiedzi. "
        "Każda odpowiedź ma szansę trafić do Google Featured Snippet."
    )

    if feature_enabled("few_shot_examples") and detected_category:
        samples_block = format_samples_block(detected_category, count=1, seed=99)
        base += f"\n\n{samples_block}"

    gpt_instructions = ""
    if pre_batch:
        gpt_instructions = pre_batch.get("gpt_instructions_v39", "")
    if gpt_instructions:
        return base + "\n\n" + gpt_instructions
    return base


def build_faq_user_prompt(paa_data, pre_batch=None):
    """FAQ user prompt — delegated to v1 for full compatibility."""
    try:
        from prompt_builder import build_faq_user_prompt as v1_faq
        return v1_faq(paa_data, pre_batch)
    except ImportError:
        # Minimal fallback
        if isinstance(paa_data, list):
            paa_data = {"serp_paa": paa_data}
        paa_questions = paa_data.get("serp_paa") or []
        sections = ["═══ SEKCJA FAQ ═══\nNapisz sekcję FAQ.\nh2: Najczęściej zadawane pytania"]
        if paa_questions:
            sections.append("Pytania z Google (PAA):")
            for i, q in enumerate(paa_questions[:8], 1):
                q_text = q.get("question", q) if isinstance(q, dict) else q
                if q_text:
                    sections.append(f'  {i}. {q_text}')
            sections.append("Wybierz 4-6 najlepszych.")
        sections.append("Format: h3: [Pytanie] → odpowiedź 60-120 słów.")
        return "\n\n".join(sections)


# ════════════════════════════════════════════════════════════
# H2 PLAN PROMPT BUILDER (delegated to v1)
# ════════════════════════════════════════════════════════════

def build_h2_plan_system_prompt():
    return (
        "Jesteś ekspertem SEO z 10-letnim doświadczeniem w planowaniu architektury treści. "
        "Tworzysz logiczne, wyczerpujące struktury nagłówków H2."
    )


def build_h2_plan_user_prompt(main_keyword, mode, s1_data, all_user_phrases, user_h2_hints=None):
    """H2 planning — delegated to v1 for full compatibility."""
    try:
        from prompt_builder import build_h2_plan_user_prompt as v1_h2
        return v1_h2(main_keyword, mode, s1_data, all_user_phrases, user_h2_hints)
    except ImportError:
        return f"Zaplanuj H2 dla: {main_keyword}"


# ════════════════════════════════════════════════════════════
# CATEGORY PROMPT BUILDERS (delegated to v1)
# ════════════════════════════════════════════════════════════

def build_category_system_prompt(pre_batch, batch_type, category_data=None):
    """Category system prompt — delegated to v1 for full compatibility."""
    try:
        from prompt_builder import build_category_system_prompt as v1_cat_sys
        return v1_cat_sys(pre_batch, batch_type, category_data)
    except ImportError:
        return "Jesteś doświadczonym copywriterem e-commerce."


def build_category_user_prompt(pre_batch, h2, batch_type, article_memory=None, category_data=None):
    """Category user prompt — delegated to v1 for full compatibility."""
    try:
        from prompt_builder import build_category_user_prompt as v1_cat_user
        return v1_cat_user(pre_batch, h2, batch_type, article_memory, category_data)
    except ImportError:
        return f"Napisz opis kategorii: {h2}"
