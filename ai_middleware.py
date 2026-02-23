"""
AI Middleware for BRAJEN SEO v48.0
==================================
ONE Claude Sonnet call cleans ALL S1 data fields.

Claude understands the topic and decides what's relevant — no blacklists needed.
Regex stays ONLY as offline fallback when API unavailable.

Primary output: TOPICAL entities (concepts: "stan nietrzeźwości", "promile")
Secondary output: NAMED entities filtered for relevance ("Sąd Najwyższy", "SAOS")

Cost: ~$0.03 per S1 cleanup call (Sonnet). One call replaces 220 regex rules.

ARCHITECTURE:
  N-gram API → S1 raw data → [Claude Sonnet: "co tu jest wartościowe?"] → clean data → Opus
"""

import os
import json
import logging
import re

import anthropic

logger = logging.getLogger(__name__)

MIDDLEWARE_MODEL = os.environ.get("MIDDLEWARE_MODEL", "claude-haiku-4-5-20251001")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


# ================================================================
# 1. MAIN: ONE CALL CLEANS EVERYTHING
# ================================================================

S1_CLEANUP_PROMPT = """Jesteś ekspertem SEO. Dostajesz surowe dane z analizy SERP dla artykułu.
Dane mogą zawierać śmieci z CSS/HTML/nawigacji stron — odfiltruj je.

TEMAT ARTYKUŁU: "{keyword}"

SUROWE DANE:
{raw_data}

ZADANIE — zwróć TYLKO JSON:
{{
  "topical_entities": ["lista 5-12 POJĘĆ TEMATYCZNYCH kluczowych dla tematu — nie nazwy własne, ale koncepty, terminy, zjawiska"],
  "named_entities": ["lista 0-8 NAZW WŁASNYCH powiązanych z tematem — instytucje, osoby, miejsca, akty prawne"],
  "clean_ngrams": ["lista 5-15 fraz kluczowych z n-gramów — TYLKO związane z tematem"],
  "clean_h2_patterns": ["lista H2 nagłówków z konkurencji — TYLKO merytoryczne, bez nawigacji"],
  "clean_salience": ["lista encji z salience — TYLKO merytoryczne"],
  "clean_cooccurrence": ["lista par encji jako 'encja1 + encja2' — TYLKO merytoryczne pary"],
  "clean_keyphrases": ["lista 3-8 keyphrases — TYLKO związane z tematem"],
  "garbage_summary": "krótko: ile i jakie śmieci znalazłeś (CSS, nawigacja, fonty...)"
}}

REGUŁY:
1. TOPICAL ENTITIES = pojęcia, koncepty, terminy — np. "stan nietrzeźwości", "promile", "zakaz prowadzenia pojazdów". To GŁÓWNE encje artykułu.
2. NAMED ENTITIES = nazwy własne powiązane z tematem — np. "Sąd Najwyższy", "Kodeks karny". Odrzuć: fonty (Menlo, Arial), frameworki, marki niezwiązane.
3. Odrzuć WSZYSTKO co wygląda jak CSS/HTML: inherit;color, section{{display, block cover, flex wrap, border, padding, margin, font-family.
4. Odrzuć NAWIGACJĘ stron: wyszukiwarka, nawigacja, mapa serwisu, newsletter, logowanie, cookie, footer, sidebar.
5. Odrzuć NAZWY FONTÓW: Menlo, Monaco, Consolas, Arial, Helvetica, Roboto, etc.
6. W H2: zachowaj tylko nagłówki opisujące sekcje artykułu. Odrzuć: "Szukaj", "Menu główne", "Biuletyn Informacji Publicznej".
7. W cooccurrence: zachowaj pary gdzie OBA elementy są merytoryczne.
8. Zwracaj wartości tekstowe (stringi), nie obiekty."""


def _extract_text(item):
    """Extract text value from entity dict or string."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return (item.get("entity") or item.get("text") or item.get("name")
                or item.get("ngram") or item.get("phrase") or item.get("pattern")
                or item.get("h2") or "")
    return str(item)


def _extract_pair_text(pair):
    """Extract text from a cooccurrence pair."""
    if isinstance(pair, dict):
        e1 = pair.get("entity_1", pair.get("entity1", ""))
        e2 = pair.get("entity_2", pair.get("entity2", ""))
        if isinstance(e1, list) and len(e1) >= 2:
            return f"{e1[0]} + {e1[1]}"
        return f"{e1} + {e2}"
    if isinstance(pair, str):
        return pair
    return str(pair)


def _build_raw_data_summary(s1_data: dict) -> str:
    """Build a condensed text summary of all S1 data for Claude to clean."""
    parts = []
    entity_seo = s1_data.get("entity_seo") or {}

    # 1. Entities (NER)
    raw_ents = entity_seo.get("top_entities", entity_seo.get("entities", []))[:25]
    if raw_ents:
        ent_texts = [_extract_text(e) for e in raw_ents if _extract_text(e)]
        parts.append(f"ENCJE NER ({len(ent_texts)}): {', '.join(ent_texts)}")

    # 2. Concept entities
    concept_ents = entity_seo.get("concept_entities", []) or s1_data.get("concept_entities", [])
    if concept_ents:
        ce_texts = [_extract_text(e) for e in concept_ents[:20] if _extract_text(e)]
        parts.append(f"ENCJE KONCEPTOWE ({len(ce_texts)}): {', '.join(ce_texts)}")

    # 3. N-grams
    raw_ngrams = (s1_data.get("ngrams") or s1_data.get("hybrid_ngrams") or [])[:30]
    if raw_ngrams:
        ng_texts = [_extract_text(n) for n in raw_ngrams if _extract_text(n)]
        parts.append(f"N-GRAMY ({len(ng_texts)}): {', '.join(ng_texts)}")

    # 4. Entity salience
    raw_sal = entity_seo.get("entity_salience", []) or s1_data.get("entity_salience", [])
    if raw_sal:
        sal_texts = [_extract_text(e) for e in raw_sal[:20] if _extract_text(e)]
        parts.append(f"SALIENCE ({len(sal_texts)}): {', '.join(sal_texts)}")

    # 5. Co-occurrence
    raw_cooc = (entity_seo.get("entity_cooccurrence", [])
                or entity_seo.get("cooccurrence", [])
                or s1_data.get("entity_cooccurrence", []))
    if raw_cooc:
        cooc_texts = [_extract_pair_text(p) for p in raw_cooc[:15]]
        parts.append(f"CO-OCCURRENCE ({len(cooc_texts)}): {', '.join(cooc_texts)}")

    # 6. H2 patterns
    raw_h2 = s1_data.get("competitor_h2_patterns", [])
    if not raw_h2:
        raw_h2 = (s1_data.get("serp_analysis") or {}).get("competitor_h2_patterns", [])
    if raw_h2:
        h2_texts = [_extract_text(h) for h in raw_h2[:25] if _extract_text(h)]
        parts.append(f"H2 PATTERNS ({len(h2_texts)}): {', '.join(h2_texts)}")

    # 7. Semantic keyphrases
    raw_kp = s1_data.get("semantic_keyphrases", [])
    if raw_kp:
        kp_texts = [_extract_text(k) for k in raw_kp[:15] if _extract_text(k)]
        parts.append(f"KEYPHRASES ({len(kp_texts)}): {', '.join(kp_texts)}")

    # 8. Topical coverage
    raw_tc = entity_seo.get("topical_coverage", [])
    if raw_tc:
        tc_texts = [_extract_text(t) for t in raw_tc[:15] if _extract_text(t)]
        parts.append(f"TOPICAL COVERAGE ({len(tc_texts)}): {', '.join(tc_texts)}")

    # 9. Placement instruction (just first 300 chars)
    sem_hints = s1_data.get("semantic_enhancement_hints") or {}
    placement = sem_hints.get("placement_instruction", "")
    if not placement:
        ep = entity_seo.get("entity_placement", {})
        if isinstance(ep, dict):
            placement = ep.get("placement_instruction", "")
    if placement:
        parts.append(f"PLACEMENT INSTRUCTION: {placement[:300]}")

    # 10. Must-cover concepts
    must_cover = sem_hints.get("must_cover_concepts", [])
    if not must_cover:
        ts = entity_seo.get("topical_summary", {})
        if isinstance(ts, dict):
            must_cover = ts.get("must_cover", [])
    if must_cover:
        mc_texts = [_extract_text(m) for m in must_cover[:10] if _extract_text(m)]
        parts.append(f"MUST COVER ({len(mc_texts)}): {', '.join(mc_texts)}")

    # 11. Causal triplets
    causal = s1_data.get("causal_triplets", {})
    chains = causal.get("chains", [])[:8]
    singles = causal.get("singles", [])[:8]
    causal_all = chains + singles
    if causal_all:
        ct_texts = []
        for c in causal_all:
            cause = c.get("cause", c.get("from", ""))
            effect = c.get("effect", c.get("to", ""))
            if cause and effect:
                ct_texts.append(f"{cause} → {effect}")
        if ct_texts:
            parts.append(f"CAUSAL ({len(ct_texts)}): {', '.join(ct_texts)}")

    return "\n".join(parts)


def ai_clean_s1_complete(s1_data: dict, main_keyword: str) -> dict:
    """
    ONE Claude Sonnet call to clean ALL S1 data.
    
    Claude sees the raw data and decides what's topically relevant.
    Returns enriched s1_data with:
    - _ai_topical_entities: concept entities (PRIMARY)
    - _ai_named_entities: filtered NER entities (SECONDARY)
    - All lists cleaned: ngrams, salience, h2_patterns, cooccurrence, etc.
    - _cleanup_stats: what was removed
    
    Falls back to regex if Claude unavailable.
    """
    if not s1_data:
        return s1_data

    raw_summary = _build_raw_data_summary(s1_data)

    if not raw_summary.strip():
        logger.info("[AI_MW] No S1 data to clean")
        return s1_data

    if not ANTHROPIC_API_KEY:
        logger.warning("[AI_MW] No API key — using regex fallback")
        return _regex_fallback_clean(s1_data, main_keyword)

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        prompt = S1_CLEANUP_PROMPT.format(
            keyword=main_keyword,
            raw_data=raw_summary
        )

        response = client.messages.create(
            model=MIDDLEWARE_MODEL,
            max_tokens=1500,
            temperature=0,
            messages=[{"role": "user", "content": prompt}]
        )

        raw_text = response.content[0].text.strip()
        json_match = re.search(r'\{[\s\S]*\}', raw_text)
        if not json_match:
            logger.warning(f"[AI_MW] No JSON in Claude response, fallback to regex")
            return _regex_fallback_clean(s1_data, main_keyword)

        clean = json.loads(json_match.group())
        logger.info(f"[AI_MW] ✅ Claude cleanup: "
                     f"{len(clean.get('topical_entities', []))} topical, "
                     f"{len(clean.get('named_entities', []))} NER, "
                     f"{len(clean.get('clean_ngrams', []))} ngrams, "
                     f"{len(clean.get('clean_h2_patterns', []))} H2 | "
                     f"{clean.get('garbage_summary', '')[:80]}")

        return _apply_clean_data(s1_data, clean, main_keyword)

    except Exception as e:
        logger.error(f"[AI_MW] Claude cleanup FAILED — {type(e).__name__}: {e}")
        return _regex_fallback_clean(s1_data, main_keyword)


def _apply_clean_data(s1_data: dict, clean: dict, main_keyword: str) -> dict:
    """Apply Claude's clean output back into s1_data structure."""
    result = dict(s1_data)
    entity_seo = dict(result.get("entity_seo") or {})

    topical = clean.get("topical_entities", [])
    named = clean.get("named_entities", [])
    clean_ngrams_list = clean.get("clean_ngrams", [])
    clean_h2 = clean.get("clean_h2_patterns", [])
    clean_sal = clean.get("clean_salience", [])
    clean_cooc = clean.get("clean_cooccurrence", [])
    clean_kp = clean.get("clean_keyphrases", [])
    garbage_summary = clean.get("garbage_summary", "")

    # ── TOPICAL ENTITIES as primary ──
    topical_dicts = [{"text": t, "type": "TOPICAL", "source": "ai_cleanup"} for t in topical if isinstance(t, str)]
    named_dicts = [{"text": n, "type": "NAMED", "source": "ai_cleanup"} for n in named if isinstance(n, str)]

    entity_seo["concept_entities"] = topical_dicts
    entity_seo["ai_topical_entities"] = topical_dicts
    entity_seo["ai_named_entities"] = named_dicts

    # ── TOP_ENTITIES: topical first, then named ──
    combined = topical_dicts + named_dicts
    entity_seo["top_entities"] = combined[:15]
    entity_seo["must_mention_entities"] = topical_dicts[:5]

    # ── ENTITY SALIENCE: filter by Claude's clean list ──
    if clean_sal:
        clean_sal_set = {s.lower() for s in clean_sal}
        raw_sal = entity_seo.get("entity_salience", []) or result.get("entity_salience", [])
        filtered_sal = [e for e in raw_sal if _extract_text(e).lower() in clean_sal_set]
        existing_texts = {_extract_text(e).lower() for e in filtered_sal}
        for sal_text in clean_sal:
            if sal_text.lower() not in existing_texts:
                filtered_sal.append({"entity": sal_text, "salience": 0.5, "source": "ai_inferred"})
        entity_seo["entity_salience"] = filtered_sal
        if "entity_salience" in result:
            result["entity_salience"] = filtered_sal

    # ── CO-OCCURRENCE: filter by Claude's clean list ──
    if clean_cooc:
        clean_cooc_set = {c.lower() for c in clean_cooc}
        raw_cooc = (entity_seo.get("entity_cooccurrence", [])
                    or entity_seo.get("cooccurrence", [])
                    or result.get("entity_cooccurrence", []))
        filtered_cooc = [p for p in raw_cooc if _extract_pair_text(p).lower() in clean_cooc_set]
        for cooc_key in ("entity_cooccurrence", "cooccurrence"):
            if cooc_key in entity_seo:
                entity_seo[cooc_key] = filtered_cooc
        if "entity_cooccurrence" in result:
            result["entity_cooccurrence"] = filtered_cooc

    # ── N-GRAMS: filter by Claude's clean list ──
    if clean_ngrams_list:
        clean_ng_set = {n.lower() for n in clean_ngrams_list}
        raw_ng = result.get("ngrams") or result.get("hybrid_ngrams") or []
        filtered_ng = [n for n in raw_ng if _extract_text(n).lower() in clean_ng_set]
        existing_ng = {_extract_text(n).lower() for n in filtered_ng}
        for ng_text in clean_ngrams_list:
            if ng_text.lower() not in existing_ng:
                filtered_ng.append({"ngram": ng_text, "source": "ai_inferred"})
        result["ngrams"] = filtered_ng

    # ── H2 PATTERNS: filter by Claude's clean list ──
    if clean_h2:
        clean_h2_set = {h.lower() for h in clean_h2}
        raw_h2_list = result.get("competitor_h2_patterns", [])
        filtered_h2 = [h for h in raw_h2_list if _extract_text(h).lower() in clean_h2_set]
        existing_h2 = {_extract_text(h).lower() for h in filtered_h2}
        for h2_text in clean_h2:
            if h2_text.lower() not in existing_h2:
                filtered_h2.append(h2_text)
        result["competitor_h2_patterns"] = filtered_h2

    # ── SEMANTIC KEYPHRASES: filter (v57.1: fuzzy match) ──
    # Claude returns clean_keyphrases as strings, TF-IDF returns dicts with
    # "phrase" key. Exact match rarely works → use substring containment.
    if clean_kp:
        clean_kp_set = {k.lower() for k in clean_kp}
        raw_kp = result.get("semantic_keyphrases", [])
        filtered_kp = []
        for k in raw_kp:
            kp_text = _extract_text(k).lower()
            # Match if TF-IDF phrase is contained in Claude's phrase or vice versa
            if any(kp_text in ckp or ckp in kp_text for ckp in clean_kp_set):
                filtered_kp.append(k)
        # v57.1: If Claude's filtering killed everything, fall back to raw
        # (let _regex_filter_list handle garbage removal downstream)
        if not filtered_kp and raw_kp:
            result["semantic_keyphrases"] = raw_kp
        else:
            result["semantic_keyphrases"] = filtered_kp

    # ── TOPICAL COVERAGE: rebuild from Claude's entities ──
    entity_seo["topical_coverage"] = [
        {"entity": t, "importance": "HIGH"} for t in topical[:8]
    ] + [
        {"entity": n, "importance": "MEDIUM"} for n in named[:5]
    ]

    # ── CAUSAL TRIPLETS: filter ──
    causal = result.get("causal_triplets", {})
    if causal:
        all_clean_texts = {t.lower() for t in topical + named + clean_sal + clean_ngrams_list}
        for key in ("chains", "singles"):
            raw_items = causal.get(key, [])
            clean_items = []
            for item in raw_items:
                cause = item.get("cause", item.get("from", ""))
                effect = item.get("effect", item.get("to", ""))
                # Keep if both cause/effect have words in common with clean entities
                cause_words = set(cause.lower().split())
                effect_words = set(effect.lower().split())
                cause_relevant = any(w in all_clean_texts or any(w in ct for ct in all_clean_texts) for w in cause_words if len(w) > 3)
                effect_relevant = any(w in all_clean_texts or any(w in ct for ct in all_clean_texts) for w in effect_words if len(w) > 3)
                if cause_relevant and effect_relevant and len(cause) > 5 and len(effect) > 5:
                    clean_items.append(item)
            causal[key] = clean_items
        result["causal_triplets"] = causal

    # ── SEMANTIC ENHANCEMENT HINTS: rebuild with clean data ──
    sem_hints = result.get("semantic_enhancement_hints") or {}
    if sem_hints:
        sem_hints["first_paragraph_entities"] = topical[:5]
        sem_hints["h2_entities"] = topical[:8]
        sem_hints["must_cover_concepts"] = topical[:10]
        if clean_cooc:
            sem_hints["cooccurrence_pairs"] = [{"pair": c} for c in clean_cooc[:5]]
        result["semantic_enhancement_hints"] = sem_hints

    # ── TOPICAL SUMMARY: rebuild ──
    ts = entity_seo.get("topical_summary", {})
    if not isinstance(ts, dict):
        ts = {}
    ts["must_cover"] = topical[:8]
    ts["should_cover"] = named[:5]
    entity_seo["topical_summary"] = ts

    result["entity_seo"] = entity_seo

    # ── CLEANUP STATS ──
    result["_cleanup_stats"] = {
        "method": "claude_sonnet",
        "topical_entities_count": len(topical),
        "named_entities_count": len(named),
        "clean_ngrams_count": len(clean_ngrams_list),
        "clean_h2_count": len(clean_h2),
        "garbage_summary": garbage_summary,
    }

    # ── AI PANEL DATA (for dashboard) ──
    result["_ai_entity_panel"] = {
        "topical_entities": topical,
        "named_entities": named,
        "clean_ngrams": clean_ngrams_list,
        "clean_h2_patterns": clean_h2,
        "clean_salience": clean_sal,
        "clean_cooccurrence": clean_cooc,
        "garbage_summary": garbage_summary,
        "method": "claude_sonnet",
    }

    return result


# ================================================================
# REGEX FALLBACK — when Claude unavailable
# ================================================================

_CSS_JS_PATTERNS = re.compile(
    r'(?:'
    r'webkit|moz-|ms-flex|display\s*:|padding|margin|'
    r'font-family|background|border|text-shadow|transform|'
    r'transition|overflow|z-index|opacity|position\s*:|'
    r'\.uk-|\.et_pb_|var\s*\(|calc\s*\(|'
    r'rgba?\s*\(|#[0-9a-f]{3,8}\b|'
    r'\{\s*\}|;\s*\}|:\s*\{|'
    r'@media|@import|@keyframe|'
    r'function\s*\(|=>\s*\{|console\.|document\.|window\.|'
    r'addEventListener|querySelector|innerHTML|className|'
    r'data-[a-z]+=|aria-[a-z]+=|role=|tabindex|'
    r'cookie|localStorage|sessionStorage|'
    r'async\s+function|await\s+|promise|fetch\(|'
    r'import\s+\{|export\s+(default|const)|require\(|'
    r'\w+__\w+|\w+--\w+|'
    r'focus-visible|,#|\.css|'
    r'\bvar\s+wp\b|wp-block|wp-embed|'
    r'block\s*embed|content\s*block|text\s*block|input\s*type|'
    r'^(header|footer|sidebar|nav|mega)\s*-?\s*menu$|'
    r'^sub-?\s*menu$|^mega\s+menu$'
    r')',
    re.IGNORECASE
)

_GARBAGE_WORDS = {
    "buttons", "meta", "cookie", "inline", "block",
    "default", "active", "hover", "flex", "grid", "none",
    "inherit", "auto", "hidden", "visible", "relative",
    "absolute", "fixed", "static", "center", "wrap",
    "bold", "normal", "italic", "transparent", "solid",
    "pointer", "disabled", "checked", "focus", "root",
    "ast", "var", "global", "color", "sich", "un", "uw",
    "menu", "submenu", "sidebar", "footer", "header", "widget",
    "navbar", "dropdown", "modal", "tooltip", "carousel",
    "accordion", "breadcrumb", "pagination", "thumbnail",
    "menlo", "monaco", "consolas", "courier", "arial", "helvetica",
    "verdana", "georgia", "roboto", "poppins", "raleway",
}

_NAV_TERMS = {
    "wyszukiwarka", "nawigacja", "moje strony", "mapa serwisu",
    "biuletyn informacji publicznej", "redakcja serwisu", "dostępność",
    "nota prawna", "polityka prywatności", "regulamin",
    "newsletter", "social media", "archiwum", "logowanie",
    "rejestracja", "mapa strony", "komenda miejska",
    "komenda powiatowa", "deklaracja dostępności",
}


def _is_garbage_regex(text: str) -> bool:
    """Regex-only garbage check — FALLBACK when Claude unavailable."""
    if not text or not isinstance(text, str):
        return True
    text = text.strip()
    if len(text) < 2:
        return True
    special = sum(1 for c in text if c in '{}:;()[]<>=#.@\\')
    if len(text) > 0 and special / len(text) > 0.12:
        return True
    t_lower = text.lower().strip()
    if t_lower in _GARBAGE_WORDS:
        return True
    if t_lower in _NAV_TERMS:
        return True
    for nav in _NAV_TERMS:
        if nav in t_lower and len(nav) >= 8:
            return True
    if _CSS_JS_PATTERNS.search(text):
        return True
    # CSS compound tokens
    if re.match(r'^[\w-]+[;{}\[\]:]+[\w-]+$', t_lower):
        return True
    # Multi-word all CSS
    words = t_lower.split()
    if len(words) >= 2:
        css_all = {"block", "inline", "flex", "grid", "auto", "none", "center",
                   "wrap", "bold", "hidden", "visible", "absolute", "relative",
                   "image", "color", "width", "height", "size", "style", "type",
                   "var", "min", "max", "dim", "cover", "inherit", "font",
                   "serif", "sans", "border", "margin", "padding", "display",
                   "strong", "section", "link", "list", "table", "column",
                   "row", "form", "embed", "widget", "footer", "sidebar",
                   "header", "nav", "menu", "sub", "mega", "wp", "template",
                   "page", "item", "text", "content", "post", "input",
                   # v49: CSS variable tokens from SERP scraping
                   "ast", "global", "color", "root", "utf", "responsive",
                   "button", "card", "wrapper", "inner", "outer"}
        if all(w in css_all for w in words):
            return True
    return False


def _regex_filter_list(items: list) -> list:
    """Filter a list of entities/ngrams using regex."""
    if not items:
        return []
    clean = []
    for item in items:
        text = _extract_text(item)
        if text and not _is_garbage_regex(text):
            clean.append(item)
    return clean


def _regex_filter_cooccurrence(pairs: list) -> list:
    if not pairs:
        return []
    clean = []
    for pair in pairs:
        text = _extract_pair_text(pair)
        parts = text.split(" + ")
        if len(parts) == 2 and not _is_garbage_regex(parts[0]) and not _is_garbage_regex(parts[1]):
            clean.append(pair)
        elif not _is_garbage_regex(text):
            clean.append(pair)
    return clean


def _regex_fallback_clean(s1_data: dict, main_keyword: str) -> dict:
    """Regex-only S1 cleaning — used when Claude unavailable."""
    result = dict(s1_data)
    entity_seo = dict(result.get("entity_seo") or {})

    total_before = 0
    total_after = 0

    for key in ("top_entities", "entities", "entity_salience", "concept_entities",
                "must_mention_entities"):
        if key in entity_seo:
            before = len(entity_seo[key])
            entity_seo[key] = _regex_filter_list(entity_seo[key])
            total_before += before
            total_after += len(entity_seo[key])

    for key in ("entity_cooccurrence", "cooccurrence"):
        if key in entity_seo:
            entity_seo[key] = _regex_filter_cooccurrence(entity_seo[key])

    if "topical_coverage" in entity_seo:
        entity_seo["topical_coverage"] = _regex_filter_list(entity_seo["topical_coverage"])

    # v49: Clean H2 patterns in BOTH locations
    if "competitor_h2_patterns" in result:
        result["competitor_h2_patterns"] = _regex_filter_list(result["competitor_h2_patterns"])
    serp = result.get("serp_analysis")
    if isinstance(serp, dict) and "competitor_h2_patterns" in serp:
        serp["competitor_h2_patterns"] = _regex_filter_list(serp["competitor_h2_patterns"])

    for key in ("ngrams", "hybrid_ngrams"):
        if key in result:
            before = len(result[key])
            result[key] = _regex_filter_list(result[key])
            total_before += before
            total_after += len(result[key])

    if "semantic_keyphrases" in result:
        result["semantic_keyphrases"] = _regex_filter_list(result["semantic_keyphrases"])

    if "entity_salience" in result:
        result["entity_salience"] = _regex_filter_list(result["entity_salience"])

    # v49: Clean placement instruction — remove CSS garbage entities
    placement = entity_seo.get("entity_placement", {})
    if isinstance(placement, dict):
        for lk in ("first_paragraph_entities", "h2_entities"):
            if lk in placement:
                placement[lk] = _regex_filter_list(placement[lk])
        if "cooccurrence_pairs" in placement:
            placement["cooccurrence_pairs"] = _regex_filter_cooccurrence(placement["cooccurrence_pairs"])
        # v49: Fix primary entity — if it's CSS garbage, replace with keyword
        primary = placement.get("primary_entity", "")
        if isinstance(primary, dict):
            primary_text = primary.get("entity", primary.get("name", ""))
        else:
            primary_text = str(primary)
        if _is_garbage_regex(primary_text):
            placement["primary_entity"] = main_keyword
            placement["placement_instruction"] = (
                f"🎯 ENCJA GŁÓWNA: \"{main_keyword}\"\n"
                f"   → MUSI być w tytule H1 i w pierwszym zdaniu artykułu"
            )

    sem = result.get("semantic_enhancement_hints") or {}
    if sem:
        for lk in ("first_paragraph_entities", "h2_entities", "must_cover_concepts"):
            if lk in sem:
                sem[lk] = _regex_filter_list(sem[lk])
        if "cooccurrence_pairs" in sem:
            sem["cooccurrence_pairs"] = _regex_filter_cooccurrence(sem["cooccurrence_pairs"])
        # v49: Clean placement_instruction text
        pi = sem.get("placement_instruction", "")
        if isinstance(pi, str) and _is_garbage_regex(pi.split('"')[1] if '"' in pi else pi[:30]):
            sem["placement_instruction"] = ""
        result["semantic_enhancement_hints"] = sem

    ts = entity_seo.get("topical_summary", {})
    if isinstance(ts, dict):
        for lk in ("must_cover", "should_cover", "topics"):
            if lk in ts:
                ts[lk] = _regex_filter_list(ts[lk])

    # v49: Generate topical entities from concept_entities (regex can't classify, but can promote)
    concept_ents = entity_seo.get("concept_entities", [])
    clean_concepts = _regex_filter_list(concept_ents)
    # Build topical entity dicts from clean concepts
    topical_dicts = []
    for c in clean_concepts[:12]:
        text = _extract_text(c)
        if text and len(text) > 2:
            topical_dicts.append({"entity": text, "type": "TOPICAL", "source": "concept_entities"})
    if topical_dicts:
        entity_seo["ai_topical_entities"] = topical_dicts
        entity_seo["ai_named_entities"] = []  # Can't distinguish in regex mode

    result["entity_seo"] = entity_seo
    removed = total_before - total_after
    result["_cleanup_stats"] = {
        "method": "regex_fallback",
        "items_removed": removed,
        "garbage_ratio": round(removed / max(total_before, 1), 2),
    }
    result["_ai_entity_panel"] = {
        "topical_entities": [_extract_text(t) for t in topical_dicts[:12]],
        "named_entities": [],
        "clean_ngrams": [_extract_text(n) for n in (result.get("ngrams") or [])[:15]],
        "garbage_summary": f"Regex fallback: {removed} items removed",
        "method": "regex_fallback",
    }
    logger.info(f"[AI_MW] Regex fallback cleanup: removed {removed}/{total_before} items, {len(topical_dicts)} topical entities from concepts")
    return result


# ================================================================
# 2. SMART RETRY — batch text rewriting
# ================================================================

def smart_retry_batch(original_text, exceeded_keywords, pre_batch, h2, batch_type="CONTENT", attempt_num=1):
    if not exceeded_keywords or not ANTHROPIC_API_KEY:
        return original_text
    replacements = []
    for exc in exceeded_keywords:
        kw = exc.get("keyword", "")
        synonyms = exc.get("use_instead") or exc.get("synonyms") or []
        severity = exc.get("severity", "WARNING")
        if not kw:
            continue
        syn_list = [s if isinstance(s, str) else str(s) for s in synonyms[:3]] if synonyms else []
        replacements.append({"keyword": kw, "synonyms": syn_list, "severity": severity})
    if not replacements:
        return original_text
    stop_kw = (pre_batch.get("keyword_limits") or {}).get("stop_keywords", [])
    stop_kw_names = [kw.get("keyword", kw) if isinstance(kw, dict) else str(kw) for kw in stop_kw[:10]]

    replacement_instructions = []
    for r in replacements:
        if r["synonyms"]:
            syn_str = ", ".join(f'"{s}"' for s in r["synonyms"])
            replacement_instructions.append(
                f'  - "{r["keyword"]}" [{r["severity"]}] → zamień na: {syn_str}'
            )
        else:
            replacement_instructions.append(
                f'  - "{r["keyword"]}" [{r["severity"]}] → użyj synonimów / omów inaczej'
            )
    replacement_text = "\n".join(replacement_instructions)
    stop_text = ", ".join(f'"{s}"' for s in stop_kw_names[:5]) if stop_kw_names else "(brak)"
    main_kw = pre_batch.get("main_keyword", "")

    prompt = f"""Przepisz poniższy tekst sekcji artykułu SEO.

PROBLEM: Tekst przekracza limity niektórych słów kluczowych.
SEKCJA: {h2} ({batch_type})
GŁÓWNE SŁOWO KLUCZOWE (NIE ZMIENIAJ): {main_kw}

NADMIAROWE SŁOWA KLUCZOWE — zamień na synonimy:
{replacement_text}

SŁOWA STOP (NIGDY NIE DODAWAJ):
{stop_text}

ZASADY:
1. Zachowaj DOKŁADNIE tę samą strukturę HTML (H2, H3, p, ul, li)
2. Zachowaj DOKŁADNIE tę samą długość (±10%)
3. Zachowaj merytorykę i styl
4. Zamień TYLKO nadmiarowe słowa — resztę zostaw
5. NIE dodawaj nowych wystąpień słowa kluczowego "{main_kw}"
6. Odpowiedz TYLKO przepisanym HTML, bez komentarzy

TEKST DO PRZEPISANIA:
{original_text}"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=MIDDLEWARE_MODEL, max_tokens=4000, temperature=0.3,
            messages=[{"role": "user", "content": prompt}]
        )
        rewritten = response.content[0].text.strip()
        if rewritten.startswith("```"):
            rewritten = re.sub(r'^```(?:html)?\s*\n?', '', rewritten)
            rewritten = re.sub(r'\n?```\s*$', '', rewritten)
        if len(rewritten) < len(original_text) * 0.5:
            logger.warning("[AI_MW] Rewritten text too short, keeping original")
            return original_text
        for r in replacements:
            kw_lower = r["keyword"].lower()
            old_count = original_text.lower().count(kw_lower)
            new_count = rewritten.lower().count(kw_lower)
            if new_count < old_count:
                logger.info(f"[AI_MW] Smart retry: '{r['keyword']}' {old_count} → {new_count}")
        return rewritten
    except Exception as e:
        logger.warning(f"[AI_MW] Smart retry failed: {e}")
        return original_text


# ================================================================
# 3. ARTICLE MEMORY — inter-batch context
# ================================================================

def synthesize_article_memory(accepted_batches: list) -> dict:
    """Simple (non-AI) article memory — extracts topics covered from accepted batches."""
    if not accepted_batches:
        return {}
    topics = []
    total_words = 0
    for batch in accepted_batches:
        h2 = batch.get("h2", "")
        if h2:
            topics.append(h2)
        text = batch.get("text", "")
        total_words += len(text.split())
    return {
        "topics_covered": topics,
        "total_words": total_words,
        "batch_count": len(accepted_batches),
    }


def ai_synthesize_memory(accepted_batches: list, main_keyword: str) -> dict:
    """AI-powered article memory — Claude summarizes what's been written so far.
    v50.5 FIX 30: Enhanced to extract specific definitions, formulas, and facts
    that must NOT be repeated in subsequent batches.
    v52.1 FIX: Added phrases_used tracking + explicit anti-repetition for exact phrases.
    The key change: phrases that were overused go into phrases_used (which triggers
    a "ogranicz" warning in the prompt), NOT into key_points (which GPT treats as
    a recipe to repeat)."""
    if not accepted_batches or not ANTHROPIC_API_KEY:
        return synthesize_article_memory(accepted_batches)

    batch_summaries = []
    for i, batch in enumerate(accepted_batches[-6:], 1):
        h2 = batch.get("h2", "Bez nagłówka")
        text = batch.get("text", "")[:500]
        batch_summaries.append(f"Sekcja {i}: [{h2}] {text}...")

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=MIDDLEWARE_MODEL, max_tokens=700, temperature=0,
            messages=[{"role": "user", "content": (
                f'Artykuł o: "{main_keyword}"\n\n'
                f'Dotychczas napisane sekcje:\n' + "\n".join(batch_summaries) + "\n\n"
                f'Przeanalizuj tekst i zwróć JSON z:\n'
                f'1. topics_covered: lista tematów/sekcji już omówionych\n'
                f'2. key_points: TYLKO unikalne fakty, liczby i definicje PIERWSZEGO WYSTĄPIENIA '
                f'(np. "mosiądz = odporny na uszkodzenia", "rozstaw: odległość między śrubami"). '
                f'WAŻNE: NIE wpisuj tu zdań które powtarzają się wielokrotnie — te idą do phrases_used!\n'
                f'3. avoid_repetition: konkretne ZDANIA i SFORMUŁOWANIA które pojawiły się 2+ razy '
                f'i NIE MOGĄ być użyte ponownie dosłownie '
                f'(np. "mosiądz gwarantuje odporność na uszkodzenia i długowieczność", '
                f'"odświeżenie wnętrza nie zawsze wymaga gruntownych remontów")\n'
                f'4. phrases_used: słownik {{fraza: liczba_użyć}} dla fraz które były użyte 3+ razy '
                f'(to ostrzega kolejne batche żeby nie przesadzać)\n'
                f'5. entities_defined: lista pojęć/encji już wprowadzonych w tekście\n'
                f'6. total_words: {sum(len(b.get("text","").split()) for b in accepted_batches)}\n\n'
                f'Zwróć TYLKO JSON, bez komentarzy.'
            )}]
        )
        text = response.content[0].text.strip()
        # Try direct parse first (most reliable)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try extracting JSON object with non-greedy match to avoid grabbing too much
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        # Last resort: greedy match with cleanup
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            raw = json_match.group()
            # Fix common JSON issues: trailing commas before } or ]
            raw = re.sub(r',\s*([}\]])', r'\1', raw)
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
    except Exception as e:
        logger.warning(f"[AI_MW] AI memory synthesis failed: {e}")

    return synthesize_article_memory(accepted_batches)
def smart_retry_per_sentence(text: str, exceeded_keywords: list, attempt_num: int = 1) -> str:
    """
    v45.3: Per-sentence smart retry — chirurgiczny fix jednego zdania zamiast całego batcha.

    Podejście:
    1. Znajdź zdania zawierające przekroczoną frazę
    2. Wyślij TYLKO to zdanie + kontekst ±1 do Haiku z prośbą o rewrite
    3. Zastąp w oryginale

    Tańsze (~$0.002 vs $0.01), precyzyjniejsze, mniejsze ryzyko regresji.
    """
    if not exceeded_keywords or not ANTHROPIC_API_KEY:
        return text

    import re as _re_local
    sentences = _re_local.split(r'(?<=[.!?])\s+', text)
    if not sentences:
        return text

    modified = False
    for exc in exceeded_keywords[:3]:  # Max 3 keywords per retry
        kw = exc.get("keyword", "")
        synonyms = exc.get("use_instead") or exc.get("synonyms") or []
        kw_type = exc.get("type", "BASIC").upper()

        if not kw or kw_type == "ENTITY":
            continue

        syn_list = [s if isinstance(s, str) else str(s) for s in synonyms[:3]] if synonyms else []
        syn_str = ", ".join(f'"{s}"' for s in syn_list) if syn_list else "synonim lub przeformułowanie"

        # Znajdź zdania z tą frazą — weź OSTATNIE wystąpienie (bo early batches budżet zjadły)
        kw_lower = kw.lower()
        matching_indices = [i for i, s in enumerate(sentences) if kw_lower in s.lower()]

        if not matching_indices:
            continue

        # Weź ostatnie zdanie z frazą
        idx = matching_indices[-1]
        target_sent = sentences[idx]
        prev_sent = sentences[idx - 1] if idx > 0 else ""
        next_sent = sentences[idx + 1] if idx < len(sentences) - 1 else ""

        prompt = f"""Przepisz to zdanie tak, aby nie zawierało frazy "{kw}".
Użyj zamiast tego: {syn_str}.
Zachowaj identyczne znaczenie i długość (±3 słowa).
Zachowaj strukturę HTML (tagi p, ul, li itp.).

KONTEKST PRZED: "{prev_sent}"
ZDANIE DO PRZEPISANIA: "{target_sent}"
KONTEKST PO: "{next_sent}"

Odpowiedz TYLKO przepisanym zdaniem, bez komentarzy."""

        try:
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                temperature=0.2,
                messages=[{"role": "user", "content": prompt}]
            )
            rewritten = response.content[0].text.strip()

            # Sanity checks
            if len(rewritten) < len(target_sent) * 0.5 or len(rewritten) > len(target_sent) * 2:
                logger.warning(f"[SMART_RETRY_SENT] Rewritten too short/long, skipping '{kw}'")
                continue

            # Verify keyword was actually removed
            if kw_lower in rewritten.lower():
                logger.warning(f"[SMART_RETRY_SENT] Keyword still present after rewrite, skipping '{kw}'")
                continue

            sentences[idx] = rewritten
            modified = True
            logger.info(f"[SMART_RETRY_SENT] ✅ '{kw}' removed from sentence {idx+1}")
        except Exception as e:
            logger.warning(f"[SMART_RETRY_SENT] Failed for '{kw}': {e}")

    if modified:
        return " ".join(sentences)
    return text


def should_use_smart_retry(result: dict, attempt: int) -> bool:
    """Decide if smart retry is worth attempting."""
    if attempt > 3:
        return False
    if not ANTHROPIC_API_KEY:
        return False
    exceeded = result.get("exceeded_keywords", [])
    if not exceeded:
        return False
    critical = sum(1 for e in exceeded if e.get("severity") == "CRITICAL")
    if critical > 5:
        return False
    return True


# ================================================================
# ENTITY GAP ANALYSIS — identifies missing entities before writing
# ================================================================

ENTITY_GAP_PROMPT = """Jesteś ekspertem SEO i NLP. Analizujesz LUKI ENCYJNE (entity gaps) dla artykułu.

TEMAT ARTYKUŁU: "{keyword}"

ENCJE ZNALEZIONE U KONKURENCJI (z analizy S1):
{found_entities}

ZADANIE: Zidentyfikuj encje, które POWINNY być w artykule o "{keyword}", ale BRAKUJE ich w danych z konkurencji.
Szukaj luk w kategoriach:
1. Powiązane pojęcia medyczne/prawne/techniczne
2. Przyczyny i skutki
3. Instytucje, osoby, miejsca
4. Procesy, metody, narzędzia
5. Synonimy i pojęcia nadrzędne/podrzędne

Zwróć TYLKO JSON:
{{
  "entity_gaps": [
    {{"entity": "nazwa encji", "why": "dlaczego powinna być w artykule", "priority": "high/medium/low"}}
  ]
}}

REGUŁY:
- Max 12 luk encyjnych
- Priorytet "high" = kluczowe dla topical authority, "medium" = wzbogacające, "low" = opcjonalne
- NIE powtarzaj encji już znalezionych
- Encje muszą być MERYTORYCZNE (nie CSS, nawigacja, marki)
- Podaj krótki powód (max 15 słów) dlaczego encja jest potrzebna"""


def analyze_entity_gaps(main_keyword: str, found_entities: list) -> list:
    """
    Analyze entity gaps — what entities SHOULD be in the article but are missing.
    Uses Claude Haiku for fast, cheap analysis.

    Returns list of entity gaps:
      [{"entity": "...", "why": "...", "priority": "high/medium/low"}]
    """
    if not ANTHROPIC_API_KEY or not main_keyword:
        return []

    # Build entity list text
    entity_names = []
    for e in found_entities[:25]:
        if isinstance(e, dict):
            name = e.get("text", e.get("entity", e.get("name", "")))
        else:
            name = str(e)
        if name and len(name) > 1:
            entity_names.append(name)

    if not entity_names:
        return []

    entities_text = ", ".join(entity_names)

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        prompt = ENTITY_GAP_PROMPT.format(
            keyword=main_keyword,
            found_entities=entities_text
        )

        response = client.messages.create(
            model=MIDDLEWARE_MODEL,
            max_tokens=800,
            temperature=0,
            messages=[{"role": "user", "content": prompt}]
        )

        raw_text = response.content[0].text.strip()
        json_match = re.search(r'\{[\s\S]*\}', raw_text)
        if not json_match:
            logger.warning("[ENTITY_GAP] No JSON in response")
            return []

        data = json.loads(json_match.group())
        gaps = data.get("entity_gaps", [])

        # Validate and clean
        clean_gaps = []
        for g in gaps[:12]:
            if isinstance(g, dict) and g.get("entity"):
                clean_gaps.append({
                    "entity": str(g["entity"]).strip(),
                    "why": str(g.get("why", "")).strip()[:100],
                    "priority": g.get("priority", "medium") if g.get("priority") in ("high", "medium", "low") else "medium",
                })

        logger.info(f"[ENTITY_GAP] Found {len(clean_gaps)} entity gaps for '{main_keyword}'")
        return clean_gaps

    except Exception as e:
        logger.warning(f"[ENTITY_GAP] Analysis failed: {e}")
        return []


# ================================================================
# EXPORTS — compatibility
# ================================================================

def process_s1_for_pipeline(s1_data: dict, main_keyword: str) -> dict:
    """Main entry point — called from app.py."""
    return ai_clean_s1_complete(s1_data, main_keyword)


# Legacy aliases
def ai_clean_s1_data(s1_data: dict, main_keyword: str) -> dict:
    return ai_clean_s1_complete(s1_data, main_keyword)

def clean_s1_entities(entities: list) -> list:
    return _regex_filter_list(entities)

def clean_s1_ngrams(ngrams: list) -> list:
    return _regex_filter_list(ngrams)

def ai_validate_entities(raw_entities: list, main_keyword: str) -> list:
    return _regex_filter_list(raw_entities)

# Expose for app.py display filters
def is_garbage_regex(text: str) -> bool:
    return _is_garbage_regex(text)


# ================================================================
# SENTENCE LENGTH RETRY — rozbija za długie zdania po akceptacji
# ================================================================

def check_sentence_length(text: str, max_avg: float = None, max_hard: int = None) -> dict:
    # Fix #9: Import z shared_constants
    try:
        from shared_constants import SENTENCE_AVG_MAX_ALLOWED, SENTENCE_HARD_MAX
        if max_avg is None:
            max_avg = float(SENTENCE_AVG_MAX_ALLOWED)  # 20.0
        if max_hard is None:
            max_hard = SENTENCE_HARD_MAX  # 35
    except ImportError:
        if max_avg is None:
            max_avg = 20.0
        if max_hard is None:
            max_hard = 35
    """
    Check if text has too-long sentences.
    Returns dict: {needs_retry, avg_len, long_count, long_sentences}
    """
    import re
    sentences = re.split(r'[.!?]+', text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 5]
    if not sentences:
        return {"needs_retry": False, "avg_len": 0, "long_count": 0}
    lengths = [len(s.split()) for s in sentences]
    avg = sum(lengths) / len(lengths)
    long_sents = [(s, l) for s, l in zip(sentences, lengths) if l > max_hard]

    # Comma check — Fix #53: SENTENCE_MAX_COMMAS = 2
    try:
        from shared_constants import SENTENCE_MAX_COMMAS
        _max_commas = SENTENCE_MAX_COMMAS
    except ImportError:
        _max_commas = 2
    comma_heavy = [(s, s.count(",")) for s in sentences if s.count(",") > _max_commas]

    # v59 FIX: Proportional thresholds — scale with text length.
    # Old: hardcoded > 2 → triggered on full articles (170 sentences, 3 long = 1.8% = normal).
    # New: 5% threshold — allows proportional number of long/complex sentences.
    total_sents = len(sentences)
    _long_threshold = max(2, int(total_sents * 0.05))
    _comma_threshold = max(2, int(total_sents * 0.05))
    needs_retry = avg > max_avg or len(long_sents) > _long_threshold or len(comma_heavy) > _comma_threshold
    return {
        "needs_retry": needs_retry,
        "avg_len": round(avg, 1),
        "long_count": len(long_sents),
        "long_sentences": [s for s, _ in long_sents[:5]],
        "comma_count": len(comma_heavy),
        "comma_examples": [s[:80] for s, _ in comma_heavy[:3]],
    }


def sentence_length_retry(text: str, h2: str = "", avg_len: float = 0, long_count: int = 0, comma_count: int = 0) -> str:
    """
    Use Haiku to split overly long sentences and reduce commas in accepted batch text.
    """
    if not ANTHROPIC_API_KEY:
        return text

    try:
        from shared_constants import SENTENCE_MAX_COMMAS
        max_commas = SENTENCE_MAX_COMMAS  # 2
    except ImportError:
        max_commas = 2

    comma_note = ""
    if comma_count > 0:
        comma_note = f" Zdań z 3+ przecinkami: {comma_count} (limit: max {max_commas} przecinki/zdanie)."

    problem_desc = f"Srednia dlugos zdania: {avg_len:.0f} slow (cel: 14-18). Zdan powyzej 28 slow: {long_count}.{comma_note}"

    prompt = f"""Skroc i uprosz zdania w ponizszym fragmencie artykulu SEO po polsku.

PROBLEM: {problem_desc}
SEKCJA: {h2}

ZASADY:
1. Rozbij zdania dluzsze niz 25 slow — podziel na 2 krotsze zdania.
2. Zdania z 3 lub wiecej przecinkami — rozbij na osobne zdania lub uprosz.
3. ZAKAZ: zdania wielokrotnie zlozone (wiele klauzul polaczonych "ktory", "poniewaz", "chociaz", "i tym", "a takze").
4. Zachowaj CALA tresc merytoryczna — zero usuwania informacji.
5. Zachowaj strukture HTML (tagi p, ul, li, h2, h3) bez zmian.
6. Cel: srednia 14-18 slow/zdanie, max 2 przecinki w zdaniu.
7. Odpowiedz TYLKO przepisanym HTML, bez komentarzy.

Technika rozbijania:
- "X, ktory Y, skutkuje Z" -> "X skutkuje Z. Dzieje sie tak, poniewaz Y."
- "A i B, a takze C w przypadku D" -> "A i B. Dotyczy to rowniez C w przypadku D."
- Dlugie wyliczanki -> zdanie + lista punktowa.

TEKST DO SKROCENIA:
{text[:4000]}"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=MIDDLEWARE_MODEL,
            max_tokens=4000,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}]
        )
        result = response.content[0].text.strip()
        original_words = len(text.split())
        new_words = len(result.split())
        if new_words < original_words * 0.7:
            return text  # too much removed, reject
        return result
    except Exception:
        return text


def check_anaphora(text: str, main_entity: str = "") -> dict:
    """
    Fix #64: Wykrywa anaphoryczny keyword stuffing.
    Sprawdza czy ta sama fraza otwiera 3+ kolejnych zdań w akapicie.
    Zwraca: {needs_fix, anaphora_count, examples}
    """
    import re
    if not text or not main_entity:
        return {"needs_fix": False, "anaphora_count": 0, "examples": []}

    entity_lower = main_entity.lower().strip()
    # Podziel na akapity (po znaczniku blokowym lub podwójnym newline)
    paragraphs = re.split(r'\n\n+|(?<=</p>)|(?<=</li>)', text)

    total_runs = 0
    examples = []

    for para in paragraphs:
        # Wyciagnij zdania z akapitu
        sents = re.split(r'(?<=[.!?])\s+', para.strip())
        sents = [s.strip() for s in sents if len(s.strip()) > 10]

        run = 0
        for sent in sents:
            if sent.lower().startswith(entity_lower):
                run += 1
                if run >= 3:
                    total_runs += 1
                    if len(examples) < 3:
                        examples.append(sent[:80])
            else:
                run = 0

    # --- Fix #64: Dodatkowe wzorce anafory globalnej ---

    # 1. FAQ: 4+ pytań zaczynających się od tego samego słowa z rzędu
    sentences_all = re.split(r'(?<=[.!?])\s+', text)
    faq_window = 4
    for i in range(len(sentences_all) - faq_window + 1):
        window = sentences_all[i:i + faq_window]
        first_words = [s.split()[0].lower().rstrip(".,?!") if s.split() else "" for s in window]
        if len(set(first_words)) == 1 and first_words[0]:
            total_runs += 1
            if len(examples) < 3:
                examples.append(f"[FAQ anaphora] 4x \'{first_words[0]}\': {window[0][:60]}")

    # 2. Zero-subject: zdanie zaczyna się od imiesłowu bez podmiotu
    # np. "Zlekceważone prowadzą", "Nieleczone skutkują", "Pozostawione mogą"
    zero_subj_matches = re.findall(
        r'(?:^|(?<=[.!?]\s))[A-ZŁŚĆŃÓŹ][a-złśćńóź]{3,}ne\s|'
        r'(?:^|(?<=[.!?]\s))[A-ZŁŚĆŃÓŹ][a-złśćńóź]{3,}ny\s|'
        r'(?:^|(?<=[.!?]\s))[A-ZŁŚĆŃÓŹ][a-złśćńóź]{3,}nych\s',
        text
    )
    if zero_subj_matches:
        total_runs += len(zero_subj_matches)
        for m in zero_subj_matches[:2]:
            if len(examples) < 3:
                examples.append(f"[zero-subject] \'{m.strip()}\'")

    # 3. Zaimek 'To' jako podmiot zdania (2+ razy)
    to_subject = re.findall(r'(?:^|(?<=[.!?]\s))To\s+[a-ząćęłńóśźż]', text)
    if len(to_subject) >= 2:
        total_runs += 1
        if len(examples) < 3:
            examples.append(f"[To-subject] {len(to_subject)}x zdanie zaczyna się od 'To'")

    return {
        "needs_fix": total_runs > 0,
        "anaphora_count": total_runs,
        "examples": examples,
    }


def anaphora_retry(text: str, main_entity: str, h2: str = "", max_retries: int = 2) -> str:
    """
    Fix #64 v2: Użyj Haiku do rozbicia anaphorycznych serii zdań.
    v45.3 FIX:
    - Rozszerzony prompt o WSZYSTKIE 4 wzorce anafory (entity, FAQ, zero-subject, To-subject)
    - Podniesiony limit z 4000 do pełnego tekstu (max 8000)
    - Dodany retry loop (max 2 próby)
    """
    if not ANTHROPIC_API_KEY or not main_entity:
        return text

    # v45.3: Pełny tekst, nie obcięty do 4000
    text_for_fix = text[:8000] if len(text) > 8000 else text

    prompt = f"""Masz do poprawienia fragment artykułu SEO po polsku.

SEKCJA: {h2}

PROBLEMY DO NAPRAWY (WSZYSTKIE 4 WZORCE):

1. ENTITY ANAPHORA: fraza "{main_entity}" otwiera 3+ kolejnych zdań w jednym akapicie.
   → Max 2 zdania z rzędu mogą zaczynać się od tej samej frazy.
   → Przy 3. zdaniu zamień otwierającą frazę na: zaimek, synonim lub inny podmiot.

2. FAQ ANAPHORA: 4+ zdań z rzędu zaczynających się od tego samego słowa (np. "Czy...", "Jak...", "Kiedy...").
   → Przeformułuj co 3. pytanie: "Warto też wiedzieć, ...", "Często pojawia się pytanie o...", "Z kolei..."

3. ZERO-SUBJECT: zdania zaczynające się od imiesłowu biernego bez podmiotu
   (np. "Zlekceważone prowadzą...", "Nieleczone skutkują...", "Pozostawione mogą...").
   → Dodaj jawny podmiot: "Objawy zlekceważone prowadzą...", "Schorzenie nieleczone skutkuje..."

4. TO-SUBJECT: 2+ zdań zaczynających się od "To jest/To może/To wymaga".
   → Zamień na konkretny podmiot: "Procedura wymaga...", "Ten etap może..."

ZASADY:
1. NIE zmieniaj treści merytorycznej — tylko podmiot/otwarcie zdania.
2. Zachowaj pełną strukturę HTML (tagi p, ul, li, h2, h3 itp.).
3. Odpowiedz TYLKO poprawionym HTML, bez żadnych komentarzy.

TEKST DO POPRAWY:
{text_for_fix}"""

    current_text = text
    for retry in range(max_retries):
        try:
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=6000,
                temperature=0,
                messages=[{"role": "user", "content": prompt}]
            )
            result = resp.content[0].text.strip()

            # Sanity check
            if len(result) < len(current_text) * 0.7 or len(result) < 50:
                logger.warning(f"[ANAPHORA_RETRY] Result too short on attempt {retry+1}, keeping current")
                break

            current_text = result

            # Check if anaphora is fixed
            check = check_anaphora(current_text, main_entity)
            if not check["needs_fix"]:
                logger.info(f"[ANAPHORA_RETRY] ✅ Fixed on attempt {retry+1}")
                return current_text

            logger.info(f"[ANAPHORA_RETRY] Attempt {retry+1}: still {check['anaphora_count']} issues, retrying...")
            # Update prompt text for next retry
            prompt = prompt.replace(text_for_fix, current_text[:8000])

        except Exception as e:
            logger.warning(f"[ANAPHORA_RETRY] Haiku call failed on attempt {retry+1}: {e}")
            break

    return current_text





# ═══════════════════════════════════════════════════════════════
# DOMAIN VALIDATOR v1.0 — Warstwa 2 ochrony terminologicznej
# Szybki Haiku call po każdym accepted batchu.
# Wykrywa halucynacje terminologiczne PRZED merge artykułu.
# ═══════════════════════════════════════════════════════════════

# Domenowe reguły per kategoria — szybka pre-check regex
# (jeśli nic nie pasuje, pomijamy kosztowny call LLM)
_DOMAIN_QUICK_PATTERNS = {
    "prawo": [
        (r"alkohol\s+[zw]\s+natury", "alkohol z/w natury → stężenie alkoholu we krwi"),
        (r"alkohol\s+z\s+urodzenia", "alkohol z urodzenia → stężenie alkoholu we krwi"),
        (r"promile\s+[zw]\s+natury", "promile z/w natury → stan nietrzeźwości"),
        (r"promile\s+z\s+urodzenia", "promile z urodzenia → stan nietrzeźwości"),
        (r"\bopilstwo\b", "opilstwo → stan nietrzeźwości (archaizm)"),
        (r"\bpijaństwo\b", "pijaństwo → stan nietrzeźwości (w kontekście prawnym)"),
        (r"obsług[iu]\w*\s+pojazd", "obsługiwał pojazd → prowadził pojazd"),
        (r"zakaz\s+obsługi\s+pojazd", "zakaz obsługi → zakaz prowadzenia"),
        (r"odpowiednich\s+przepisów\s+prawa", "placeholder → konkretny artykuł ustawy"),
        (r"właściwych\s+regulacji\s+prawnych", "placeholder → konkretny artykuł ustawy"),
        (r"stosownych\s+przepisów", "placeholder → konkretny artykuł ustawy"),
        (r"bezwzględn\w+\s+aresztowan", "aresztowanie → pozbawienie wolności"),
        (r"\baresztowan\w+", "aresztowanie → pozbawienie wolności (terminologia)"),
        (r"do\s+2\s+lat\b.{0,30}alkohol", "do 2 lat → art. 178a §1 = do 3 lat (2023)"),
        (r"mg/100\s*ml", "mg/100ml → promile (‰) lub mg/dm³"),
        # Bug E Fix: confusable terminologia spadkowa — LLM myli "upadek" z "spadek"
        (r"\bupad[klu]\w*\b", "upadek/upadku → prawdopodobnie 'spadek/spadku' (dziedziczenie)"),
        (r"\bobjęci[ae]\s+upadku\b", "objęcie upadku → nabycie spadku"),
        (r"\bupad[kl]\s+(?:po|jest|jako|na)\b", "upadek → spadek (mylenie terminów)"),
    ],
    "medycyna": [
        (r"badanie\s+wykazało\s+\d+%\s+skuteczn", "podejrzana statystyka — zweryfikuj"),
        (r"według\s+badań\s+z\s+\d{4}\s+roku.*?%", "podejrzana statystyka z rokiem — zweryfikuj"),
        (r"lek\s+\w+\s+dzia[łl]a\s+w\s+\d+%", "podejrzana dawka — zweryfikuj"),
    ],
    "finanse": [
        (r"stopa\s+procentowa\s+wynosi\s+\d+[,\.]\d+%", "podejrzana stopa procentowa — zweryfikuj aktualność"),
        (r"podatek\s+\w+\s+wynosi\s+\d+%", "stawka podatkowa — zweryfikuj aktualność"),
    ],
}

_DOMAIN_LLM_PROMPT = {
    "prawo": """Jesteś walidatorem terminologii prawnej.

Przejrzyj poniższy tekst i wykryj TYLKO te błędy:
1. Błędna terminologia karna: "opilstwo", "pijaństwo" zamiast "stan nietrzeźwości"
2. Halucynacje alkohol: "alkohol z natury", "alkohol z urodzenia", "promile z natury", "promile z urodzenia"
3. Błędne jednostki: "mg/100 ml" (poprawne: promile ‰ lub mg/dm³)
4. Phantom przepisy: "odpowiednich przepisów prawa", "właściwych regulacji" bez numeru artykułu
5. Błędne kary: "do 2 lat" dla art. 178a §1 KK (poprawne: do 3 lat od 2023)
6. Błędna terminologia: "obsługiwał pojazd" zamiast "prowadził pojazd"
7. Podejrzane sygnatury wyroków (I C / II C w sprawach karnych)
8. Mylenie "upadek/upadku" z "spadek/spadku" w kontekście dziedziczenia (np. "objęcie upadku" → "nabycie spadku")

Odpowiedz TYLKO w JSON:
{"errors": [{"type": "TERMINOLOGIA|HALUCYNACJA|JEDNOSTKI|PHANTOM|KARA|SYGNATURA|CONFUSABLE", "found": "cytat z tekstu", "fix": "poprawka"}], "clean": true/false}

Jeśli brak błędów: {"errors": [], "clean": true}

TEKST:
{text}""",

    "medycyna": """Jesteś walidatorem terminologii medycznej.

Wykryj TYLKO:
1. Wymyślone statystyki (konkretne % lub liczby bez źródła)
2. Nieistniejące leki lub dawki
3. Niebezpieczne porady zdrowotne bez zastrzeżenia
4. Błędna terminologia medyczna (potoczna zamiast naukowej)

Odpowiedz TYLKO w JSON:
{"errors": [{"type": "HALUCYNACJA|NIEBEZPIECZNE|TERMINOLOGIA", "found": "cytat", "fix": "poprawka"}], "clean": true/false}

Jeśli brak błędów: {"errors": [], "clean": true}

TEKST:
{text}""",

    "finanse": """Jesteś walidatorem terminologii finansowej.

Wykryj TYLKO:
1. Nieaktualne lub podejrzane stopy procentowe / stawki podatkowe
2. Porady inwestycyjne bez zastrzeżenia "nie stanowi porady finansowej"
3. Wymyślone dane rynkowe

Odpowiedz TYLKO w JSON:
{"errors": [{"type": "NIEAKTUALNE|NIEBEZPIECZNE|HALUCYNACJA", "found": "cytat", "fix": "poprawka"}], "clean": true/false}

Jeśli brak błędów: {"errors": [], "clean": true}""",
}


def _quick_domain_check(text: str, category: str) -> list[str]:
    """
    Szybka regex pre-check — O(n) bez kosztów API.
    Zwraca listę opisów znalezionych problemów.
    """
    patterns = _DOMAIN_QUICK_PATTERNS.get(category, [])
    found = []
    tl = text.lower()
    for pat, desc in patterns:
        if re.search(pat, tl):
            found.append(desc)
    return found


def validate_batch_domain(text: str, category: str, batch_num: int = 0) -> dict:
    """
    Warstwa 2: Walidacja domenowa po każdym accepted batchu.

    Zwraca:
        {
            "clean": bool,
            "errors": list[dict],    # [{type, found, fix}]
            "quick_hits": list[str], # regex pre-check hits
            "skipped": bool,         # True if category nie ma walidatora
        }
    """
    result = {"clean": True, "errors": [], "quick_hits": [], "skipped": False}

    if not text or not category or category not in _DOMAIN_QUICK_PATTERNS:
        result["skipped"] = True
        return result

    # 1. Szybka regex pre-check
    quick = _quick_domain_check(text, category)
    result["quick_hits"] = quick

    # Jeśli regex nie znalazł nic → oszczędzamy call LLM
    if not quick:
        return result

    # 2. LLM validation (Haiku — tani, szybki)
    if not ANTHROPIC_API_KEY:
        # Tylko regex wyniki bez LLM
        if quick:
            result["clean"] = False
            result["errors"] = [{"type": "REGEX", "found": q, "fix": ""} for q in quick]
        return result

    prompt_template = _DOMAIN_LLM_PROMPT.get(category)
    if not prompt_template:
        result["skipped"] = True
        return result

    # Truncate text for cost control (~2000 tokens max)
    text_for_llm = text[:4000] if len(text) > 4000 else text
    prompt = prompt_template.replace("{text}", text_for_llm)

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            temperature=0,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = resp.content[0].text.strip()

        # Parse JSON
        first = raw.find("{")
        last = raw.rfind("}")
        if first != -1 and last > first:
            data = json.loads(raw[first:last+1])
            errors = data.get("errors", [])
            result["clean"] = len(errors) == 0
            result["errors"] = errors
        else:
            # Fallback do regex
            result["clean"] = False
            result["errors"] = [{"type": "REGEX", "found": q, "fix": ""} for q in quick]

    except Exception as e:
        logger.warning(f"[DOMAIN_VALIDATOR] batch {batch_num} error: {e}")
        # Regex only
        result["clean"] = False
        result["errors"] = [{"type": "REGEX", "found": q, "fix": ""} for q in quick]

    return result


def fix_batch_domain_errors(text: str, validation: dict, category: str, h2: str = "") -> str:
    """
    Warstwa 1 rozszerzona: Smart retry z domain errors (nie tylko keyword overflow).
    Używa Haiku do poprawy znalezionych błędów domenowych.
    """
    if validation.get("clean") or not validation.get("errors"):
        return text

    errors = validation["errors"]
    if not ANTHROPIC_API_KEY:
        return text

    # Buduj listę poprawek
    fix_lines = []
    for e in errors:
        found = e.get("found", "")
        fix = e.get("fix", "")
        typ = e.get("type", "BŁĄD")
        if found:
            if fix:
                fix_lines.append(f'  [{typ}] Znajdź: "{found}" → Zamień na: "{fix}"')
            else:
                fix_lines.append(f'  [{typ}] Usuń lub przepisz fragment: "{found}"')

    if not fix_lines:
        return text

    fix_text = "\n".join(fix_lines)

    prompt = f"""Popraw poniższy fragment artykułu. Zmień TYLKO błędne wyrażenia z listy poniżej.
Zachowaj dokładnie tę samą strukturę HTML, długość i styl tekstu.
Odpowiedz TYLKO poprawionym HTML bez żadnych komentarzy.

SEKCJA: {h2}

BŁĘDY DO POPRAWY:
{fix_text}

TEKST:
{text}"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4000,
            temperature=0,
            messages=[{"role": "user", "content": prompt}]
        )
        fixed = resp.content[0].text.strip()
        # Safety: reject if too short
        if len(fixed) < len(text) * 0.7:
            logger.warning("[DOMAIN_VALIDATOR] fix too short, rejecting")
            return text
        return fixed
    except Exception as e:
        logger.warning(f"[DOMAIN_VALIDATOR] fix error: {e}")
        return text
