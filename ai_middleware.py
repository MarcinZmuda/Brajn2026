"""
AI Middleware for BRAJEN SEO v45.3
==================================
Replaces the "AI agent intelligence layer" that existed in Custom GPT
but was lost when migrating to deterministic Flask app.

Uses Claude Haiku (fast, cheap) for:
1. S1 data cleaning — removes CSS/JS garbage from entities and n-grams
2. Smart retry — rewrites batch text addressing exceeded keywords
3. S1 insight extraction — generates meaningful analysis when S1 data is noisy

ARCHITECTURE:
  N-gram API → S1 raw data → [AI MIDDLEWARE] → clean data → Claude Opus (content generation)
  
  Batch rejected → [AI MIDDLEWARE smart retry] → rewritten text → batch_simple

Cost: Claude Haiku is ~20x cheaper than Opus. Typical S1 cleanup = ~500 tokens input.
"""

import os
import json
import logging
import re

import anthropic

logger = logging.getLogger(__name__)

# Use Haiku for middleware (fast + cheap), Opus stays for content generation
MIDDLEWARE_MODEL = os.environ.get("MIDDLEWARE_MODEL", "claude-haiku-4-5-20251001")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# ================================================================
# 1. S1 DATA CLEANING — AI-powered garbage removal
# ================================================================

# Pattern-based pre-filter (fast, no API call needed for obvious garbage)
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
    r'import\s+\{|export\s+(default|const)|require\('
    r')',
    re.IGNORECASE
)

_GARBAGE_ENTITY_TYPES = {
    # NER labels that make no sense for typical entities
    "buttons", "meta", "cookie", "Web", "inline", "block",
    "default", "active", "hover", "flex", "grid", "none",
    "inherit", "auto", "hidden", "visible", "relative",
    "absolute", "fixed", "static", "center", "wrap",
    "bold", "normal", "italic", "transparent", "solid",
    "pointer", "disabled", "checked", "focus", "root",
    "ast", "var", "global", "color", "sich", "un", "uw",
}


def _is_obvious_garbage(text: str) -> bool:
    """Fast pattern check — no AI needed for obvious CSS/JS garbage."""
    if not text or not isinstance(text, str):
        return True
    text = text.strip()
    if len(text) < 2:
        return True
    
    # High ratio of special characters
    special = sum(1 for c in text if c in '{}:;()[]<>=#.@\\')
    if len(text) > 0 and special / len(text) > 0.12:
        return True
    
    # Known garbage words
    if text.lower().strip() in _GARBAGE_ENTITY_TYPES:
        return True
    
    # CSS/JS pattern match
    if _CSS_JS_PATTERNS.search(text):
        return True
    
    # N-gram specific: multiple words that are all lowercase CSS-like
    words = text.lower().split()
    if len(words) >= 2:
        css_words = {"block", "inline", "flex", "grid", "left", "right", "top", "bottom",
                     "auto", "none", "center", "wrap", "bold", "normal", "hidden",
                     "visible", "absolute", "relative", "fixed", "static", "default",
                     "image", "color", "width", "height", "size", "style", "type",
                     "global", "var", "ast", "min", "max", "overflow", "scroll",
                     "decoration", "widget", "footer", "sidebar", "header", "nav"}
        if all(w in css_words for w in words):
            return True
    
    return False


def clean_s1_entities(entities: list) -> list:
    """Clean entities using pattern matching + optional AI verification."""
    if not entities:
        return []
    
    clean = []
    for ent in entities:
        if isinstance(ent, dict):
            text = ent.get("text", "") or ent.get("entity", "") or ent.get("name", "")
        else:
            text = str(ent)
        
        if not _is_obvious_garbage(text):
            clean.append(ent)
    
    return clean


def clean_s1_ngrams(ngrams: list) -> list:
    """Clean n-grams using pattern matching."""
    if not ngrams:
        return []
    
    clean = []
    for ng in ngrams:
        text = ng.get("ngram", ng) if isinstance(ng, dict) else str(ng)
        if not _is_obvious_garbage(text):
            clean.append(ng)
    
    return clean


def ai_clean_s1_data(s1_data: dict, main_keyword: str) -> dict:
    """
    AI-powered S1 data cleaning using Claude Haiku.
    
    Cleans: entities, n-grams, H2 patterns.
    Enriches: generates summary of competitive landscape when data is noisy.
    
    Returns: cleaned s1_data dict (modified in-place safe).
    """
    if not s1_data:
        return s1_data
    
    # Step 1: Pattern-based pre-cleaning (free, instant)
    raw_entities = (s1_data.get("entity_seo") or {}).get("top_entities", 
                   (s1_data.get("entity_seo") or {}).get("entities", []))
    raw_ngrams = s1_data.get("ngrams", [])
    raw_h2_patterns = s1_data.get("competitor_h2_patterns", [])
    
    clean_entities = clean_s1_entities(raw_entities)
    clean_ngrams = clean_s1_ngrams(raw_ngrams)
    
    # Count how much garbage was removed
    entities_removed = len(raw_entities) - len(clean_entities)
    ngrams_removed = len(raw_ngrams) - len(clean_ngrams)
    total_garbage = entities_removed + ngrams_removed
    
    logger.info(f"[AI_MW] S1 cleanup: removed {entities_removed} garbage entities, {ngrams_removed} garbage n-grams")
    
    # Step 2: If too much garbage (>40%), use AI to extract real insights
    garbage_ratio = total_garbage / max(len(raw_entities) + len(raw_ngrams), 1)
    
    ai_insights = None
    if garbage_ratio > 0.4 and ANTHROPIC_API_KEY:
        logger.info(f"[AI_MW] High garbage ratio ({garbage_ratio:.0%}) — calling AI for S1 insights")
        ai_insights = _ai_extract_s1_insights(
            main_keyword=main_keyword,
            clean_entities=clean_entities[:15],
            clean_ngrams=clean_ngrams[:20],
            h2_patterns=raw_h2_patterns[:15],
            paa=s1_data.get("paa", [])[:10],
            causal=s1_data.get("causal_triplets", {})
        )
    
    # Step 3: Update s1_data with cleaned values
    result = dict(s1_data)  # shallow copy
    
    if "entity_seo" in result:
        entity_seo = dict(result["entity_seo"])
        if "top_entities" in entity_seo:
            entity_seo["top_entities"] = clean_entities
        elif "entities" in entity_seo:
            entity_seo["entities"] = clean_entities
        result["entity_seo"] = entity_seo
    
    result["ngrams"] = clean_ngrams
    
    # Add AI insights if generated
    if ai_insights:
        result["_ai_insights"] = ai_insights
        # Supplement missing data
        if not clean_entities and ai_insights.get("key_entities"):
            result["entity_seo"] = result.get("entity_seo", {})
            result["entity_seo"]["ai_extracted_entities"] = ai_insights["key_entities"]
        if ai_insights.get("competitive_summary"):
            result["_competitive_summary"] = ai_insights["competitive_summary"]
    
    result["_cleanup_stats"] = {
        "entities_removed": entities_removed,
        "ngrams_removed": ngrams_removed,
        "garbage_ratio": round(garbage_ratio, 2),
        "ai_enriched": ai_insights is not None
    }
    
    return result


def _ai_extract_s1_insights(main_keyword, clean_entities, clean_ngrams, 
                             h2_patterns, paa, causal):
    """Use Claude Haiku to extract real insights from noisy S1 data."""
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        
        # Build compact prompt
        entities_text = ", ".join(
            (e.get("text", str(e)) if isinstance(e, dict) else str(e))
            for e in clean_entities[:10]
        )
        ngrams_text = ", ".join(
            (ng.get("ngram", str(ng)) if isinstance(ng, dict) else str(ng))
            for ng in clean_ngrams[:15]
        )
        h2_text = "\n".join(str(h) for h in h2_patterns[:10])
        paa_text = "\n".join(str(q) for q in paa[:8])
        
        response = client.messages.create(
            model=MIDDLEWARE_MODEL,
            max_tokens=600,
            temperature=0.2,
            system="Jesteś ekspertem SEO. Analizujesz dane z SERP i wyciągasz kluczowe wnioski. Odpowiadaj po polsku, zwięźle. Zwróć JSON.",
            messages=[{
                "role": "user",
                "content": f"""Temat: "{main_keyword}"

Oczyszczone encje z SERP: {entities_text or "brak"}
N-gramy: {ngrams_text or "brak"}
Nagłówki H2 konkurencji:
{h2_text or "brak"}
Pytania PAA:
{paa_text or "brak"}

Na podstawie tych danych, zwróć JSON:
{{
  "key_entities": ["lista 5-8 PRAWDZIWYCH encji istotnych dla tematu"],
  "important_ngrams": ["lista 5-10 PRAWDZIWYCH fraz kluczowych"],
  "competitive_summary": "1-2 zdania: co konkurencja porusza, jakie aspekty pokrywa",
  "missing_angles": ["2-3 kąty tematyczne których brakuje w SERP"]
}}"""
            }]
        )
        
        text = response.content[0].text.strip()
        # Parse JSON from response
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            return json.loads(json_match.group())
        return None
        
    except Exception as e:
        logger.warning(f"[AI_MW] S1 insights extraction failed: {e}")
        return None


# ================================================================
# 2. SMART RETRY — AI-powered batch rewriting
# ================================================================

def smart_retry_batch(
    original_text: str,
    exceeded_keywords: list,
    pre_batch: dict,
    h2: str,
    batch_type: str = "CONTENT",
    attempt_num: int = 1
) -> str:
    """
    Intelligent batch retry using Claude Haiku to rewrite text.
    
    Instead of mechanical string.replace(), this:
    1. Identifies all forms of exceeded keywords in text
    2. Replaces them contextually with synonyms
    3. Preserves meaning, flow, and SEO intent
    
    Much cheaper than re-generating with Opus — Haiku handles rewrites well.
    
    Args:
        original_text: Text that was rejected
        exceeded_keywords: List of exceeded keyword dicts with synonyms
        pre_batch: Pre-batch info for context
        h2: Current H2 heading
        batch_type: INTRO/CONTENT/FAQ
        attempt_num: Which retry attempt (1-3)
    
    Returns:
        Rewritten text with exceeded keywords replaced by synonyms
    """
    if not exceeded_keywords or not ANTHROPIC_API_KEY:
        return original_text
    
    # Build replacement instructions
    replacements = []
    for exc in exceeded_keywords:
        kw = exc.get("keyword", "")
        synonyms = exc.get("use_instead") or exc.get("synonyms") or []
        severity = exc.get("severity", "WARNING")
        
        if not kw or not synonyms:
            continue
        
        syn_list = [s if isinstance(s, str) else str(s) for s in synonyms[:3]]
        replacements.append({
            "keyword": kw,
            "synonyms": syn_list,
            "severity": severity
        })
    
    if not replacements:
        return original_text
    
    # Build stop keywords context
    stop_kw = (pre_batch.get("keyword_limits") or {}).get("stop_keywords", [])
    stop_kw_names = [kw.get("keyword", kw) if isinstance(kw, dict) else str(kw) for kw in stop_kw[:10]]
    
    # Build must-use keywords context
    must_kw = (pre_batch.get("keywords") or {}).get("basic_must_use", [])
    must_kw_names = [kw.get("keyword", kw) if isinstance(kw, dict) else str(kw) for kw in must_kw[:10]]
    
    replacement_instructions = "\n".join(
        f'  • "{r["keyword"]}" → zamień na: {", ".join(r["synonyms"])} ({"KRYTYCZNE" if r["severity"] == "CRITICAL" else "ostrzeżenie"})'
        for r in replacements
    )
    
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        
        response = client.messages.create(
            model=MIDDLEWARE_MODEL,
            max_tokens=4000,
            temperature=0.3,
            system=f"""Jesteś redaktorem SEO. Przepisujesz tekst zastępując nadużywane frazy ich synonimami.

ZASADY:
1. Zamień WSZYSTKIE formy odmieniowe danej frazy (np. "spakowane", "spakowanych", "spakowanego" → synonim)
2. Zachowaj sens, naturalność i płynność tekstu
3. NIE dodawaj nowych treści — tylko zamieniaj słowa
4. NIE zmieniaj struktury (nagłówki, akapity zostają jak są)
5. Zachowaj format: h2: na początku, potem akapity
6. Wynik = TYLKO przepisany tekst, bez komentarzy""",
            messages=[{
                "role": "user",
                "content": f"""Nagłówek sekcji: {h2}

FRAZY DO ZAMIANY:
{replacement_instructions}

{"FRAZY STOP (nie używaj wcale): " + ", ".join(stop_kw_names) if stop_kw_names else ""}

ORYGINALNY TEKST:
{original_text}

Przepisz tekst zamieniając nadużywane frazy na synonimy. Zwróć TYLKO przepisany tekst."""
            }]
        )
        
        rewritten = response.content[0].text.strip()
        
        # Sanity check: rewritten text should be similar length
        orig_words = len(original_text.split())
        new_words = len(rewritten.split())
        
        if new_words < orig_words * 0.7 or new_words > orig_words * 1.3:
            logger.warning(f"[AI_MW] Smart retry produced text with different length "
                         f"({new_words} vs {orig_words} words) — using original")
            return original_text
        
        # Ensure h2: prefix is preserved
        if original_text.strip().startswith("h2:") and not rewritten.strip().startswith("h2:"):
            rewritten = original_text.split("\n")[0] + "\n" + rewritten
        
        logger.info(f"[AI_MW] Smart retry: replaced keywords in {new_words} words "
                    f"(attempt {attempt_num})")
        return rewritten
        
    except Exception as e:
        logger.warning(f"[AI_MW] Smart retry failed: {e} — falling back to original text")
        return original_text


# ================================================================
# 3. ARTICLE MEMORY SYNTHESIS (when backend doesn't provide it)
# ================================================================

def synthesize_article_memory(accepted_batches: list) -> dict:
    """
    Build article memory from accepted batches when Anti-Frankenstein is disabled.
    
    This is a LOCAL substitute — tracks what was written in previous batches
    so Claude doesn't repeat itself.
    
    Args:
        accepted_batches: List of {"text": str, "h2": str, "batch_num": int}
    
    Returns:
        dict compatible with prompt_builder._fmt_article_memory()
    """
    if not accepted_batches:
        return {}
    
    topics_covered = []
    key_facts = []
    phrases_used = {}
    
    for batch in accepted_batches:
        text = batch.get("text", "")
        h2 = batch.get("h2", "")
        
        if h2:
            topics_covered.append({"topic": h2, "batch": batch.get("batch_num", 0)})
        
        # Simple phrase counting (without spaCy — just basic word frequency)
        words = text.lower().split()
        for word in set(words):
            if len(word) > 4:  # Skip short words
                count = words.count(word)
                if count >= 2:
                    phrases_used[word] = phrases_used.get(word, 0) + count
        
        # Extract first sentence of each paragraph as key facts
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip() and not p.strip().startswith("h2:")]
        for para in paragraphs[:2]:  # Max 2 facts per batch
            first_sentence = para.split(". ")[0] + "."
            if len(first_sentence) > 20 and len(first_sentence) < 200:
                key_facts.append(first_sentence)
    
    return {
        "topics_covered": topics_covered,
        "key_facts_used": key_facts[-8:],  # Last 8 facts
        "phrases_used": {k: v for k, v in sorted(phrases_used.items(), key=lambda x: -x[1])[:15]}
    }


def ai_synthesize_memory(accepted_batches: list, main_keyword: str) -> dict:
    """
    AI-powered article memory — uses Haiku to summarize what was written.
    Richer than synthesize_article_memory() but costs a small API call.
    
    Only called when Anti-Frankenstein backend module is disabled.
    """
    if not accepted_batches or not ANTHROPIC_API_KEY:
        return synthesize_article_memory(accepted_batches)
    
    # Only use AI for longer articles (3+ batches)
    if len(accepted_batches) < 3:
        return synthesize_article_memory(accepted_batches)
    
    # Collect texts (truncated)
    batch_summaries = []
    for batch in accepted_batches[-5:]:  # Last 5 batches
        text = batch.get("text", "")[:500]
        h2 = batch.get("h2", "")
        batch_summaries.append(f"[{h2}]: {text}")
    
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        
        response = client.messages.create(
            model=MIDDLEWARE_MODEL,
            max_tokens=500,
            temperature=0.2,
            system="Jesteś asystentem SEO. Streszczasz dotychczasową treść artykułu. Odpowiedz JSON.",
            messages=[{
                "role": "user",
                "content": f"""Temat artykułu: "{main_keyword}"

Dotychczasowe sekcje:
{"---".join(batch_summaries)}

Zwróć JSON:
{{
  "topics_covered": ["lista omówionych tematów"],
  "key_facts_used": ["lista kluczowych faktów/danych użytych w tekście"],
  "open_threads": ["tematy zapowiedziane ale nie rozwinięte"],
  "tone": "jednozdaniowy opis tonu (formalny/nieformalny/mieszany)"
}}"""
            }]
        )
        
        text = response.content[0].text.strip()
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            ai_memory = json.loads(json_match.group())
            # Merge with basic stats
            basic = synthesize_article_memory(accepted_batches)
            ai_memory["phrases_used"] = basic.get("phrases_used", {})
            return ai_memory
        
    except Exception as e:
        logger.warning(f"[AI_MW] Memory synthesis failed: {e}")
    
    return synthesize_article_memory(accepted_batches)


# ================================================================
# 4. QUALITY GATE — decide if AI retry is worth it
# ================================================================

def should_use_smart_retry(result: dict, attempt: int) -> bool:
    """
    Decide whether to use AI smart retry vs mechanical retry vs forced mode.
    
    Strategy:
    - Attempt 1: Failed → try smart_retry_batch (AI rewrite)
    - Attempt 2: Still failed → try smart_retry_batch again with stronger instructions
    - Attempt 3: Still failed → forced mode (give up on keywords, save anyway)
    
    Returns True if smart retry is recommended.
    """
    exceeded = result.get("exceeded_keywords") or []
    quality = result.get("quality") or {}
    score = quality.get("score", 0)
    
    # If no exceeded keywords, the issue is quality — smart retry won't help
    if not exceeded:
        return False
    
    # If score is very low (<50), a full rewrite is better than retry
    if score and score < 50:
        return False
    
    # Smart retry is useful for attempts 1-2
    return attempt < 3


# ================================================================
# 5. CONVENIENCE: Full S1 pipeline cleanup
# ================================================================

def process_s1_for_pipeline(s1_data: dict, main_keyword: str) -> dict:
    """
    Full S1 cleanup pipeline — call this right after receiving S1 response.
    
    1. Pattern-based cleanup (free, instant)
    2. AI enrichment if data is very noisy (small Haiku call)
    3. Returns clean s1_data ready for H2 planning and create_project
    """
    return ai_clean_s1_data(s1_data, main_keyword)
