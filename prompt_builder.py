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
• PASSAGE-FIRST: Każdy akapit zaczynaj od konkretnej odpowiedzi, potem rozwijaj.
• BURSTINESS: Mieszaj długość zdań — krótkie (8 słów) z dłuższymi (20-25 słów).
• ANTI-AI: Unikaj fraz-klisz: "warto zauważyć", "należy podkreślić", "w dzisiejszych czasach", "kluczowe jest", "nie ulega wątpliwości". Brzmi to sztucznie.
• NATURALNOŚĆ: Pisz jak ekspert tłumaczący temat znajomemu — konkretnie, bez lania wody.
• FORMAT: Używaj wyłącznie formatu h2:/h3: dla nagłówków. Żadnego markdown, HTML ani gwiazdek.""")

    return "\n\n".join(parts)


# ════════════════════════════════════════════════════════════
# USER PROMPT BUILDER
# ════════════════════════════════════════════════════════════

def build_user_prompt(pre_batch, h2, batch_type, article_memory=None):
    """
    Main user prompt builder.
    Converts ALL pre_batch fields into readable, actionable instructions.
    Each section is wrapped in try/except so one bad field won't crash generation.
    """
    pre_batch = pre_batch or {}
    sections = []

    formatters = [
        lambda: _fmt_batch_header(pre_batch, h2, batch_type),
        lambda: _fmt_intro_guidance(pre_batch, batch_type),
        lambda: _fmt_smart_instructions(pre_batch),
        lambda: _fmt_keywords(pre_batch),
        lambda: _fmt_semantic_plan(pre_batch, h2),
        lambda: _fmt_entities(pre_batch),
        lambda: _fmt_ngrams(pre_batch),
        lambda: _fmt_serp_enrichment(pre_batch),
        lambda: _fmt_continuation(pre_batch),
        lambda: _fmt_article_memory(article_memory),
        lambda: _fmt_coverage_density(pre_batch),
        lambda: _fmt_style(pre_batch),
        lambda: _fmt_legal_medical(pre_batch),
        lambda: _fmt_experience_markers(pre_batch),
        lambda: _fmt_causal_context(pre_batch),
        lambda: _fmt_h2_remaining(pre_batch),
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

    return f"""═══ BATCH {batch_number}/{total_batches} — {batch_type} ═══
Sekcja H2: "{h2}"
Długość: {min_w}-{max_w} słów{length_hint}
Zaczynaj DOKŁADNIE od: h2: {h2}"""


def _fmt_intro_guidance(pre_batch, batch_type):
    if batch_type not in ("INTRO", "intro"):
        return ""
    guidance = pre_batch.get("intro_guidance", "")
    if not guidance:
        return ""

    if isinstance(guidance, dict):
        hook = guidance.get("hook", "")
        angle = guidance.get("angle", "")
        parts = []
        if hook:
            parts.append(f"Hak otwierający: {hook}")
        if angle:
            parts.append(f"Kąt artykułu: {angle}")
        return "═══ WPROWADZENIE ═══\n" + "\n".join(parts) if parts else ""

    return f"═══ WPROWADZENIE ═══\n{guidance}"


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


def _fmt_entities(pre_batch):
    entities_for_batch = pre_batch.get("entities_for_batch") or {}
    entity_seo = pre_batch.get("entity_seo") or {}
    enhanced = pre_batch.get("enhanced") or {}
    entities_to_define = enhanced.get("entities_to_define") or []
    relations = enhanced.get("relations_to_establish") or []

    if not entities_for_batch and not entity_seo.get("enabled") and not entities_to_define:
        return ""

    parts = ["═══ ENCJE (budują autorytet tematyczny) ═══"]

    introduce = entities_for_batch.get("introduce") or []
    if introduce:
        parts.append("WPROWADŹ w tym batchu (pierwsza wzmianka):")
        for ent in introduce[:5]:
            if isinstance(ent, dict):
                name = ent.get("entity", ent.get("text", ""))
                etype = ent.get("type", "")
                context = ent.get("context", "")
                line = f'  • "{name}"'
                if etype:
                    line += f" ({etype})"
                if context:
                    line += f" — {context}"
                parts.append(line)
            else:
                parts.append(f'  • "{ent}"')

    if entities_to_define:
        parts.append("\nZDEFINIUJ (wyjaśnij czytelnikowi):")
        for ent in entities_to_define[:5]:
            if isinstance(ent, dict):
                name = ent.get("entity", ent.get("text", ""))
                hint = ent.get("definition_hint", ent.get("hint", ""))
                line = f'  • "{name}"'
                if hint:
                    line += f" — {hint}"
                parts.append(line)
            else:
                parts.append(f'  • "{ent}"')

    maintain = entities_for_batch.get("maintain") or []
    if maintain:
        names = ", ".join(f'"{m}"' if isinstance(m, str) else f'"{m.get("entity", "")}"' for m in maintain[:5])
        parts.append(f"\nUTRZYMUJ (już wprowadzone wcześniej): {names}")

    if relations:
        parts.append("\nPOWIĄŻ ze sobą:")
        for rel in relations[:4]:
            if isinstance(rel, dict):
                subj = rel.get("subject", "")
                verb = rel.get("verb", rel.get("relation", "→"))
                obj = rel.get("object", "")
                parts.append(f'  • {subj} {verb} {obj}')
            elif isinstance(rel, str):
                parts.append(f'  • {rel}')

    must_mention = entity_seo.get("must_mention") or []
    if must_mention and not introduce:
        parts.append("WSPOMNIJ w tekście:")
        for ent in must_mention[:5]:
            if isinstance(ent, dict):
                name = ent.get("text", ent.get("entity", ""))
                parts.append(f'  • "{name}"')
            else:
                parts.append(f'  • "{ent}"')

    return "\n".join(parts) if len(parts) > 1 else ""


def _fmt_ngrams(pre_batch):
    ngrams = pre_batch.get("ngrams_for_batch") or []
    ngram_guidance = pre_batch.get("ngram_guidance") or {}

    if not ngrams and not ngram_guidance:
        return ""

    parts = ["═══ POPULARNE FRAZY Z TOP10 (n-gramy) ═══",
             "Te frazy często pojawiają się u najlepszych wyników. Wpleć naturalnie:"]

    for ng in ngrams[:10]:
        if isinstance(ng, dict):
            text = ng.get("ngram", ng.get("text", ""))
            count = ng.get("count", ng.get("frequency", ""))
            if text:
                parts.append(f'  • "{text}"' + (f" ({count}× u konkurencji)" if count else ""))
        elif isinstance(ng, str):
            parts.append(f'  • "{ng}"')

    if ngram_guidance:
        overused = ngram_guidance.get("overused") or []
        if overused:
            over_list = ", ".join(f'"{o}"' if isinstance(o, str) else f'"{o.get("ngram", "")}"' for o in overused[:5])
            parts.append(f"\n⚠️ Nadużywane n-gramy (użyj zamienników): {over_list}")

        synonyms = ngram_guidance.get("suggested_synonyms") or ngram_guidance.get("synonyms") or {}
        if synonyms and isinstance(synonyms, dict):
            parts.append("Sugerowane zamienniki:")
            for orig, alts in list(synonyms.items())[:5]:
                if isinstance(alts, list):
                    parts.append(f'  • "{orig}" → {", ".join(alts[:3])}')

    return "\n".join(parts) if len(parts) > 2 else ""


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

    parts = ["═══ PAMIĘĆ ARTYKUŁU (nie powtarzaj!) ═══"]

    if isinstance(article_memory, dict):
        topics = article_memory.get("topics_covered") or article_memory.get("covered_topics") or []
        if topics:
            parts.append("Tematy już omówione w artykule:")
            for t in topics[:10]:
                if isinstance(t, str):
                    parts.append(f'  ✓ {t}')
                elif isinstance(t, dict):
                    parts.append(f'  ✓ {t.get("topic", t.get("h2", ""))}')

        facts = article_memory.get("key_facts_used") or article_memory.get("facts", [])
        if facts:
            parts.append("\nFakty już użyte (nie powtarzaj):")
            for f in facts[:8]:
                parts.append(f'  • {f}' if isinstance(f, str) else f'  • {json.dumps(f, ensure_ascii=False)[:100]}')

        phrases_used = article_memory.get("phrases_used") or {}
        if phrases_used:
            high_use = [(k, v) for k, v in phrases_used.items()
                        if isinstance(v, (int, float)) and v >= 3]
            if high_use:
                parts.append("\nFrazy już często użyte (ogranicz):")
                for name, count in high_use[:8]:
                    parts.append(f'  • "{name}" — już {count}×')
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

    parts = []

    if legal_ctx and legal_ctx.get("active"):
        parts.append("═══ KONTEKST PRAWNY (YMYL) ═══")
        parts.append("Ten artykuł dotyczy tematyki prawnej. MUSISZ:")
        parts.append("  1. Cytować realne przepisy i orzeczenia (podane niżej)")
        parts.append("  2. Dodać disclaimer o konsultacji z prawnikiem")
        parts.append("  3. NIE wymyślać sygnatur ani dat orzeczeń")

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
                    parts.append(f'  • {sig} — {court} ({date})')

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


def _fmt_h2_remaining(pre_batch):
    h2_remaining = pre_batch.get("h2_remaining") or []
    if not h2_remaining:
        return ""

    h2_list = ", ".join(f'"{h}"' for h in h2_remaining[:6])
    return f"═══ PLAN ═══\nPozostałe sekcje H2 w artykule: {h2_list}\nNie zachodź na ich tematy — zostaną pokryte później."


def _fmt_output_format(h2, batch_type):
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
        avoid = list(avoid.values()) if avoid else []
    elif not isinstance(avoid, list):
        avoid = []
    instructions = paa_data.get("instructions", "")

    enhanced_paa = []
    if pre_batch:
        enhanced = pre_batch.get("enhanced") or {}
        enhanced_paa = enhanced.get("paa_from_serp") or []

    keyword_limits = {}
    if pre_batch:
        keyword_limits = pre_batch.get("keyword_limits") or {}
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

    all_gaps = []
    for key in ("paa_unanswered", "subtopic_missing", "depth_missing", "gaps"):
        items = content_gaps.get(key) or []
        for item in items[:5]:
            gap_text = item if isinstance(item, str) else item.get("gap", item.get("topic", str(item)))
            if gap_text and gap_text not in all_gaps:
                all_gaps.append(gap_text)
    if all_gaps:
        lines = ["═══ LUKI TREŚCIOWE (tematy do pokrycia) ═══"]
        for g in all_gaps[:10]:
            lines.append(f"  • {g}")
        sections.append("\n".join(lines))

    if paa:
        lines = ["═══ PYTANIA PAA (People Also Ask z Google) ═══"]
        for q in paa[:8]:
            q_text = q.get("question", q) if isinstance(q, dict) else q
            if q_text:
                lines.append(f"  ❓ {q_text}")
        sections.append("\n".join(lines))

    triplet_list = (causal_triplets.get("chains") or causal_triplets.get("singles")
                    or causal_triplets.get("triplets") or [])[:5]
    if triplet_list:
        lines = ["═══ PRZYCZYNOWE ZALEŻNOŚCI (cause→effect z konkurencji) ═══"]
        for t in triplet_list:
            if isinstance(t, dict):
                cause = t.get("cause", t.get("subject", ""))
                effect = t.get("effect", t.get("object", ""))
                lines.append(f"  • {cause} → {effect}")
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

    fast_note = "Tryb fast: max 3 sekcje + FAQ." if mode == "fast" else "Typowo 5-10 sekcji — tyle ile wymaga temat."
    h2_hint_rule = ("Uwzględnij frazy H2 użytkownika w nagłówkach, o ile brzmią naturalnie."
                    if user_h2_hints else "Dobierz nagłówki na podstawie S1 i luk treściowych.")

    sections.append(f"""═══ ZASADY ═══

1. LICZBA H2 wynika z analizy — ile sekcji potrzeba, by wyczerpująco pokryć temat. {fast_note}
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
