"""
BRAJEN SEO Web App v45.2.2
==========================
Standalone web app that orchestrates BRAJEN SEO API + Anthropic Claude for text generation.
Replaces unreliable GPT Custom Actions with deterministic code-driven workflow.

Deploy: Render (render.yaml included)
Auth: Simple login/password via environment variable
"""

import os
import json
import time
import uuid
import hashlib
import logging
import secrets
import threading
import queue
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, jsonify, Response,
    session, redirect, url_for, stream_with_context, send_file
)
import requests as http_requests
# v68: HTTP session pooling — reuse TCP/TLS connections across brajen_call
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry as _Urllib3Retry
_brajen_session = http_requests.Session()
_brajen_adapter = HTTPAdapter(pool_connections=5, pool_maxsize=10, max_retries=0)
_brajen_session.mount("https://", _brajen_adapter)
_brajen_session.mount("http://", _brajen_adapter)
import anthropic
from prompt_v2.integration import (
    build_system_prompt, build_user_prompt,
    build_faq_system_prompt, build_faq_user_prompt,
    build_h2_plan_system_prompt, build_h2_plan_user_prompt,
    build_category_system_prompt, build_category_user_prompt,
    get_api_params,
)

# Optional: OpenAI
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

import re as _re

# AI Middleware: inteligentne czyszczenie danych i smart retry
from ai_middleware import (
    process_s1_for_pipeline,
    smart_retry_batch,
    should_use_smart_retry,
    synthesize_article_memory,
    ai_synthesize_memory,
    structured_article_memory,
    check_sentence_length,
    sentence_length_retry,
    check_anaphora,
    anaphora_retry,
    validate_batch_domain,
    fix_batch_domain_errors,
    analyze_entity_gaps,
)
from keyword_dedup import deduplicate_keywords, remove_subsumed_basic, cascade_deduct_targets
from entity_salience import (
    check_entity_salience,
    generate_article_schema,
    schema_to_html,
    generate_topical_map,
    build_entity_salience_instructions,
    is_salience_available,
    analyze_entities_google_nlp,
    analyze_subject_position,
    analyze_style_consistency,
    analyze_ymyl_references,
)

# v50.7: Polish NLP validator (NKJP corpus norms)
try:
    from polish_nlp_validator import validate_polish_text, get_polish_nlp_summary
    POLISH_NLP_AVAILABLE = True
except ImportError:
    POLISH_NLP_AVAILABLE = False

# v50.7: LanguageTool integration (corpus-based grammar/collocation checker)
try:
    from languagetool_checker import check_text as lt_check_text, get_summary as lt_get_summary
    LANGUAGETOOL_AVAILABLE = True
except ImportError:
    LANGUAGETOOL_AVAILABLE = False

# v67: LLM Cost Tracker
from llm_cost_tracker import cost_tracker

# ================================================================
# CSS/JS GARBAGE FILTER: extracted to css_filter.py
# ================================================================
from css_filter import (
    _CSS_GARBAGE_PATTERNS, _CSS_NGRAM_EXACT, _CSS_ENTITY_WORDS,
    _is_css_garbage, _extract_text, _filter_entities,
    _BRAND_PATTERNS, _is_brand_entity, _filter_ngrams
)


# v56: S1 cache — SERP data doesn't change within 24h for the same keyword
_S1_CACHE_DIR = "/tmp/s1_cache"
_S1_CACHE_TTL = 24 * 3600  # 24 hours

def _s1_cache_get(keyword):
    """Get cached S1 result for keyword. Returns None if expired or missing."""
    try:
        os.makedirs(_S1_CACHE_DIR, exist_ok=True)
        cache_key = hashlib.md5(keyword.lower().strip().encode()).hexdigest()
        cache_path = os.path.join(_S1_CACHE_DIR, f"{cache_key}.json")
        if os.path.exists(cache_path):
            mtime = os.path.getmtime(cache_path)
            if time.time() - mtime < _S1_CACHE_TTL:
                with open(cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
    except Exception:
        pass
    return None

def _s1_cache_set(keyword, data):
    """Cache S1 result for keyword."""
    try:
        os.makedirs(_S1_CACHE_DIR, exist_ok=True)
        cache_key = hashlib.md5(keyword.lower().strip().encode()).hexdigest()
        cache_path = os.path.join(_S1_CACHE_DIR, f"{cache_key}.json")
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass

# v50.7 FIX 40: AI cleanup for n-grams and causal triplets
# Uses Claude Haiku (cheap, ~$0.005/call) to filter scraper garbage
# that regex-based _is_css_garbage() misses.
_AI_CLEANUP_MODEL = "claude-haiku-4-5-20251001"

def _ai_cleanup_all_s1_data(main_keyword: str, ngrams: list, causal_chains: list, 
                            causal_singles: list, placement_instruction: str,
                            entity_salience: list, entities: list) -> dict:
    """v50.7 FIX 45: One AI call to clean ALL scraper data at once.
    
    Replaces regex whack-a-mole with AI that understands context.
    Cost: ~$0.005-0.01 per call (Claude Haiku), ~2-3s.
    
    Returns dict with cleaned versions of all inputs.
    """
    # Build concise input for AI
    ng_texts = []
    for ng in ngrams[:40]:
        text = ng.get("ngram", ng) if isinstance(ng, dict) else str(ng)
        ng_texts.append(text)
    
    causal_texts = []
    for c in (causal_chains + causal_singles)[:10]:
        cause = c.get("cause", c.get("from", ""))
        effect = c.get("effect", c.get("to", ""))
        causal_texts.append(f"{cause} → {effect}")
    
    sal_texts = []
    for s in entity_salience[:25]:
        ent = s.get("entity", s.get("text", "")) if isinstance(s, dict) else str(s)
        sal = s.get("salience", 0) if isinstance(s, dict) else 0
        typ = s.get("type", "") if isinstance(s, dict) else ""
        sal_texts.append(f"{ent} ({typ}, {sal:.2f})")
    
    ent_texts = []
    for e in entities[:25]:
        text = e.get("text", e.get("entity", "")) if isinstance(e, dict) else str(e)
        ent_texts.append(text)

    prompt = f"""Temat artykułu: "{main_keyword}"

Dane poniżej pochodzą ze scrapera stron konkurencji w SERP.
DUŻO z nich to ŚMIECI: fragmenty CSS (@font-face, font-family, display:block),
kody kolorów (hex: A7FF, FF00), nazwy fontów (Menlo, Monaco, Font Awesome),
nawigacja (menu, sidebar), klasy CSS (relative;display), nazwy języków z Wikipedii,
fragmenty URL (wp-content, blog/wp), urwane zdania (zaczynające się od małej litery
lub od przyrostka słowa), elementy UI.

ZADANIE: Z każdej sekcji zwróć TYLKO elementy MERYTORYCZNIE związane z "{main_keyword}".
Odrzuć wszelkie śmieci techniczne, CSS, HTML, nawigacyjne.

=== N-GRAMY ===
{chr(10).join(ng_texts) if ng_texts else "(brak)"}

=== RELACJE KAUZALNE ===
{chr(10).join(causal_texts) if causal_texts else "(brak)"}

=== PLACEMENT INSTRUCTION (tekst) ===
{placement_instruction[:800] if placement_instruction else "(brak)"}

=== ENTITY SALIENCE ===
{chr(10).join(sal_texts) if sal_texts else "(brak)"}

=== NAMED ENTITIES ===
{chr(10).join(ent_texts) if ent_texts else "(brak)"}

Odpowiedz TYLKO w JSON (bez markdown, bez ```):
{{
  "ngrams": ["ngram1", "ngram2"],
  "causal": ["cause → effect", ...],
  "placement": "oczyszczony tekst placement instruction (bez linii z CSS/śmieciami, zachowaj strukturę emoji 🎯📌📋📎🔺)",
  "salience": ["entity1", "entity2", ...],
  "entities": ["entity1", "entity2", ...]
}}

Jeśli sekcja ma SAME śmieci, zwróć pustą listę/string."""

    try:
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"), max_retries=0)
        response = client.messages.create(
            model=_AI_CLEANUP_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        result = json.loads(text)
        
        # --- N-grams: keep only AI-approved ---
        clean_ng_set = set(n.lower() for n in result.get("ngrams", []))
        filtered_ngrams = []
        for ng in ngrams:
            ng_text = (ng.get("ngram", ng) if isinstance(ng, dict) else str(ng)).lower()
            if ng_text in clean_ng_set:
                filtered_ngrams.append(ng)
        
        # --- Causal: keep by cause match ---
        approved_causes = set()
        for ct in result.get("causal", []):
            parts = ct.split("→")
            if parts:
                approved_causes.add(parts[0].strip().lower())
        filtered_chains = [c for c in causal_chains 
                          if c.get("cause", c.get("from", "")).lower().strip() in approved_causes
                          or any(ac in c.get("cause", c.get("from", "")).lower() for ac in approved_causes)]
        filtered_singles = [c for c in causal_singles
                           if c.get("cause", c.get("from", "")).lower().strip() in approved_causes
                           or any(ac in c.get("cause", c.get("from", "")).lower() for ac in approved_causes)]
        
        # --- Placement: use AI-cleaned version ---
        clean_placement = result.get("placement", placement_instruction) or placement_instruction
        
        # --- Salience: keep only AI-approved entities ---
        clean_sal_set = set(s.lower() for s in result.get("salience", []))
        filtered_salience = []
        for s in entity_salience:
            ent = (s.get("entity", s.get("text", "")) if isinstance(s, dict) else str(s)).lower()
            if ent in clean_sal_set or any(cs in ent for cs in clean_sal_set):
                filtered_salience.append(s)
        
        # --- Entities: keep only AI-approved ---
        clean_ent_set = set(e.lower() for e in result.get("entities", []))
        filtered_entities = []
        for e in entities:
            text = (e.get("text", e.get("entity", "")) if isinstance(e, dict) else str(e)).lower()
            if text in clean_ent_set or any(ce in text for ce in clean_ent_set):
                filtered_entities.append(e)
        
        logger.info(f"[AI_CLEANUP] ngrams:{len(ngrams)}→{len(filtered_ngrams)} | "
                    f"causal:{len(causal_chains)+len(causal_singles)}→{len(filtered_chains)+len(filtered_singles)} | "
                    f"salience:{len(entity_salience)}→{len(filtered_salience)} | "
                    f"entities:{len(entities)}→{len(filtered_entities)} | "
                    f"placement:{'cleaned' if clean_placement != placement_instruction else 'unchanged'}")
        
        return {
            "ngrams": filtered_ngrams,
            "causal_chains": filtered_chains,
            "causal_singles": filtered_singles,
            "placement_instruction": clean_placement,
            "entity_salience": filtered_salience,
            "entities": filtered_entities,
        }
    except Exception as e:
        logger.warning(f"[AI_CLEANUP] Failed: {e}, falling back to unfiltered data")
        return {
            "ngrams": ngrams,
            "causal_chains": causal_chains,
            "causal_singles": causal_singles,
            "placement_instruction": placement_instruction,
            "entity_salience": entity_salience,
            "entities": entities,
        }
# ============================================================
# FIX #21: YMYL Cache helpers
# ============================================================
def _get_cached_ymyl(project_id, db):
    """
    Check Firestore cache for YMYL data.
    Returns cached dict or None if not found or expired.
    """
    if not db or not project_id:
        return None
    try:
        doc = db.collection("ymyl_cache").document(project_id).get()
        if doc.exists:
            data = doc.to_dict()
            # Check expiration (24 hours)
            import time
            timestamp = data.get("_cached_at", 0)
            if time.time() - timestamp < 86400:  # 24 hours
                return data.get("ymyl_data")
    except Exception as e:
        logger.debug(f"[YMYL_CACHE] Get failed: {e}")
    return None


def _cache_ymyl(project_id, ymyl_data, db):
    """
    Save YMYL data to Firestore cache.
    Returns True if successful, False otherwise.
    """
    if not db or not project_id:
        return False
    try:
        import time
        db.collection("ymyl_cache").document(project_id).set({
            "ymyl_data": ymyl_data,
            "_cached_at": time.time(),
        })
        return True
    except Exception as e:
        logger.debug(f"[YMYL_CACHE] Set failed: {e}")
        return False


# ============================================================
# v50.7 FIX 46: LOCAL YMYL DETECTION (replaces master-seo-api call)
# Single Claude Haiku call → classifies + enriches
# Eliminates 404 error from broken /api/ymyl/detect_and_enrich
# ============================================================
_YMYL_PROMPT = """Klasyfikuj temat: "{topic}"

Określ kategorię YMYL (Your Money Your Life):
- "prawo": jeśli temat dotyczy prawa, kar, przepisów, wyroków, umów, rozwodów, przestępstw
- "zdrowie": jeśli dotyczy zdrowia, chorób, leków, terapii, objawów, diagnoz
- "finanse": jeśli dotyczy inwestycji, kredytów, podatków, ubezpieczeń, oszczędności
- "general": wszystko inne

Odpowiedz TYLKO w JSON (bez markdown):
{{
  "category": "prawo"|"zdrowie"|"finanse"|"general",
  "confidence": 0.0-1.0,
  "reasoning": "krótkie uzasadnienie po polsku",
  "ymyl_intensity": "full"|"light"|"none",
  "legal": {{"articles": ["art. X k.k."], "acts": ["Kodeks karny"], "key_concepts": ["..."], "search_queries": ["..."]}},
  "medical": {{"condition": "...", "mesh_terms": [], "search_queries": []}},
  "finance": {{"regulations": [], "search_queries": []}}
}}

Wypełnij TYLKO sekcję odpowiadającą kategorii. Resztę zostaw pustą."""


def _detect_ymyl_local(main_keyword: str) -> dict:
    """Local YMYL detection using Claude Haiku. ~$0.003, ~1s. v50.7 FIX 48: Auto-retry."""
    try:
        def _call():
            client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"), max_retries=0)
            return client.messages.create(
                model=_AI_CLEANUP_MODEL,  # Haiku (cheap + fast)
                max_tokens=500,
                temperature=0.1,
                messages=[{"role": "user", "content": _YMYL_PROMPT.format(topic=main_keyword)}]
            )
        response = _llm_call_with_retry(_call)
        raw = response.content[0].text.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(raw)
        
        category = result.get("category", "general")
        result["is_legal"] = category == "prawo"
        result["is_medical"] = category in ("zdrowie", "medycyna")
        result["is_finance"] = category in ("finanse", "finance")
        result["is_ymyl"] = category != "general"
        result["detection_method"] = "local_haiku"
        
        # Ensure all sections exist
        result.setdefault("legal", {})
        result.setdefault("medical", {})
        result.setdefault("finance", {})
        result.setdefault("ymyl_intensity", "full" if result["is_ymyl"] else "none")
        result.setdefault("confidence", 0.8)
        result.setdefault("reasoning", "")
        
        logger.info(f"[YMYL_LOCAL] {main_keyword} → {category} ({result.get('confidence', 0):.1f}) {result.get('reasoning', '')[:60]}")
        return result
    except Exception as e:
        logger.warning(f"[YMYL_LOCAL] Failed: {e}")
        return {
            "category": "general", "is_ymyl": False, "is_legal": False,
            "is_medical": False, "is_finance": False, "confidence": 0,
            "reasoning": f"Detection failed: {e}", "detection_method": "fallback",
            "ymyl_intensity": "none", "legal": {}, "medical": {}, "finance": {},
        }


# ═══ v56 FIX 1A: Validate legal article references from Haiku ═══
# Haiku hallucinates act names — e.g. "art. 87 ustawy o ochronie konkurencji"
# instead of "art. 87 k.w." (Kodeks wykroczeń). Only allow known Polish acts.
_KNOWN_LEGAL_ACTS_ABBR = {
    'k.k.', 'k.w.', 'k.c.', 'k.p.c.', 'k.p.k.', 'k.p.', 'k.r.o.',
    'k.p.a.', 'k.s.h.', 'p.r.d.', 'u.s.g.', 'k.k.s.',
}
# Use stems/roots to match Polish grammatical forms (prawo/prawa/prawem, ustawa/ustawy)
_KNOWN_LEGAL_ACT_STEMS = [
    'kodeks karn',          # Kodeks karny/karnego
    'kodeks wykrocz',       # Kodeks wykroczeń
    'kodeks cywiln',        # Kodeks cywilny/cywilnego
    'kodeks postępowan',    # Kodeks postępowania ...
    'kodeks prac',          # Kodeks pracy
    'kodeks rodzinn',       # Kodeks rodzinny
    'kodeks spółek',        # Kodeks spółek handlowych
    'praw. o ruchu drog',   # Prawo/Prawa o ruchu drogowym (regex below)
    'ustaw. o ruchu drog',  # Ustawa/Ustawy o ruchu drogowym
    'praw. budowlan',       # Prawo budowlane
    'praw. zamówień',       # Prawo zamówień publicznych
    'ustaw. o samorząd',    # Ustawa o samorządzie
    'kodeks karny skarbow', # Kodeks karny skarbowy
    'ustaw. o przeciwdziałaniu narkomani',  # Ustawa o przeciwdziałaniu narkomanii
    'ustaw. o wychowaniu w trzeźw',         # Ustawa o wychowaniu w trzeźwości
    'ustaw. o ochronie danych',             # Ustawa o ochronie danych osobowych
]

def _validate_legal_articles(articles: list) -> list:
    """Reject article references with hallucinated act names."""
    import re as _re
    validated = []
    for art in articles:
        art_lower = art.lower().strip()
        # Check known abbreviations (e.g. "k.k.", "k.w.", "p.r.d.")
        if any(abbr in art_lower for abbr in _KNOWN_LEGAL_ACTS_ABBR):
            validated.append(art)
            continue
        # Check known act stems (handles Polish grammatical forms)
        matched = False
        for stem in _KNOWN_LEGAL_ACT_STEMS:
            # Replace '.' in stem with regex for any single char (handles prawo/prawa/prawem)
            pattern = stem.replace('.', '.')
            if _re.search(pattern, art_lower):
                matched = True
                break
        if matched:
            validated.append(art)
            continue
        # Reject — likely hallucinated
        logger.warning(f"[YMYL_VALID] Rejected hallucinated article ref: {art}")
    return validated


def _detect_ymyl(main_keyword: str) -> dict:
    """
    YMYL detection with master-seo-api enrichment.

    Flow:
    1. Call _detect_ymyl_local as pre-filter
    2. If not YMYL: add detected_category, return
    3. If YMYL: call master-seo-api /api/ymyl/detect_and_enrich for enrichment
    4. Return enriched data with normalized detected_category
    """
    try:
        # Step 1: Pre-filter with local detection
        local_result = _detect_ymyl_local(main_keyword)
        detected_category = local_result.get("category", "general")
        is_ymyl = local_result.get("is_ymyl", False)

        # Step 2: If not YMYL, add category and return early
        if not is_ymyl:
            local_result["detected_category"] = detected_category
            local_result["enrichment_method"] = "local_only"
            return local_result

        # Step 3: If YMYL, try to enrich via master-seo-api
        try:
            master_api_url = os.environ.get("BRAJEN_API_URL", os.environ.get("MASTER_SEO_API_URL", "https://master-seo-api.onrender.com"))
            api_key = os.environ.get("MASTER_SEO_API_KEY", "")

            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            enrich_response = http_requests.post(
                f"{master_api_url}/api/ymyl/detect_and_enrich",
                json={"keyword": main_keyword, "local_detection": local_result},
                headers=headers,
                timeout=8
            )

            if enrich_response.status_code == 200:
                # Fix #55: Guard against HTML error page (cold start / 502 z Render)
                raw_text = enrich_response.text.strip()
                if not raw_text.startswith("{"):
                    logger.warning(f"[YMYL_ENRICH] Response not valid JSON (starts with: {raw_text[:40]!r}), retrying once...")
                    # v67: Retry once — cold start often resolves in 2nd attempt
                    import time as _time_ymyl
                    _time_ymyl.sleep(2)
                    try:
                        enrich_response2 = http_requests.post(
                            f"{master_api_url}/api/ymyl/detect_and_enrich",
                            json={"keyword": main_keyword, "content_type": content_type},
                            headers=headers, timeout=10
                        )
                        raw_text2 = enrich_response2.text.strip()
                        if enrich_response2.status_code == 200 and raw_text2.startswith("{"):
                            enriched = enrich_response2.json()
                            enriched["detected_category"] = enriched.get("detected_category", detected_category)
                            enriched["enrichment_method"] = "master_api_enriched_retry"
                            logger.info(f"[YMYL_ENRICH] {main_keyword} enriched via retry")
                            return enriched
                        else:
                            logger.warning(f"[YMYL_ENRICH] Retry also failed, using local result")
                    except Exception as _retry_err:
                        logger.warning(f"[YMYL_ENRICH] Retry error: {_retry_err}")
                else:
                    enriched = enrich_response.json()
                    # Normalize detected_category from response
                    enriched["detected_category"] = enriched.get("detected_category", detected_category)
                    enriched["enrichment_method"] = "master_api_enriched"
                    logger.info(f"[YMYL_ENRICH] {main_keyword} enriched via master-seo-api")
                    return enriched
            else:
                logger.warning(f"[YMYL_ENRICH] Master API returned {enrich_response.status_code}, using local result")
        except Exception as e:
            logger.warning(f"[YMYL_ENRICH] Master API call failed: {e}, using local result")

        # Step 4: Fallback to local result with enrichment_method set
        local_result["detected_category"] = detected_category
        local_result["enrichment_method"] = "local_fallback"
        return local_result

    except Exception as e:
        logger.error(f"[YMYL_ENRICH] Error in _detect_ymyl: {e}")
        return {
            "category": "general", "is_ymyl": False, "is_legal": False,
            "is_medical": False, "is_finance": False, "confidence": 0,
            "reasoning": f"YMYL detection error: {e}", "detection_method": "error",
            "detected_category": "general", "enrichment_method": "error",
            "ymyl_intensity": "none", "legal": {}, "medical": {}, "finance": {},
        }


# When N-gram API fails to provide ai_topical_entities (common),
# generate proper topical entities using a fast LLM call.
# This replaces CSS/HTML garbage with real topic-based entities.
#
# Based on:
# - Patent US10235423B2: entity relatedness & notability
# - Patent US9009192B1: identifying central entities
# - Dunietz & Gillick (2014): entity salience
# - Document "Topical entities w SEO": topical entities = concepts
#   that define and contextualize a topic in Knowledge Graph
# ============================================================

_TOPICAL_ENTITY_PROMPT = """Jesteś ekspertem semantic SEO. Dla podanego tematu wygeneruj topical entities oraz N-gramy frazowe — koncepty, osoby, jednostki, prawa, urządzenia i pojęcia, które definiują ten temat w Knowledge Graph Google, PLUS frazy kluczowe które realnie pojawią się w tekście u konkurencji.

ZASADY:
1. Encje MUSZĄ być tematyczne, bezpośrednio powiązane z tematem, nie z komercyjnymi stronami w SERP
2. Encja główna = DOKŁADNIE podany temat (bez zmiany, bez 'bardziej precyzyjnych' wersji — hasło to jedyna poprawna odpowiedź)
3. Encje wtórne = 16-20 kluczowych konceptów powiązanych (podtypy, pojęcia prawne/medyczne/techniczne, procesy, konsekwencje, wyjątki, edge cases)
4. Dla każdej encji: 1 trójka E-A-V (Encja → Atrybut → Wartość)
5. 5-8 par co-occurrence (encje które powinny występować blisko siebie w tekście)
6. 10-15 semantic_ngrams — 2-4 wyrazowe frazy które MUSZĄ się pojawić w dobrym artykule o tym temacie (nie encje, ale konkretne wyrażenia jak „warunkowe umorzenie postępowania", „kara pozbawienia wolności", „stan po użyciu alkoholu")
7. NIE dodawaj firm komercyjnych, dat, cen, taryf
8. Odpowiedź TYLKO w JSON, bez markdown, bez komentarzy

FORMAT JSON:
{
  "primary_entity": {"text": "...", "type": "CONCEPT"},
  "secondary_entities": [
    {"text": "...", "type": "PERSON|CONCEPT|UNIT|LAW|DEVICE|EVENT|PROCESS", "eav": "encja → atrybut → wartość"}
  ],
  "semantic_ngrams": [
    {"phrase": "...", "importance": "HIGH|MEDIUM", "reason": "dlaczego ważne"}
  ],
  "svo_triples": [
    {"subject": "encja", "verb": "czasownik/relacja", "object": "wartość/encja", "context": "opcjonalny kontekst"}
  ],
  "cooccurrence_pairs": [
    {"entity1": "...", "entity2": "...", "reason": "dlaczego blisko"}
  ],
  "placement_instruction": "Krótka instrukcja rozmieszczenia encji w tekście (2-3 zdania)"
}

Dla svo_triples: wygeneruj 10-15 trójek Subject→Verb→Object które MODEL MUSI wyrazić w tekście.
Przykłady dla "jazda po alkoholu":
  {"subject": "jazda po alkoholu", "verb": "skutkuje", "object": "zakazem prowadzenia pojazdów 3-15 lat"}
  {"subject": "sąd", "verb": "orzeka obligatoryjnie", "object": "zakaz prowadzenia przy art. 178a §1"}
  {"subject": "stężenie alkoholu", "verb": "decyduje o kwalifikacji", "object": "przestępstwo vs wykroczenie (próg 0,5 promila)"}
  {"subject": "blokada alkoholowa", "verb": "umożliwia skrócenie", "object": "zakazu prowadzenia pojazdów"}
To są FAKTY MERYTORYCZNE które MUSZĄ znaleźć się w artykule — nie styl, nie encje ogólne."""


# ═══ v2.3: SEARCH VARIANT GENERATOR ═══
def _generate_search_variants(main_keyword: str, secondary_keywords: list = None) -> dict:
    """Generate all natural Polish search variants — main keyword + secondary.
    
    ONE LLM call replaces: _derive_entity_synonyms, _generate_entity_variants,
    _find_keyword_synonyms.
    
    Returns:
    {
        "fleksyjne": ["jazdy po alkoholu", ...],
        "peryfrazy": ["prowadzenie pod wpływem alkoholu", ...],
        "potoczne": ["jazda po pijaku", ...],
        "formalne": ["kierowanie pojazdem w stanie nietrzeźwości", ...],
        "intencja_info": ["co grozi za jazdę po alkoholu", ...],
        "intencja_transakcyjna": ["adwokat jazda po alkoholu", ...],
        "all_flat": [... all unique main variants ...],
        "secondary": {
            "blokada alkoholowa": ["blokadą alkoholową", "alkolock", ...],
            "art 178a": ["artykuł 178a kk", "przepis o jeździe po alkoholu", ...],
            ...
        }
    }
    
    Cost: ~$0.002-0.004 (one gpt-4.1-mini or Haiku call)
    """
    if not main_keyword or len(main_keyword) < 3:
        return {}

    # Build secondary section
    sec_list = []
    if secondary_keywords:
        main_lower = main_keyword.lower().strip()
        seen = {main_lower}
        for kw in secondary_keywords:
            name = (kw.get("keyword", "") if isinstance(kw, dict) else str(kw)).strip()
            if name and name.lower() not in seen:
                sec_list.append(name)
                seen.add(name.lower())
        sec_list = sec_list[:8]

    sec_block = ""
    sec_json_hint = ""
    if sec_list:
        sec_numbered = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(sec_list))
        sec_block = (
            f"\n\nDodatkowo, dla każdej z poniższych fraz podaj 3-5 wariantów "
            f"(fleksja + peryfrazy, naturalnie wymiennych w tekście):\n{sec_numbered}"
        )
        sec_json_hint = ', "secondary": {"fraza1": ["wariant1", "wariant2"], ...}'

    prompt = (
        f'Podaj wszystkie naturalne warianty frazy "{main_keyword}", '
        f'które Polak mógłby wpisać w Google.\n\n'
        f'Uwzględnij:\n'
        f'- warianty fleksyjne (odmiana przez przypadki, liczby)\n'
        f'- peryfrazy (dłuższe/krótsze sposoby powiedzenia tego samego)\n'
        f'- warianty potoczne i formalne\n'
        f'- frazy z intencją informacyjną (pytania, "co to", "ile", "jak")\n'
        f'- frazy z intencją transakcyjną (szukanie usługi/produktu)\n\n'
        f'Zasady:\n'
        f'- Tylko REALNE frazy które ludzie wpisują w Google\n'
        f'- Każda kategoria: 3-6 fraz\n'
        f'- NIE powtarzaj oryginalnej frazy bez zmian\n'
        f'- NIE wymyślaj sztucznych wariantów'
        f'{sec_block}\n\n'
        f'Odpowiedz TYLKO jako JSON (bez komentarzy, bez markdown):\n'
        f'{{"fleksyjne": ["..."], "peryfrazy": ["..."], "potoczne": ["..."], '
        f'"formalne": ["..."], "intencja_info": ["..."], "intencja_transakcyjna": ["..."]{sec_json_hint}}}'
    )

    def _parse_variants(raw: str) -> dict:
        raw = raw.strip().replace("```json", "").replace("```", "").strip()
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            raw = raw[start:end]
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # v67: Try to repair truncated JSON (common with max_tokens cutoff)
            # Strategy: close all open brackets/braces, then parse
            try:
                repaired = raw
                # Count unclosed structures
                open_brackets = repaired.count('[') - repaired.count(']')
                open_braces = repaired.count('{') - repaired.count('}')
                # Remove trailing comma or incomplete string
                repaired = repaired.rstrip()
                if repaired.endswith(','):
                    repaired = repaired[:-1]
                # If last char is a quote-less string start, remove it
                last_quote = repaired.rfind('"')
                if last_quote > 0:
                    # Check if the quote is unclosed (odd number of quotes)
                    if repaired[last_quote:].count('"') % 2 == 1:
                        repaired = repaired[:last_quote]
                        repaired = repaired.rstrip().rstrip(',')
                # Close structures
                repaired += ']' * max(0, open_brackets) + '}' * max(0, open_braces)
                data = json.loads(repaired)
                logger.info(f"[SEARCH_VARIANTS] ✅ JSON repair successful (closed {open_brackets}[ {open_braces}{{)")
            except (json.JSONDecodeError, Exception):
                return {}
        if not isinstance(data, dict):
            return {}

        main_lower = main_keyword.lower().strip()
        result = {}
        all_flat = []

        for key in ("fleksyjne", "peryfrazy", "potoczne", "formalne",
                     "intencja_info", "intencja_transakcyjna"):
            variants = data.get(key, [])
            if not isinstance(variants, list):
                continue
            clean = [str(v).strip() for v in variants
                     if str(v).strip() and str(v).strip().lower() != main_lower
                     and 3 <= len(str(v).strip()) <= 120]
            if clean:
                result[key] = clean[:6]
                all_flat.extend(clean[:6])

        # Deduplicated flat list
        seen = set()
        unique_flat = []
        for v in all_flat:
            vl = v.lower()
            if vl not in seen:
                seen.add(vl)
                unique_flat.append(v)
        result["all_flat"] = unique_flat

        # Parse secondary keywords
        sec_data = data.get("secondary", {})
        if isinstance(sec_data, dict) and sec_data:
            sec_result = {}
            for key, variants in sec_data.items():
                key_clean = str(key).strip()
                # Match by name or by index ("1", "2")
                matched_name = key_clean
                if key_clean.isdigit():
                    idx = int(key_clean) - 1
                    if 0 <= idx < len(sec_list):
                        matched_name = sec_list[idx]
                if isinstance(variants, list):
                    clean = [str(v).strip() for v in variants
                             if str(v).strip() and len(str(v).strip()) >= 3
                             and str(v).strip().lower() != matched_name.lower()]
                    if clean:
                        sec_result[matched_name] = clean[:6]
            if sec_result:
                result["secondary"] = sec_result

        return result

    # Try OpenAI (cheapest)
    if OPENAI_API_KEY and OPENAI_AVAILABLE:
        try:
            import openai as _openai
            _client = _openai.OpenAI(api_key=OPENAI_API_KEY)
            resp = _client.chat.completions.create(
                model="gpt-4.1-mini",
                max_tokens=1200 if sec_list else 700,
                temperature=0.3,
                messages=[{"role": "user", "content": prompt}],
                timeout=25.0
            )
            raw = resp.choices[0].message.content.strip()
            result = _parse_variants(raw)
            if result:
                total = len(result.get("all_flat", []))
                sec_count = len(result.get("secondary", {}))
                logger.info(f"[SEARCH_VARIANTS] ✅ OpenAI: {total} main + {sec_count} secondary dla '{main_keyword}'")
                return result
            else:
                logger.warning(f"[SEARCH_VARIANTS] OpenAI returned unparseable: {raw[:120]}")
        except Exception as e:
            logger.warning(f"[SEARCH_VARIANTS] OpenAI error: {e}")

    # Fallback: Claude Haiku
    if ANTHROPIC_API_KEY:
        try:
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1200 if sec_list else 700,
                temperature=0.3,
                messages=[{"role": "user", "content": prompt}],
                timeout=25.0
            )
            result = _parse_variants(resp.content[0].text.strip())
            if result:
                total = len(result.get("all_flat", []))
                sec_count = len(result.get("secondary", {}))
                logger.info(f"[SEARCH_VARIANTS] ✅ Haiku: {total} main + {sec_count} secondary dla '{main_keyword}'")
                return result
        except Exception as e:
            logger.warning(f"[SEARCH_VARIANTS] Haiku error: {e}")

    # v67: Deterministic fallback — generate basic Polish inflections without LLM
    logger.warning(f"[SEARCH_VARIANTS] All LLM providers failed for '{main_keyword}', using deterministic fallback")
    return _deterministic_variant_fallback(main_keyword, sec_list)


def _deterministic_variant_fallback(main_keyword: str, secondary_keywords: list = None) -> dict:
    """Generate basic Polish variant hints when LLM fails.
    
    Uses simple suffix rules for common Polish inflection patterns.
    Not perfect, but gives the model SOMETHING to rotate with.
    """
    result = {}
    all_flat = []
    mk = main_keyword.strip()
    mk_lower = mk.lower()
    words = mk_lower.split()
    
    # Basic Polish noun/adjective inflection patterns
    _PL_SUFFIXES = {
        # nominative → other cases (approximate)
        "ów": ["om", "ami", "ach"],
        "ów ": ["om ", "ami ", "ach "],
        "ie": ["iu", "iem"],
        "a": ["ę", "y", "ie", "ą"],
        "o": ["a", "u", "em"],
        "y": ["ów", "om", "ami"],
        "i": ["ów", "om", "ami"],
        "ść": ["ści", "ścią"],
        "ek": ["ku", "kiem"],
    }
    
    fleksyjne = []
    # Try to generate inflected forms of the last significant word
    for suffix, replacements in _PL_SUFFIXES.items():
        if words[-1].endswith(suffix):
            base = words[-1][:-len(suffix)]
            for repl in replacements:
                variant_words = words[:-1] + [base + repl]
                variant = " ".join(variant_words)
                if variant != mk_lower and variant not in fleksyjne:
                    fleksyjne.append(variant)
            break
    
    # For "jak + verb" patterns, add noun forms
    if len(words) >= 2 and words[0] in ("jak", "co", "czy", "ile", "kiedy"):
        # Drop the question word for a declarative variant
        declarative = " ".join(words[1:])
        if declarative != mk_lower:
            fleksyjne.append(declarative)
        # Add "sposoby na" variant
        peryfrazy_base = " ".join(words[1:])
        all_flat.append(f"sposoby na {peryfrazy_base}")
    
    if fleksyjne:
        result["fleksyjne"] = fleksyjne[:5]
        all_flat.extend(fleksyjne[:5])
    
    # Generate basic periphrases
    peryfrazy = []
    for w in words:
        if len(w) >= 6:
            # Just note the word can be replaced — gives the model a hint
            pass
    if peryfrazy:
        result["peryfrazy"] = peryfrazy[:4]
        all_flat.extend(peryfrazy[:4])
    
    # Secondary keywords — generate case variants
    if secondary_keywords:
        sec_result = {}
        for kw in secondary_keywords[:8]:
            kw_clean = kw.strip() if isinstance(kw, str) else str(kw).strip()
            kw_words = kw_clean.lower().split()
            variants = []
            if kw_words:
                last = kw_words[-1]
                for suffix, replacements in _PL_SUFFIXES.items():
                    if last.endswith(suffix):
                        base = last[:-len(suffix)]
                        for repl in replacements[:2]:
                            v = " ".join(kw_words[:-1] + [base + repl])
                            if v != kw_clean.lower():
                                variants.append(v)
                        break
            if variants:
                sec_result[kw_clean] = variants[:3]
        if sec_result:
            result["secondary"] = sec_result
    
    # Deduplicated flat list
    seen = set()
    unique_flat = []
    for v in all_flat:
        vl = v.lower()
        if vl not in seen and vl != mk_lower:
            seen.add(vl)
            unique_flat.append(v)
    result["all_flat"] = unique_flat
    
    total = len(unique_flat)
    sec_count = len(result.get("secondary", {}))
    logger.info(f"[SEARCH_VARIANTS] ⚠️ Deterministic fallback: {total} main + {sec_count} secondary dla '{main_keyword}'")
    return result


def _generate_topical_entities(main_keyword: str, h2_plan: list = None) -> dict:
    """Generate topical entities for keyword using fast LLM call.
    
    Returns dict with: primary_entity, secondary_entities, cooccurrence_pairs,
    placement_instruction. Returns empty dict on failure.
    
    Uses gpt-4.1-mini for speed (~1-2s) and cost efficiency.
    """
    if not OPENAI_API_KEY:
        logger.warning("[TOPICAL_ENTITIES] No OpenAI API key, skipping")
        return {}
    
    try:
        import openai as _openai
        client = _openai.OpenAI(api_key=OPENAI_API_KEY)
        
        h2_context = ""
        if h2_plan:
            h2_context = f"\nPlan H2 artykułu: {' | '.join(h2_plan[:8])}"
        
        user_msg = f"Temat: \"{main_keyword}\"{h2_context}\n\nWygeneruj topical entities dla tego tematu."
        
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": _TOPICAL_ENTITY_PROMPT},
                {"role": "user", "content": user_msg}
            ],
            temperature=0.3,
            max_tokens=1200,
            timeout=15
        )
        
        raw = response.choices[0].message.content.strip()
        # Clean potential markdown fences
        raw = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(raw)
        
        if not isinstance(result, dict) or "primary_entity" not in result:
            logger.warning(f"[TOPICAL_ENTITIES] Invalid response structure")
            return {}
        
        logger.info(f"[TOPICAL_ENTITIES] ✅ Generated {len(result.get('secondary_entities', []))} topical entities for '{main_keyword}'")
        return result
        
    except json.JSONDecodeError as e:
        logger.warning(f"[TOPICAL_ENTITIES] JSON parse error: {e}")
        return {}
    except Exception as e:
        logger.warning(f"[TOPICAL_ENTITIES] Error: {e}")
        return {}


def _compute_topical_salience(topical_result: dict) -> dict:
    """
    Compute salience for each secondary entity based on structural signals.
    
    Inspired by Google patent US20150278366 (Identifying topical entities):
    - Co-occurrence count = edge weight proxy (patent: "more times two entities
      associated with same resource → greater edge weight")
    - SVO subject count = directed edge proxy (patent: centrality via outgoing edges)
    - Type weight = domain specificity signal
    - Ngram HIGH importance = frequency/relevance signal
    - Position = LLM orders by topic centrality, slight decay
    
    Returns dict: {entity_name_lower: salience_float}
    """
    TYPE_WEIGHT = {
        "LAW": 0.15, "PROCESS": 0.10, "DEVICE": 0.08,
        "CONCEPT": 0.05, "PERSON": 0.05, "ORGANIZATION": 0.05, "EVENT": 0.05
    }
    MAX_SALIENCE = 0.82  # Primary entity is 0.85 — secondaries cap below it

    entities = topical_result.get("secondary_entities", [])
    cooc = topical_result.get("cooccurrence_pairs", [])
    svo = topical_result.get("svo_triples", [])
    ngrams = topical_result.get("semantic_ngrams", [])

    # Co-occurrence count per entity
    cooc_counts = {}
    for pair in cooc:
        for field in ("entity1", "entity2"):
            name = (pair.get(field) or "").lower().strip()
            if name:
                cooc_counts[name] = cooc_counts.get(name, 0) + 1

    # SVO subject count (subject = central/active node)
    svo_subjects = {}
    for triple in svo:
        subj = (triple.get("subject") or "").lower().strip()
        if subj:
            svo_subjects[subj] = svo_subjects.get(subj, 0) + 1

    # HIGH-importance ngrams set
    high_ngrams = set(
        (ng.get("phrase") or "").lower()
        for ng in ngrams
        if isinstance(ng, dict) and ng.get("importance") == "HIGH"
    )

    max_cooc = max(cooc_counts.values(), default=1)
    max_svo = max(svo_subjects.values(), default=1)

    salience_map = {}
    for i, ent in enumerate(entities):
        name = (ent.get("text") or "")
        name_lower = name.lower().strip()
        if not name_lower:
            continue
        etype = ent.get("type", "CONCEPT")

        # Base: position decay (0.75 → 0.45 across 16 entities)
        base = max(0.45, 0.75 - i * 0.018)

        # Co-occurrence signal: 0–0.15 (patent: edge weights)
        cooc_score = (cooc_counts.get(name_lower, 0) / max_cooc) * 0.15

        # SVO subject signal: 0–0.10 (patent: outgoing edges = centrality)
        svo_score = (svo_subjects.get(name_lower, 0) / max_svo) * 0.10

        # Type weight: domain-specific types are more central
        type_score = TYPE_WEIGHT.get(etype, 0.05)

        # Ngram HIGH importance: entity appears in core phrases of topic
        ngram_score = 0.05 if any(name_lower in ng for ng in high_ngrams) else 0

        total = round(min(MAX_SALIENCE, base + cooc_score + svo_score + type_score + ngram_score), 3)
        salience_map[name_lower] = total

    return salience_map


def _topical_to_entity_list(topical_result: dict, main_keyword: str = "") -> list:
    """Convert topical entity result to standard entity list format.
    
    Returns list of dicts compatible with clean_entities / ai_topical format:
    [{"text": "...", "type": "...", "eav": "...", "source": "topical_generator"}]
    
    v61 FIX: primary_entity is ALWAYS overridden by main_keyword.
    LLMs sometimes choose "more precise" synonyms (e.g. "stan nietrzeźwości" for "jazda po alkoholu").
    This is wrong - the primary entity must match the keyword the user is targeting.
    """
    if not topical_result:
        return []
    
    entities = []
    
    # Primary entity: ALWAYS use main_keyword if provided
    # The LLM may generate a "more precise" form but that breaks entity salience targeting
    primary = topical_result.get("primary_entity", {})
    primary_text = main_keyword.strip() if main_keyword else (primary.get("text", "") if primary else "")
    if primary_text:
        entities.append({
            "text": primary_text,
            "entity": primary_text,
            "type": primary.get("type", "CONCEPT") if primary else "CONCEPT",
            "eav": primary.get("eav", "") if primary else "",
            "source": "topical_generator",
            "is_primary": True
        })
    
    # Compute structural salience for secondary entities (patent-inspired)
    salience_map = _compute_topical_salience(topical_result)

    # Secondary entities — expanded to 20
    for ent in topical_result.get("secondary_entities", [])[:20]:
        if ent and ent.get("text"):
            name = ent["text"]
            computed_sal = salience_map.get(name.lower().strip(), 0.5)
            entities.append({
                "text": name,
                "entity": name,
                "type": ent.get("type", "CONCEPT"),
                "eav": ent.get("eav", ""),
                "salience": computed_sal,
                "source": "topical_generator",
                "is_primary": False
            })
    
    return entities


def _topical_to_ngrams(topical_result: dict) -> list:
    """Extract semantic_ngrams from topical entity result.
    
    Returns list of dicts in clean_ngrams format:
    [{"ngram": "...", "freq_median": 1, "freq_max": 3, "site_distribution": "1/5", "source": "topical_generator"}]
    """
    if not topical_result:
        return []
    
    ngrams = []
    for ng in topical_result.get("semantic_ngrams", [])[:15]:
        if not ng:
            continue
        phrase = ng.get("phrase", "") if isinstance(ng, dict) else str(ng)
        if not phrase or len(phrase) < 4:
            continue
        importance = (ng.get("importance", "MEDIUM") if isinstance(ng, dict) else "MEDIUM").upper()
        # Map importance to frequency targets
        freq_median = 3 if importance == "HIGH" else 1
        freq_max = 6 if importance == "HIGH" else 3
        ngrams.append({
            "ngram": phrase,
            "freq_median": freq_median,
            "freq_max": freq_max,
            "site_distribution": "2/5",  # treat as present in 2 competitors
            "source": "topical_generator",
            "importance": importance,
        })
    return ngrams



def _topical_to_eav(topical_result: dict) -> list:
    """Extract EAV triples from topical entity result for batch prompt injection.
    
    Returns list of dicts:
    [{"entity": "kodeks karny", "attribute": "penalizuje", "value": "jazdę po alkoholu art. 178a", "type": "CONCEPT"}]
    """
    if not topical_result:
        return []
    
    eav_list = []
    
    # Primary entity EAV
    primary = topical_result.get("primary_entity", {})
    if primary and primary.get("eav"):
        eav_raw = primary["eav"]
        parts = [p.strip() for p in eav_raw.split("→")]
        if len(parts) >= 3:
            eav_list.append({
                "entity": primary.get("text", parts[0]),
                "attribute": parts[1],
                "value": parts[2],
                "type": primary.get("type", "CONCEPT"),
                "is_primary": True,
            })
    
    # Secondary entities EAV
    for ent in topical_result.get("secondary_entities", [])[:18]:
        if not ent or not ent.get("eav"):
            continue
        eav_raw = ent["eav"]
        parts = [p.strip() for p in eav_raw.split("→")]
        if len(parts) >= 3:
            eav_list.append({
                "entity": ent.get("text", parts[0]),
                "attribute": parts[1],
                "value": parts[2],
                "type": ent.get("type", "CONCEPT"),
                "is_primary": False,
            })
    
    return eav_list


def _topical_to_svo(topical_result: dict) -> list:
    """Extract SVO triples from topical entity result.
    
    Returns list of dicts:
    [{"subject": "sąd", "verb": "orzeka obligatoryjnie", "object": "zakaz prowadzenia", "context": "przy art. 178a §1"}]
    """
    if not topical_result:
        return []
    
    svo_list = []
    for triple in topical_result.get("svo_triples", [])[:15]:
        if not isinstance(triple, dict):
            continue
        subj = triple.get("subject", "")
        verb = triple.get("verb", "")
        obj = triple.get("object", "")
        if subj and verb and obj:
            svo_list.append({
                "subject": subj,
                "verb": verb,
                "object": obj,
                "context": triple.get("context", ""),
            })
    return svo_list


def _topical_to_placement_instruction(topical_result: dict, main_keyword: str) -> str:
    """Build placement instruction from topical entities.
    
    Generates structured placement rules following entity salience research:
    - Primary entity → H1 + first sentence
    - Secondary entities → H2 + first paragraphs
    - E-A-V triples → explicit description in text
    - Co-occurrence pairs → same paragraph
    """
    if not topical_result:
        return ""
    
    lines = []
    primary = topical_result.get("primary_entity", {})
    secondary = topical_result.get("secondary_entities", [])[:8]
    cooc = topical_result.get("cooccurrence_pairs", [])[:5]
    
    # Primary entity
    if primary and primary.get("text"):
        p_text = primary["text"]
        lines.append(f'🎯 ENCJA GŁÓWNA: "{p_text}"')
        lines.append(f'   → W tytule H1 i w pierwszym zdaniu artykułu')
        lines.append(f'   → Jako PODMIOT zdań (nie dopełnienie)')
        if primary.get("eav"):
            lines.append(f'   → Opisz wprost: {primary["eav"]}')
    
    # First paragraph entities
    fp_ents = [e["text"] for e in secondary[:3] if e.get("text")]
    if fp_ents:
        lines.append(f'')
        lines.append(f'📌 PIERWSZY AKAPIT (100 słów): Wprowadź razem z encją główną:')
        lines.append(f'   {", ".join(fp_ents)}')
    
    # H2 entities
    h2_ents = [e for e in secondary if e.get("text")]
    if h2_ents:
        lines.append(f'')
        lines.append(f'📋 ENCJE TEMATYCZNE (do rozmieszczenia w tekście):')
        for e in h2_ents:
            eav = f': {e["eav"]}' if e.get("eav") else ""
            lines.append(f'   • "{e["text"]}" ({e.get("type", "CONCEPT")}){eav}')
    
    # Co-occurrence pairs
    if cooc:
        lines.append(f'')
        lines.append(f'🔗 CO-OCCURRENCE (umieść w TYM SAMYM akapicie):')
        for pair in cooc:
            e1 = pair.get("entity1", "")
            e2 = pair.get("entity2", "")
            reason = pair.get("reason", "")
            if e1 and e2:
                lines.append(f'   • "{e1}" + "{e2}"{" (" + reason + ")" if reason else ""}')
    
    return "\n".join(lines)


def _topical_to_cooccurrence(topical_result: dict) -> list:
    """Extract co-occurrence pairs in standard format."""
    if not topical_result:
        return []
    pairs = []
    for pair in topical_result.get("cooccurrence_pairs", [])[:8]:
        if pair.get("entity1") and pair.get("entity2"):
            pairs.append({
                "entity1": pair["entity1"],
                "entity2": pair["entity2"],
                "source": "topical_generator"
            })
    return pairs

def _filter_h2_patterns(patterns):
    """Filter H2 patterns: remove CSS garbage AND navigation elements."""
    # v49: Navigation terms that appear as H2 on scraped pages (exact match only)
    _NAV_H2_EXACT = {
        "wyszukiwarka", "nawigacja", "moje strony", "mapa serwisu", "mapa strony",
        "dostępność", "regulamin", "newsletter", "social media", "archiwum",
        "logowanie", "rejestracja", "kontakt", "o nas", "strona główna",
        "menu główne", "szukaj", "przydatne linki", "informacje", "stopka", "cookie",
    }
    # Multi-word nav phrases: these ARE safe for partial/substring matching
    _NAV_H2_PHRASES = {
        "biuletyn informacji publicznej", "redakcja serwisu", "nota prawna",
        "polityka prywatności", "deklaracja dostępności", "komenda miejska",
        "komenda powiatowa", "inne wersje portalu", "mapa serwisu",
    }
    if not patterns:
        return []
    clean = []
    for p in patterns:
        text = p if isinstance(p, str) else (p.get("pattern", "") if isinstance(p, dict) else str(p))
        if not text or len(text) <= 3:
            continue
        t_lower = text.strip().lower()
        # Skip CSS garbage
        if _is_css_garbage(text):
            continue
        # v49: Skip exact-match navigation H2s
        if t_lower in _NAV_H2_EXACT:
            continue
        # Skip if contains multi-word nav phrase (safe partial match)
        if any(phrase in t_lower for phrase in _NAV_H2_PHRASES):
            continue
        # Skip very short generic H2s
        if len(text.strip()) < 5:
            continue
        clean.append(p)
    # v60: Deduplicate H2 patterns (case-insensitive)
    seen = set()
    deduped = []
    for p in clean:
        text = p if isinstance(p, str) else (p.get("pattern", "") if isinstance(p, dict) else str(p))
        key = text.strip().lower()
        if key not in seen:
            seen.add(key)
            deduped.append(p)
    return deduped


def _filter_cooccurrence(pairs):
    """Remove co-occurrence pairs where either entity is CSS/nav garbage."""
    if not pairs:
        return []
    clean = []
    for pair in pairs:
        if isinstance(pair, dict):
            e1 = pair.get("entity_1", pair.get("entity1", ""))
            e2 = pair.get("entity_2", pair.get("entity2", ""))
            if isinstance(e1, list) and len(e1) >= 2:
                e1, e2 = str(e1[0]), str(e1[1])
            if not _is_css_garbage(str(e1)) and not _is_css_garbage(str(e2)):
                clean.append(pair)
        elif isinstance(pair, str):
            if not _is_css_garbage(pair):
                clean.append(pair)
    return clean


def _sanitize_placement_instruction(text):
    """Remove lines from placement instruction that reference garbage entities."""
    if not text or not isinstance(text, str):
        return ""
    lines = text.split("\n")
    clean_lines = []
    for line in lines:
        quoted = _re.findall(r'"([^"]+)"', line)
        has_garbage = any(_is_css_garbage(q) for q in quoted)
        if has_garbage:
            continue
        # v50.7 FIX 39: Also check unquoted entity-like words on the line
        # Placement lines like "📎 ENCJE: A7FF, bluish, vivid" have no quotes
        line_lower = line.lower()
        # Check for hex color codes in the line
        hex_matches = _re.findall(r'\b[A-Fa-f0-9]{4,8}\b', line)
        if hex_matches and not any(c.isalpha() and c.lower() not in 'abcdef' for m in hex_matches for c in m):
            # Line contains hex color codes with no other alpha → suspicious
            pure_hex = [m for m in hex_matches if _re.match(r'^[0-9A-Fa-f]{4,8}$', m)]
            if len(pure_hex) >= 2:
                continue  # Multiple hex codes → CSS color line
        # v50.7: Check for Font Awesome references
        if 'font awesome' in line_lower or 'fontawesome' in line_lower:
            continue
        # v50.7: Check for CSS property patterns anywhere in the line
        if any(css_pat in line_lower for css_pat in [
            'placeholder{', 'relative;', 'serif;', '{color', 'display:', 
            'font-family', '@font-face', 'woff2', '.woff', '.ttf',
        ]):
            continue
        # v50.4: Filter lines where a PERSON entity appears alongside a brand
        if quoted and any(_is_brand_entity(q) for q in quoted):
            non_brand_quoted = [q for q in quoted if not _is_brand_entity(q)]
            line_lower = line.lower()
            if "person" in line_lower and non_brand_quoted:
                continue  # Skip: this is a brand contact person
        # v50.4: Filter relation lines that are scraped sentence fragments
        if "→" in line:
            parts = line.split("→")
            if len(parts) >= 3:
                relation_value = parts[-1].strip()
                if len(relation_value.split()) > 8:
                    continue
        clean_lines.append(line)
    result = "\n".join(clean_lines).strip()
    # v50.4: If >60% of instruction was garbage, data is too contaminated
    if len(result) < len(text) * 0.4:
        return ""
    return result


# ============================================================
# TOPICAL ENTITY FILTERS (v61)
# ============================================================

# Zaimki wskazujące i nieokreślone które wskazują, że fraza to fragment zdania, nie encja
_NGRAM_PRONOUN_FRAGMENTS = {
    "dana", "danej", "danego", "danemu", "danym",
    "innej", "innego", "innemu", "innym", "inni", "inne", "inny",
    "tej", "tego", "temu", "tą", "tym",
    "każdej", "każdego", "każdemu", "każdym", "każda",
    "takiej", "takiego", "takim", "taka",
    "pewnej", "pewnego", "pewnym",
    "swojej", "swojego", "swoim", "swojemu",
    "własnej", "własnego", "własnym",
}

# Przyimki polskie — fraza startująca od przyimka to fragment zdania, nie encja
_POLISH_PREPOSITIONS_START = {
    "w ", "na ", "do ", "ze ", "z ", "od ", "dla ", "przy ",
    "przez ", "po ", "za ", "nad ", "pod ", "przed ", "między ",
    "wokół ", "wobec ", "według ", "wzdłuż ", "oprócz ", "poza ",
    "pomimo ", "mimo ", "dzięki ", "podczas ", "wśród ",
    "szczególności ", "względu ", "uwagi ", "podstawie ",
}

# Stopwords same w sobie nie tworzą encji
_STOPWORD_ONLY_TOKENS = {
    "osoby", "osoba", "osobą", "osobie", "stan", "stanu",
    "przypadek", "przypadku", "przypadki",
    "życiu", "życia", "życie",
    "zachowania", "zachowanie", "zachowaniu",
}


def _is_ngram_entity(phrase: str) -> bool:
    """Sprawdza czy fraza to prawdziwa encja topicalna (nie fragment n-gramowy).
    
    Zwraca False dla:
    - fraz zaczynających się od przyimka
    - fraz ze zaimkami wskazującymi/nieokreślonymi
    - zbyt krótkich lub zbyt generycznych fraz
    - konkretnych liczebnikowych przykładów (np. "28-letni mężczyzna")
    """
    if not phrase or not isinstance(phrase, str):
        return False
    phrase = phrase.strip()
    p_lower = phrase.lower()
    
    # Za krótka
    if len(phrase) < 4:
        return False
    
    # Zaczyna się od przyimka polskiego
    for prep in _POLISH_PREPOSITIONS_START:
        if p_lower.startswith(prep):
            return False
    
    # Zawiera zaimek wskazujący/nieokreślony jako PIERWSZE słowo
    first_word = p_lower.split()[0] if p_lower.split() else ""
    if first_word in _NGRAM_PRONOUN_FRAGMENTS:
        return False
    
    # Fraza to wyłącznie stopword + rzeczownik (bez znaczącej treści)
    words = p_lower.split()
    if len(words) == 2 and words[0] in _NGRAM_PRONOUN_FRAGMENTS:
        return False
    if len(words) == 2 and words[1] in _STOPWORD_ONLY_TOKENS and words[0] in _NGRAM_PRONOUN_FRAGMENTS:
        return False
    
    # Konkretny przykład liczbowy: "28-letni mężczyzna", "3-osobowa rodzina"
    import re as _re2
    if _re2.match(r'^\d+-', phrase):
        return False
    
    # Urwany celownik/dopełniacz kończący się na typowe końcówki bez kontekstu
    # Blokuj tylko gdy pierwsza słowo jest zaimkiem ORAZ ostatnie jest generycznym stopwordem
    # "dana osoba" → False, ale "małżonek osoby" → True (małżonek nie jest zaimkiem)
    if len(words) <= 2 and words[0] in _NGRAM_PRONOUN_FRAGMENTS and words[-1] in _STOPWORD_ONLY_TOKENS:
        return False
    
    return True


def _filter_must_cover_concepts(concepts: list) -> list:
    """Filtruje listę must_cover_concepts usuwając n-gramowe śmieci.
    
    Zachowuje tylko prawdziwe encje topicalne.
    """
    if not concepts:
        return []
    clean = []
    for c in concepts:
        text = c.get("text", c.get("entity", "")) if isinstance(c, dict) else str(c)
        text = text.strip()
        if not text:
            continue
        if _is_css_garbage(text):
            continue
        if not _is_ngram_entity(text):
            continue
        clean.append(c)
    return clean


def _build_concept_instruction_from_topical(topical_result: dict, main_keyword: str) -> str:
    """Buduje concept_instruction z wyników topical entity generatora.
    
    Zamiast surowych n-gramów z API — grupuje encje wg typu semantycznego
    i formatuje jako czytelną, merytoryczną instrukcję dla modelu.
    
    Zwraca pusty string jeśli brak danych.
    """
    if not topical_result:
        return ""
    
    secondary = topical_result.get("secondary_entities", [])
    ngrams = topical_result.get("semantic_ngrams", [])
    cooc = topical_result.get("cooccurrence_pairs", [])
    
    if not secondary and not ngrams:
        return ""
    
    # Grupuj encje wtórne wg typu
    type_groups = {}
    type_labels = {
        "LAW": "Przepisy",
        "CONCEPT": "Pojęcia prawne" if any(t in main_keyword.lower() for t in ["prawo", "prawny", "sąd", "ustawa", "ubezwłas", "kodeks", "art.", "paragraf"]) else "Kluczowe pojęcia",
        "PROCESS": "Procesy i procedury",
        "PERSON": "Osoby i role",
        "ORGANIZATION": "Instytucje",
        "UNIT": "Jednostki",
        "EVENT": "Zdarzenia",
        "DEVICE": "Substancje / narzędzia",
        "OTHER": "Inne",
    }
    
    for ent in secondary[:16]:
        if not isinstance(ent, dict):
            continue
        text = ent.get("text", "").strip()
        if not text or not _is_ngram_entity(text):
            continue
        etype = ent.get("type", "CONCEPT").upper()
        if etype not in type_labels:
            etype = "OTHER"
        if etype not in type_groups:
            type_groups[etype] = []
        type_groups[etype].append(text)
    
    if not type_groups and not ngrams:
        return ""
    
    lines = [f"📚 ENCJE TEMATYCZNE dla \"{main_keyword}\" (wpleć naturalnie — odmieniaj przez przypadki):"]
    lines.append("")
    
    # Encje pogrupowane wg typu
    type_order = ["LAW", "CONCEPT", "PROCESS", "PERSON", "ORGANIZATION", "UNIT", "EVENT", "DEVICE", "OTHER"]
    for etype in type_order:
        if etype in type_groups and type_groups[etype]:
            label = type_labels.get(etype, etype)
            entities_str = " | ".join(type_groups[etype][:6])
            lines.append(f"[{label}]: {entities_str}")
    
    # N-gramy semantyczne jako "wyrażenia obowiązkowe"
    high_ngrams = [ng for ng in ngrams if isinstance(ng, dict) and ng.get("importance") == "HIGH"]
    if high_ngrams:
        lines.append("")
        phrases = [ng.get("phrase", "") for ng in high_ngrams[:6] if ng.get("phrase")]
        if phrases:
            lines.append(f"WYRAŻENIA KLUCZOWE: {' | '.join(phrases)}")
    
    # Co-occurrence pairs
    if cooc:
        lines.append("")
        lines.append("RAZEM W JEDNYM AKAPICIE (silny sygnał semantyczny):")
        for pair in cooc[:4]:
            e1 = pair.get("entity1", "")
            e2 = pair.get("entity2", "")
            if e1 and e2:
                lines.append(f"  • {e1} + {e2}")
    
    return "\n".join(lines)


# ============================================================
# CONFIG
# ============================================================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)

# ============================================================
# RATE LIMITING (in-memory, per-IP)
# ============================================================
_rate_limit_store = {}
_RATE_LIMIT_WINDOW = 60  # seconds
_RATE_LIMIT_MAX_API = int(os.environ.get("RATE_LIMIT_MAX", "30"))  # /api/ endpoints per minute
_rate_limit_last_cleanup = 0  # v68 M15: periodic cleanup

@app.before_request
def _rate_limit():
    """Per-IP rate limiting for /api/ endpoints (except health/stream)."""
    if not request.path.startswith("/api/"):
        return
    if request.path in ("/api/health", "/api/engines") or "/stream/" in request.path:
        return
    ip = request.remote_addr or "unknown"
    now = time.time()
    timestamps = _rate_limit_store.get(ip, [])
    _rate_limit_store[ip] = [t for t in timestamps if now - t < _RATE_LIMIT_WINDOW]
    if len(_rate_limit_store[ip]) >= _RATE_LIMIT_MAX_API:
        return jsonify({"error": "Too many requests", "retry_after": _RATE_LIMIT_WINDOW}), 429
    _rate_limit_store[ip].append(now)
    # v68 M15: Periodically purge stale IPs (every 5 min)
    global _rate_limit_last_cleanup
    if now - _rate_limit_last_cleanup > 300:
        _rate_limit_last_cleanup = now
        stale = [k for k, v in _rate_limit_store.items() if not v or now - max(v) > _RATE_LIMIT_WINDOW]
        for k in stale:
            del _rate_limit_store[k]

BRAJEN_API = os.environ.get("BRAJEN_API_URL", "https://master-seo-api.onrender.com")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
# v68 H1: Thread-local model override — prevents race condition between concurrent SSE streams
import threading as _threading
_thread_local = _threading.local()

def _get_anthropic_model():
    """Return thread-local model override, or global default."""
    return getattr(_thread_local, "anthropic_model", None) or ANTHROPIC_MODEL

def _set_anthropic_model(model):
    """Set thread-local model override for current workflow."""
    _thread_local.anthropic_model = model

def _clear_anthropic_model():
    """Clear thread-local override, revert to global."""
    _thread_local.anthropic_model = None
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.2")

REQUEST_TIMEOUT = 120
HEAVY_REQUEST_TIMEOUT = 360  # For editorial_review, final_review, full_article (6 min)
MAX_RETRIES = 3
RETRY_DELAYS = [5, 15, 30]

# v50.7 FIX 48: Auto-retry for transient LLM API errors (429 quota, 529 overloaded, 503 unavailable)
LLM_RETRY_MAX = 3
LLM_RETRY_DELAYS = [10, 20, 30]  # v68 M18: capped at 30s (was 60s — blocks SSE generator)
LLM_RETRY_DELAYS_529 = [5, 10, 20, 30]   # v68 M18: capped at 30s (was 60s)
LLM_RETRYABLE_CODES = {429, 503, 529}
LLM_529_MAX_RETRIES = 4  # 4 retry dla 529 — daje Anthropic czas na odciążenie

# Circuit breaker: max total LLM retries per workflow to prevent retry storms
# brajen_call(3 retries) × _llm_call_with_retry(3 retries) × batch loop(4 attempts) = 36 max
# Circuit breaker caps this at 15 total retries per job
_CIRCUIT_BREAKER_MAX = 15
_circuit_breaker_counts = {}  # job_id -> retry_count

def _circuit_breaker_check(job_id: str) -> bool:
    """Return True if circuit breaker tripped (too many retries)."""
    count = _circuit_breaker_counts.get(job_id, 0)
    return count >= _CIRCUIT_BREAKER_MAX

def _circuit_breaker_increment(job_id: str):
    """Increment retry count for a job."""
    _circuit_breaker_counts[job_id] = _circuit_breaker_counts.get(job_id, 0) + 1

def _circuit_breaker_reset(job_id: str):
    """Reset retry counter for a job (call when job completes or is abandoned)."""
    _circuit_breaker_counts.pop(job_id, None)

def _llm_call_with_retry(fn, *args, **kwargs):
    """Wrap LLM API call with retry on transient errors.
    
    Retries on: 429 (rate limit/quota), 503 (unavailable), 529 (overloaded).
    Does NOT retry on: 400 (bad request), 401 (auth), 404, etc.
    """
    last_error = None
    _max_attempts = max(LLM_RETRY_MAX, LLM_529_MAX_RETRIES) + 1
    for attempt in range(_max_attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_error = e
            # Extract HTTP status code from various API client exceptions
            status = getattr(e, 'status_code', None) or getattr(e, 'status', None)
            if status is None:
                # anthropic.APIStatusError / openai.APIStatusError store it in .status_code
                err_str = str(e)
                for code in LLM_RETRYABLE_CODES:
                    if str(code) in err_str:
                        status = code
                        break
            
            if status in LLM_RETRYABLE_CODES:
                # v52.4: 529 = serwer przeciążony — fail fast i przejdź do fallback modelu
                is_529 = (status == 529)
                max_r = LLM_529_MAX_RETRIES if is_529 else LLM_RETRY_MAX
                delays = LLM_RETRY_DELAYS_529 if is_529 else LLM_RETRY_DELAYS
                if attempt < max_r:
                    delay = delays[min(attempt, len(delays) - 1)]
                    logger.warning(f"[LLM_RETRY] {status} attempt {attempt+1}/{max_r+1}, retry in {delay}s: {str(e)[:120]}")
                    time.sleep(delay)
                    continue
            raise  # Non-retryable or max retries exceeded

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================
# CSRF PROTECTION
# ============================================================
def _generate_csrf_token():
    """Generate a per-session CSRF token."""
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    return session['_csrf_token']


app.jinja_env.globals['csrf_token'] = _generate_csrf_token


def _check_csrf_token():
    """Validate CSRF token for state-changing requests."""
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return
    # Skip CSRF for API endpoints that use JSON bodies (SameSite cookie protects these)
    if request.is_json:
        return
    token = request.form.get('csrf_token')
    if not token or token != session.get('_csrf_token'):
        from flask import abort
        abort(403)


@app.before_request
def csrf_protect():
    _check_csrf_token()


# ============================================================
# HTTP SECURITY HEADERS
# ============================================================
@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    )
    return response

# Auth: require env vars, no hardcoded fallbacks
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
APP_USERNAME = os.environ.get("APP_USERNAME", "")
if not APP_PASSWORD or not APP_USERNAME:
    logger.critical("⚠️ APP_PASSWORD and APP_USERNAME must be set as environment variables!")

# Store active jobs in memory (for SSE) with TTL cleanup
active_jobs = {}
_JOBS_TTL_HOURS = 6


def _cleanup_old_jobs():
    """Remove jobs older than TTL to prevent memory leaks."""
    cutoff = datetime.utcnow() - timedelta(hours=_JOBS_TTL_HOURS)
    stale = [jid for jid, job in active_jobs.items()
             if job.get("created_at", datetime.utcnow()) < cutoff]
    for jid in stale:
        del active_jobs[jid]
    if stale:
        logger.info(f"[CLEANUP] Removed {len(stale)} stale jobs")


# ============================================================
# AUTH
# ============================================================
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        # Timing-safe comparison to prevent timing attacks
        user_ok = secrets.compare_digest(username.encode(), APP_USERNAME.encode()) if APP_USERNAME else False
        pass_ok = secrets.compare_digest(password.encode(), APP_PASSWORD.encode()) if APP_PASSWORD else False
        if user_ok and pass_ok:
            session["logged_in"] = True
            session.permanent = True
            session["user"] = username
            return redirect(url_for("index"))
        error = "Nieprawidłowy login lub hasło"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ============================================================

# ─────────────────────────────────────────────────────────
# Wikipedia fetch for YMYL legal enrichment
# ─────────────────────────────────────────────────────────
import urllib.request as _urllib_req, urllib.parse as _urllib_parse, json as _json_mod

def _fetch_wikipedia_legal_article(article_ref):
    """Fetch Wikipedia summary for a legal article ref like 'art. 178a k.k.'"""
    import re as _re
    q = article_ref.strip()
    # Build expanded query for Wikipedia search
    q_expanded = _re.sub(r'art\.\s*', 'Art. ', q, flags=_re.IGNORECASE)
    # Map abbreviations to full act names for better search
    _act_map = {
        'k.k.': 'Kodeks karny', 'k.w.': 'Kodeks wykroczeń',
        'k.c.': 'Kodeks cywilny', 'k.p.c.': 'Kodeks postępowania cywilnego',
        'k.p.': 'Kodeks pracy', 'k.r.o.': 'Kodeks rodzinny i opiekuńczy',
        'k.p.a.': 'Kodeks postępowania administracyjnego',
        'k.s.h.': 'Kodeks spółek handlowych',
    }
    for abbr, full in _act_map.items():
        q_expanded = q_expanded.replace(abbr, full)
    # Extract article number and act name for relevance filtering
    _art_match = _re.search(r'Art\.?\s*(\d+\w*)', q_expanded, _re.IGNORECASE)
    _art_num = _art_match.group(1) if _art_match else ""
    # Extract act name (everything after the article number)
    _act_name = ""
    for full_name in _act_map.values():
        if full_name.lower() in q_expanded.lower():
            _act_name = full_name.lower()
            break
    try:
        search_url = "https://pl.wikipedia.org/w/api.php?" + _urllib_parse.urlencode({
            "action": "query", "list": "search", "srsearch": q_expanded,
            "format": "json", "srlimit": 5, "srprop": "snippet"
        })
        req = _urllib_req.Request(search_url, headers={"User-Agent": "Brajn2026/1.0"})
        with _urllib_req.urlopen(req, timeout=8) as r:
            data = _json_mod.loads(r.read())
        results = data.get("query", {}).get("search", [])
        if not results:
            return {"found": False, "article_ref": article_ref}
        # v60 FIX: Strict Wikipedia relevance — require article number in page title.
        # Problem observed: "art. 16 k.c." matched "Kodeks cywilny Królestwa Polskiego"
        # which is historically irrelevant. Wikipedia articles about specific k.c. articles
        # are generally low-quality. We now require article NUMBER in the page title
        # (e.g. "Art. 178a" must appear in "Kodeks karny art. 178a" title).
        best_result = None
        for res in results:
            title_low = res.get("title", "").lower()
            # STRICTEST: Page title must contain BOTH act name AND article number
            if _act_name and _art_num:
                if _act_name in title_low and _art_num.lower() in title_low:
                    best_result = res
                    break
        # Second pass: act name + article number anywhere in snippet
        if not best_result and _act_name and _art_num:
            for res in results:
                title_low = res.get("title", "").lower()
                snippet_low = res.get("snippet", "").lower()
                if _act_name in title_low and _art_num.lower() in snippet_low:
                    best_result = res
                    break
        # Only fall back to act-name-only for well-known acts (k.k., k.w. — karny/wykroczeń)
        # Skip this for k.c. (civil code) — Wikipedia articles are typically off-topic
        if not best_result and _act_name and "kodeks cywilny" not in _act_name:
            for res in results:
                title_low = res.get("title", "").lower()
                if title_low.startswith(_act_name) or _act_name.startswith(title_low):
                    best_result = res
                    break
        if not best_result:
            return {"found": False, "article_ref": article_ref, "reason": "no_relevant_wikipedia_result"}
        page_id = best_result["pageid"]
        extract_url = "https://pl.wikipedia.org/w/api.php?" + _urllib_parse.urlencode({
            "action": "query", "pageids": page_id, "prop": "extracts|info",
            "exintro": True, "explaintext": True, "inprop": "url", "format": "json"
        })
        req2 = _urllib_req.Request(extract_url, headers={"User-Agent": "Brajn2026/1.0"})
        with _urllib_req.urlopen(req2, timeout=8) as r2:
            data2 = _json_mod.loads(r2.read())
        pages = data2.get("query", {}).get("pages", {})
        page = next(iter(pages.values()), {})
        extract = (page.get("extract") or "").strip()[:600]
        url = page.get("fullurl", "https://pl.wikipedia.org")
        title = page.get("title", best_result.get("title", ""))
        if extract:
            return {"found": True, "article_ref": article_ref, "title": title, "url": url, "extract": extract, "source": "Wikipedia (pl)"}
        return {"found": False, "article_ref": article_ref}
    except Exception as e:
        return {"found": False, "article_ref": article_ref, "error": str(e)[:60]}


def _enrich_legal_with_wikipedia(articles):
    """Fetch Wikipedia for up to 4 legal article references."""
    results = []
    seen = set()
    for art in articles[:6]:
        r = _fetch_wikipedia_legal_article(art)
        if r.get("found") and r.get("title") not in seen:
            seen.add(r["title"])
            results.append(r)
        if len(results) >= 4:
            break
    return results



# BRAJEN API CLIENT
# ============================================================
def brajen_call(method, endpoint, json_data=None, timeout=None):
    """Call BRAJEN API with retry logic for cold starts. Uses session pooling."""
    url = f"{BRAJEN_API}{endpoint}"
    req_timeout = timeout or REQUEST_TIMEOUT
    # v68 C3: Send Authorization header if MASTER_SEO_API_KEY is set
    _api_key = os.environ.get("MASTER_SEO_API_KEY", "")
    _headers = {"Authorization": f"Bearer {_api_key}"} if _api_key else {}

    for attempt in range(MAX_RETRIES):
        try:
            if method == "get":
                resp = _brajen_session.get(url, headers=_headers, timeout=req_timeout)
            else:
                resp = _brajen_session.post(url, json=json_data, headers=_headers, timeout=req_timeout)

            if resp.status_code in (200, 201):
                content_type = resp.headers.get("content-type", "")
                if "application/json" in content_type:
                    return {"ok": True, "data": resp.json()}
                else:
                    return {"ok": True, "binary": True, "content": resp.content,
                            "headers": dict(resp.headers)}

            logger.warning(f"BRAJEN {method.upper()} {endpoint} → {resp.status_code}")
            if resp.status_code >= 500 and attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAYS[attempt])
                continue

            return {"ok": False, "status": resp.status_code,
                    "error": resp.text[:500]}

        except http_requests.exceptions.Timeout:
            logger.warning(f"BRAJEN timeout: {endpoint} (attempt {attempt+1})")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAYS[attempt])
                continue
            return {"ok": False, "status": 0, "error": "Timeout (Render cold start?)"}

        except http_requests.exceptions.ConnectionError as e:
            logger.warning(f"BRAJEN connection error: {endpoint}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAYS[attempt])
                continue
            return {"ok": False, "status": 0, "error": str(e)[:200]}

    return {"ok": False, "status": 0, "error": "All retries exhausted"}


# ============================================================
# TEXT POST-PROCESSING: strip duplicate headers, clean artifacts
# ============================================================
def _clean_batch_text(text):
    """v59.2: Bulletproof formatter — fixes ALL known LLM output issues.
    Tested on real broken output with 16 glued headings, markdown bold, mixed formats."""

    # ═══ v2: Strip <thinking> blocks and <article_section> tags ═══
    import re as _re_v2
    # Remove entire <thinking>...</thinking> block (Claude planning step)
    text = _re_v2.sub(r'<thinking>.*?</thinking>', '', text, flags=_re_v2.DOTALL).strip()
    # Remove <article_section> wrapper tags (keep content)
    text = text.replace('<article_section>', '').replace('</article_section>', '').strip()
    if not text:
        return text

    # ── FIX 1: Strip markdown **bold** → plain text ──
    text = _re.sub(r'\*\*([^*]+)\*\*', r'\1', text)

    # ── FIX 1b: Unit spacing — "10m²" → "10 m²", "2500zł" → "2500 zł" ──
    text = _re.sub(r'(\d)(m[²³]|m2|cm|mm|km|zł|PLN|kg|mg|ml|l|ha|h|min|szt)', r'\1 \2', text)

    # ── FIX 2: </h3> or </h2> followed by text on same line → line break ──
    text = _re.sub(r'(</h[23]>)\s*(\S)', r'\1\n\2', text)

    # ── FIX 3: ANY H2:/H3: NOT at line start → force \n\n before it ──
    # This is aggressive but correct — headings MUST start on their own line.
    text = _re.sub(r'(?<!\n)([ \t]*)(H[23]:)', r'\n\n\2', text, flags=_re.IGNORECASE)
    text = _re.sub(r'\n{3,}(h[23]:)', r'\n\n\1', text, flags=_re.IGNORECASE)

    # ── FIX 4: Split heading title from paragraph glued on same line ──
    _ABBREVS = {'art', 'pkt', 'ust', 'nr', 'ok', 'dr', 'prof', 'mgr', 'inż',
                'np', 'tj', 'itd', 'itp', 'ww', 'jw', 'tzn', 'tzw',
                'tab', 'rys', 'zob', 'k', 'p', 'c', 'w', 'a', 'o',
                'k.k', 'k.c', 'k.p', 'k.w', 'k.p.a', 'k.r.o', 'k.p.c'}

    def _split_heading_from_para(m):
        tag = m.group(1)
        rest = m.group(2).strip()

        # Strategy A: FAQ heading — title ends with "?"  (always wins)
        q_match = _re.search(r'^(.+?\?)\s+([A-ZĄĆĘŁŃÓŚŹŻ])', rest)
        if q_match and 10 <= len(q_match.group(1)) <= 120:
            return f'{tag}: {q_match.group(1).strip()}\n{rest[q_match.end(1):].strip()}'

        # Collect ALL possible split points, then pick the best one
        candidates = []  # list of (position, source) tuples

        # Strategy B: sentence boundary ". X" / "! X" — skip abbreviations
        for sp in _re.finditer(r'([.!])\s+([A-ZĄĆĘŁŃÓŚŹŻ])', rest):
            pos = sp.start()
            if pos < 15 or pos > 120:
                continue
            before_parts = rest[:pos + 1].rstrip('.').rsplit(None, 1)
            wb = before_parts[-1].rstrip('.').lower() if before_parts else ""
            if wb in _ABBREVS or _re.match(r'^\d+$', wb):
                continue
            candidates.append((pos, 'B'))

        # Strategy C: case boundary — non-upper char + Uppercase word
        for cm in _re.finditer(
            r'([^A-ZĄĆĘŁŃÓŚŹŻ\s])\s+([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]{2,})',
            rest
        ):
            if 25 <= cm.start() <= 130:
                candidates.append((cm.start(), 'C'))

        if not candidates:
            return m.group(0)

        # Pick the split closest to ideal heading length (40-80 chars)
        # Prefer shorter splits (closer to actual heading title)
        IDEAL = 60
        best = min(candidates, key=lambda c: abs(c[0] - IDEAL))
        pos, src = best

        if src == 'B':
            return f'{tag}: {rest[:pos + 1].strip()}\n{rest[pos + 1:].strip()}'
        else:  # C
            return f'{tag}: {rest[:pos + 1].strip()}\n{rest[pos + 1:].strip()}'

        return m.group(0)

    text = _re.sub(
        r'^(h[23]):\s*(.{65,})$',
        _split_heading_from_para,
        text,
        flags=_re.MULTILINE | _re.IGNORECASE
    )

    # ── Step 5: Fix malformed HTML tags ──
    text = _normalize_html_tags(text)

    # ── Step 6: Convert h2:/h3: to HTML tags (case-insensitive) ──
    text = _re.sub(r'^h2:\s*(.+)$', r'<h2>\1</h2>', text, flags=_re.MULTILINE | _re.IGNORECASE)
    text = _re.sub(r'^h3:\s*(.+)$', r'<h3>\1</h3>', text, flags=_re.MULTILINE | _re.IGNORECASE)

    # ── Step 7: Markdown ## to HTML ──
    text = _re.sub(r'^###\s+(.+)$', r'<h3>\1</h3>', text, flags=_re.MULTILINE)
    text = _re.sub(r'^##\s+(.+)$', r'<h2>\1</h2>', text, flags=_re.MULTILINE)

    # ── Step 8: Bold-only lines to h3 ──
    text = _re.sub(r'^\*\*([^*]+)\*\*$', r'<h3>\1</h3>', text, flags=_re.MULTILINE)

    # ── Step 9: Ensure blank line before every <h2>/<h3> ──
    text = _re.sub(r'([^\n])\n(<h[23]>)', r'\1\n\n\2', text)

    # ── Step 10: Clean whitespace ──
    text = _re.sub(r'\n{3,}', '\n\n', text)
    text = _re.sub(r'  +', ' ', text)

    return text.strip()


def _fix_citation_hallucinations(text: str) -> dict:
    """v67: Fix common LLM hallucinations in medical/legal citations.
    
    LLMs often:
    - Misspell journal names: "J Chin Endocrinol Metal" → "J Clin Endocrinol Metab"
    - Mix languages in abbreviations: "ESC/ZAŚ" → "ESC/EAS"  
    - Corrupt author names: "Grunty" → "Grundy"
    - Misspell "Eur Hart J" → "Eur Heart J"
    
    Returns: {"text": fixed_text, "fixes": ["desc1", ...]}
    """
    import re as _re
    fixes = []
    
    # Known medical/legal citation corrections
    _CITATION_FIXES = {
        # Journal names
        r"J\s+Chin\s+Endocrinol\s+Metal": "J Clin Endocrinol Metab",
        r"J\s+Clin\s+Endocrinol\s+Metal": "J Clin Endocrinol Metab",
        r"Eur\s+Hart\s+J\b": "Eur Heart J",
        r"Eur\s+Hear\s+J\b": "Eur Heart J",
        r"N\s+Eng\s+J\s+Med\b": "N Engl J Med",
        r"Lancett?\b(?=\s*[,;.\)])": "Lancet",
        # Organization abbreviations (Polish hallucinations)
        r"ESC/ZAŚ\b": "ESC/EAS",
        r"ESC/EAŚ\b": "ESC/EAS",
        r"AHA/ACC\b\.?\s*[Oo]pisują": "AHA/ACC opisują",
        # Common author name hallucinations
        r"\bGrunty\s+(i\s+wsp|et\s+al)": "Grundy \\1",
        r"\bGrundy\s+i\s+wsp": "Grundy et al",
        # Polish grammar in citations
        r"\(Gru[a-z]+\s+i\s+wsp\.\s*,\s*(\d{4})\s*,\s*Circulation\)": "(Grundy et al., \\1, Circulation)",
        # Remove broken parentheses in citations
        r"\.\s*\(Gr[a-z]+\s*\)": ".",
    }
    
    result = text
    for pattern, replacement in _CITATION_FIXES.items():
        matches = _re.findall(pattern, result, _re.IGNORECASE)
        if matches:
            result = _re.sub(pattern, replacement, result, flags=_re.IGNORECASE)
            fixes.append(f"{pattern[:25]}→{replacement[:25]}")
    
    return {"text": result, "fixes": fixes}


def _normalize_html_tags(text):
    """v56: Safety net — normalize malformed HTML tags in any text.
    Strips code fences, fixes <p.>→<p>, <H2>→<h2>, etc.
    v2.3: Also strips stray/unwanted HTML tags (e.g. <Tt>, <Span>, <Font>).
    Called before emitting article text to frontend."""
    if not text:
        return text
    import re as _re_norm
    _t = text.strip()
    if _t.startswith("```html"):
        _t = _t[7:]
    elif _t.startswith("```"):
        _t = _t[3:]
    if _t.endswith("```"):
        _t = _t[:-3]
    _t = _t.strip()
    _t = _re_norm.sub(r'<p[.,;:]+>', '<p>', _t, flags=_re_norm.IGNORECASE)
    _t = _re_norm.sub(r'</p[.,;:]+>', '</p>', _t, flags=_re_norm.IGNORECASE)
    _t = _re_norm.sub(r'<(h[2-6])[.,;:]+>', r'<\1>', _t, flags=_re_norm.IGNORECASE)
    _t = _re_norm.sub(r'</(h[2-6])[.,;:]+>', r'</\1>', _t, flags=_re_norm.IGNORECASE)
    # v2.3: Strip non-allowed HTML tags (keeps content, removes tag)
    _ALLOWED_TAGS = {'h2', 'h3', 'h4', 'ul', 'ol', 'li', 'table', 'thead', 'tbody',
                     'tr', 'th', 'td', 'strong', 'em', 'b', 'i', 'p', 'br', 'a', 'sup', 'sub'}
    def _strip_bad_tag(m):
        tag_name = _re_norm.match(r'</?(\w+)', m.group(0))
        if tag_name and tag_name.group(1).lower() in _ALLOWED_TAGS:
            return m.group(0)
        return ''  # strip the tag, keep nothing
    _t = _re_norm.sub(r'</?[a-zA-Z][a-zA-Z0-9]*(?:\s[^>]*)?\s*/?>', _strip_bad_tag, _t)
    def _lower(m):
        return m.group(0).lower()
    _t = _re_norm.sub(r'</?[A-Z][A-Z0-9]*(?:\s[^>]*)?\s*/?>', _lower, _t)
    return _t


def _strip_html_for_analysis(text):
    """v59: Strip ALL HTML tags from text for grammar/language analysis.
    
    Problem: Editorial review adds <p>, <h2>, <h3> tags to article text.
    These tags confuse LanguageTool (scores 0/100 because it treats <p> as
    abbreviation 'p' needing a dot) and grammar_checker (48 false fixes).
    
    This function produces CLEAN TEXT for analysis tools while preserving
    h2:/h3: markers that the scoring system understands.
    """
    if not text:
        return text
    import re as _re_strip
    _t = text
    # Convert <h2>Title</h2> back to h2: Title (preserves structure for scoring)
    _t = _re_strip.sub(r'<h2[^>]*>\s*', 'h2: ', _t, flags=_re_strip.IGNORECASE)
    _t = _re_strip.sub(r'\s*</h2>', '', _t, flags=_re_strip.IGNORECASE)
    _t = _re_strip.sub(r'<h3[^>]*>\s*', 'h3: ', _t, flags=_re_strip.IGNORECASE)
    _t = _re_strip.sub(r'\s*</h3>', '', _t, flags=_re_strip.IGNORECASE)
    # Strip <p>, </p>, <li>, </li>, <ul>, </ul>, <ol>, </ol>, <br>, <hr>, etc.
    # NOTE: table|tr|td|th intentionally KEPT — tables are content, not formatting artifacts
    _t = _re_strip.sub(r'</?(?:p|li|ul|ol|div|span|br|hr|blockquote|strong|em|b|i|a)[^>]*/?>', '', _t, flags=_re_strip.IGNORECASE)
    # Clean up extra whitespace from tag removal
    _t = _re_strip.sub(r'\n{3,}', '\n\n', _t)
    _t = _re_strip.sub(r'  +', ' ', _t)
    return _t.strip()
# ============================================================
def generate_h2_plan(main_keyword, mode, s1_data, basic_terms, extended_terms, user_h2_hints=None):
    """
    Generate optimal H2 structure from S1 analysis data.
    v45.3: Uses prompt_builder for readable prompts instead of json.dumps().
    v50.7 FIX 48: Auto-retry on 429/529.
    """
    # Extract S1 insights for fallback
    suggested_h2s = (s1_data.get("content_gaps") or {}).get("suggested_new_h2s", [])
    
    # Parse user phrases (strip ranges), for topic context only
    all_user_phrases = []
    for term_str in (basic_terms + extended_terms):
        kw = term_str.strip().split(":")[0].strip()
        if kw:
            all_user_phrases.append(kw)
    
    # Build prompts via prompt_builder
    system_prompt = build_h2_plan_system_prompt()
    user_prompt = build_h2_plan_user_prompt(
        main_keyword, mode, s1_data, all_user_phrases, user_h2_hints
    )

    # v52.4: _generate_claude ma pełny fallback chain (Sonnet→Haiku na 529)
    # v59.1: OpenAI fallback — H2 plan jest krytyczny, nie może crashować workflow
    try:
        response_text = _generate_claude(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.5,
        )
    except Exception as e:
        err_str = str(e).lower()
        if OPENAI_API_KEY and OPENAI_AVAILABLE and ("529" in err_str or "overload" in err_str or "503" in err_str):
            logger.warning(f"[H2_PLAN] Claude 529/503 — fallback to OpenAI ({OPENAI_MODEL}): {str(e)[:100]}")
            try:
                response_text = _generate_openai(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=0.5,
                )
            except Exception as e2:
                raise RuntimeError(f"H2 plan generation failed (Claude + OpenAI): Claude={e}, OpenAI={e2}") from e2
        else:
            raise RuntimeError(f"H2 plan generation failed: {e}") from e
    
    # Parse JSON response
    h2_list = None
    try:
        clean = response_text.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(clean)
        if isinstance(parsed, list) and len(parsed) >= 2:
            h2_list = parsed
    except (json.JSONDecodeError, ValueError):
        pass
    
    if not h2_list:
        # Fallback: extract lines that look like H2s
        h2_lines = [l.strip().strip('"').strip("'").strip(",").strip('"') 
                 for l in response_text.split("\n") if l.strip() and not l.strip().startswith("[") and not l.strip().startswith("]")]
        if h2_lines:
            h2_list = h2_lines
    
    if not h2_list:
        # Ultimate fallback
        h2_list = suggested_h2s[:7] + ["Najczęściej zadawane pytania"] if suggested_h2s else [main_keyword, "Najczęściej zadawane pytania"]
    
    # ═══ v50.8 FIX 50: Enforce H2 count limits based on mode ═══
    # Dynamic cap: derive from recommended length (not hardcoded)
    _rec = (s1_data or {}).get("recommended_length") or \
           ((s1_data or {}).get("length_analysis") or {}).get("recommended") or 1500
    _dynamic_max = max(4, min(14, int(_rec) // 250 + 2))  # +2 = FAQ + buffer
    MAX_H2 = {"fast": 4, "standard": _dynamic_max}
    max_allowed = MAX_H2.get(mode, 10)
    
    if len(h2_list) > max_allowed:
        logger.info(f"[H2_PLAN] ✂️ Trimming {len(h2_list)} H2s to {max_allowed} (mode={mode})")
        # Keep FAQ at the end
        has_faq = any("pytani" in h.lower() for h in h2_list[-2:])
        if has_faq:
            faq = [h for h in h2_list if "pytani" in h.lower()][-1]
            content_h2s = [h for h in h2_list if "pytani" not in h.lower()]
            h2_list = content_h2s[:max_allowed - 1] + [faq]
        else:
            h2_list = h2_list[:max_allowed]
    
    return h2_list



# ============================================================
# TEXT GENERATION (Claude + OpenAI)
# ============================================================
def generate_batch_text(pre_batch, h2, batch_type, article_memory=None, engine="claude", openai_model=None, temperature=None, content_type="article", category_data=None):
    """Generate batch text using optimized prompts built from pre_batch data.

    v45.3: Replaces raw json.dumps() with structured natural language prompts
    that Claude can follow effectively. Uses prompt_builder module.
    v50.8 FIX 49: Adaptive thinking (effort) + web search for YMYL.
    """
    if content_type == "category":
        system_prompt = build_category_system_prompt(pre_batch, batch_type, category_data)
        user_prompt = build_category_user_prompt(pre_batch, h2, batch_type, article_memory, category_data)
    else:
        system_prompt = build_system_prompt(pre_batch, batch_type)
        user_prompt = build_user_prompt(pre_batch, h2, batch_type, article_memory)

    if engine == "openai" and OPENAI_API_KEY:
        return _generate_openai(system_prompt, user_prompt, model=openai_model, temperature=temperature)
    else:
        # v50.9 FIX 53: Thinking only for YMYL. Regular content uses user temperature.
        is_ymyl = pre_batch.get("_is_ymyl", False)
        ymyl_intensity = pre_batch.get("_ymyl_intensity", "none")
        
        # Thinking (effort) only for YMYL where accuracy matters
        if ymyl_intensity == "full":
            effort = "high"
        elif ymyl_intensity == "light":
            effort = "medium"
        else:
            effort = None  # No thinking, user temperature controls output
        
        # Web search: only for YMYL content (legal/medical/finance)
        use_web_search = is_ymyl and ymyl_intensity == "full"
        
        # ═══ v2: Use recommended temperature per batch type ═══
        v2_params = get_api_params(batch_type)
        effective_temp = temperature  # User override takes priority
        if effective_temp is None and v2_params.get("version") == "v2":
            effective_temp = v2_params["temperature"]
        
        return _generate_claude(system_prompt, user_prompt,
                                effort=effort, web_search=use_web_search,
                                temperature=effective_temp)


def _generate_claude(system_prompt, user_prompt, effort=None, web_search=False, temperature=None, _cost_job=None, _cost_step="llm_call"):
    """Generate text using Anthropic Claude.
    
    v50.7 FIX 48: Auto-retry on 429/529.
    v50.8 FIX 49: Adaptive thinking (effort) + web search for YMYL.
    v50.9 FIX 52: User-configurable temperature.
    v67: _cost_job/_cost_step — optional cost tracking via llm_cost_tracker.
    
    Args:
        effort: "high" | "medium" | "low" | None (None = no effort param, uses temperature)
        web_search: True = enable web_search tool (for YMYL fact verification)
        temperature: 0.0-1.0, user-configured. When thinking is enabled, forced to 1.
        _cost_job: job_id for cost tracking (None = skip tracking)
        _cost_step: step name for cost breakdown
    """
    # v50.9: User temperature (default 0.7 if not set)
    user_temp = temperature if temperature is not None else 0.7
    
    def _call():
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, max_retries=0)
        
        kwargs = {
            "model": _get_anthropic_model(),
            "max_tokens": 4000,
            "system": [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"}
                }
            ],
            "messages": [{"role": "user", "content": user_prompt}],
        }
        
        # v50.8 FIX 49: Adaptive thinking: budget_tokens scales by task difficulty.
        # max_tokens must exceed budget_tokens (thinking counts against it).
        # YMYL (legal/medical) → more reasoning → better accuracy
        # Regular content → less reasoning → faster, cheaper
        if effort:
            kwargs["temperature"] = 1  # Required: temperature must be 1 with thinking
            budget = {"high": 3000, "medium": 1500, "low": 500}.get(effort, 1500)
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": budget
            }
            # max_tokens must be > budget_tokens; ensure 4000 for output
            kwargs["max_tokens"] = budget + 4000
        else:
            kwargs["temperature"] = user_temp  # v50.9: user-configurable temperature
        
        # v50.8 FIX 49: Web search tool for YMYL content
        # Claude searches the web to verify legal/medical facts during generation
        if web_search:
            kwargs["tools"] = [
                {"type": "web_search_20250305", "name": "web_search"}
            ]
        
        response = client.messages.create(**kwargs)
        
        # v67: Cost tracking
        if _cost_job:
            try:
                _in_t = getattr(response.usage, 'input_tokens', 0)
                _out_t = getattr(response.usage, 'output_tokens', 0)
                cost_tracker.record(_cost_job, _get_anthropic_model(), _in_t, _out_t, step=_cost_step)
            except Exception:
                pass
        
        # v50.8: Parse response: may contain thinking blocks + text + web search results
        text_parts = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
        
        return "\n".join(text_parts).strip()
    
    try:
        return _llm_call_with_retry(_call)
    except Exception as e:
        # v50.8: Graceful fallback: if thinking/web_search not supported, retry without
        err_str = str(e).lower()
        if effort and ("thinking" in err_str or "budget_tokens" in err_str or "temperature" in err_str):
            logger.warning(f"[FIX49] Thinking not supported, falling back: {str(e)[:100]}")
            effort = None  # Disable for retry
            return _llm_call_with_retry(_call)
        if web_search and ("web_search" in err_str or "tool" in err_str):
            logger.warning(f"[FIX49] Web search not supported, falling back: {str(e)[:100]}")
            web_search = False  # Disable for retry
            return _llm_call_with_retry(_call)
        raise


def _generate_openai(system_prompt, user_prompt, model=None, temperature=None):
    """Generate text using OpenAI GPT. v50.7 FIX 48: Auto-retry on 429/529."""
    if not OPENAI_AVAILABLE:
        logger.warning("OpenAI not installed, falling back to Claude")
        return _generate_claude(system_prompt, user_prompt, temperature=temperature)
    
    effective_model = model or OPENAI_MODEL
    user_temp = temperature if temperature is not None else 0.7
    
    # v50.7 FIX 43: GPT-5.x and o-series use max_completion_tokens, not max_tokens
    use_new_param = any(effective_model.startswith(p) for p in ("gpt-5", "o1", "o3", "o4"))
    token_param = {"max_completion_tokens": 4000} if use_new_param else {"max_tokens": 4000}
    
    def _call():
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=effective_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=user_temp,
            **token_param
        )
        return response.choices[0].message.content.strip()
    return _llm_call_with_retry(_call)


def _generate_paa_fallback(main_keyword: str) -> list:
    """Generate PAA questions using Claude when SERP providers return none.
    
    v59.1: Client-side fallback — backend PAA_FALLBACK requires OPENAI_API_KEY
    which may not be set. Claude Haiku generates 6-8 realistic PAA questions.
    """
    if not ANTHROPIC_API_KEY:
        return []
    
    system = "Jesteś ekspertem Google PAA (People Also Ask). Generujesz realistyczne pytania które Google pokazałby dla danej frazy. Odpowiedz TYLKO tablicą JSON."
    user = f"""Wygeneruj 6-8 pytań PAA (People Also Ask) dla frazy: "{main_keyword}"

Zasady:
- Pytania muszą brzmieć jak prawdziwe zapytania użytkowników Google
- Zaczynaj od: "Czy...", "Jak...", "Ile...", "Co...", "Kiedy...", "Jaki..."
- Nie powtarzaj frazy głównej dosłownie w każdym pytaniu
- Pytania powinny pokrywać różne aspekty tematu

Format: ["pytanie 1", "pytanie 2", ...]"""
    
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, max_retries=1)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            system=system,
            messages=[{"role": "user", "content": user}],
            temperature=0.8,
        )
        text = response.content[0].text.strip()
        # Parse JSON array
        clean = text.replace("```json", "").replace("```", "").strip()
        questions = json.loads(clean)
        if isinstance(questions, list) and len(questions) >= 3:
            logger.info(f"[PAA_FALLBACK] ✅ Claude generated {len(questions)} PAA questions for '{main_keyword}'")
            return [{"question": q, "source": "claude_fallback"} if isinstance(q, str) else q for q in questions[:8]]
    except Exception as e:
        logger.warning(f"[PAA_FALLBACK] Claude fallback failed: {str(e)[:100]}")
    
    return []


def generate_faq_text(paa_data, pre_batch=None, engine="claude", openai_model=None, temperature=None):
    """Generate FAQ section using optimized prompts.
    
    v45.3: Uses prompt_builder for structured instructions instead of json.dumps().
    v45.3.4: Handles paa_data as list or dict.
    """
    # Normalize: if paa_data is a list, wrap it as dict
    if isinstance(paa_data, list):
        paa_data = {"serp_paa": paa_data}
    elif not isinstance(paa_data, dict):
        paa_data = {}

    system_prompt = build_faq_system_prompt(pre_batch)
    user_prompt = build_faq_user_prompt(paa_data, pre_batch)

    if engine == "openai" and OPENAI_API_KEY:
        return _generate_openai(system_prompt, user_prompt, model=openai_model, temperature=temperature)
    else:
        # FAQ = simple Q&A, no thinking needed
        return _generate_claude(system_prompt, user_prompt, effort=None, temperature=temperature)


# ============================================================
# QUALITY BREAKDOWN EXTRACTION
# ============================================================
def _extract_quality_breakdown(final):
    """Extract quality radar scores from final_review response.

    Backend may return scores at top level, nested in quality_breakdown,
    or inside validations. Scores may be 0-10 or 0-100.
    """
    # Try pre-built quality_breakdown from backend first
    qb = final.get("quality_breakdown") or {}

    # Define field name variants for each dimension
    _FIELDS = {
        "keywords":  ["keyword_score", "keywords_score", "keywords"],
        "humanness": ["humanness_score", "ai_score", "humanness", "human_score"],
        "grammar":   ["grammar_score", "grammar"],
        "structure": ["structure_score", "structure"],
        "semantic":  ["semantic_score", "semantic", "semantic_relevance"],
        "depth":     ["depth_score", "depth", "content_depth"],
        "coherence": ["coherence_score", "coherence"],
    }

    # Map radar dimensions to nested API response paths
    # Backend returns: keywords_validation, advanced_semantic, entity_scoring, validations
    _NESTED_PATHS = {
        "keywords":  ["keywords_validation", ("validations", "missing_keywords")],
        "semantic":  ["advanced_semantic", ("validations", "semantic")],
        "depth":     ["entity_scoring", ("validations", "depth")],
        "grammar":   [("validations", "grammar")],
        "structure": [("validations", "structure")],
        "humanness": [("validations", "humanness"), ("validations", "ai_detection")],
        "coherence": [("validations", "coherence")],
    }

    result = {}
    for dim, candidates in _FIELDS.items():
        val = qb.get(dim)  # first try pre-built breakdown
        if val is None:
            for key in candidates:
                val = final.get(key)
                if val is not None:
                    break
        # Still None? Try nested in validations.quality or scores
        if val is None:
            scores_obj = final.get("scores") or final.get("quality") or {}
            for key in [dim] + candidates:
                val = scores_obj.get(key)
                if val is not None:
                    break
        # Still None? Try nested API response objects (keywords_validation.score, etc.)
        if val is None:
            for path in _NESTED_PATHS.get(dim, []):
                if isinstance(path, tuple):
                    obj = final
                    for key in path:
                        obj = (obj.get(key) or {}) if isinstance(obj, dict) else {}
                else:
                    obj = final.get(path) or {}
                if isinstance(obj, dict):
                    val = obj.get("score") or obj.get(f"{dim}_score")
                    if val is not None:
                        break
        result[dim] = val

    # Auto-detect scale: if all non-None values are <= 10, multiply by 10
    non_none = [v for v in result.values() if v is not None and isinstance(v, (int, float))]
    if non_none and all(v <= 10 for v in non_none):
        result = {k: (round(v * 10) if isinstance(v, (int, float)) else v)
                  for k, v in result.items()}

    # Log for debug
    logger.info(f"[RADAR_DEBUG] extracted: {result} | final keys: {sorted(final.keys())[:15]}")

    return result


# ============================================================
# SEMANTIC DISTANCE & EVALUATION HELPERS
# ============================================================
def _fuzzy_phrase_in_text(phrase, text_lower, _text_stems=None):
    """
    v59: Polish fuzzy matching using stem-prefix approach.
    Handles declension: "kara pozbawienia wolności" matches "karę pozbawienia wolności".
    
    For each word in phrase:
    - words ≤3 chars: exact substring match
    - words 4 chars: match first 3 chars (Polish short-word declension changes last char)  
    - words ≥5 chars: match first 4 chars (standard stem4)
    
    All words must match for phrase to count as found.
    """
    import re as _re
    words = phrase.lower().split()
    if not words:
        return False
    # Fast path: exact match
    if phrase.lower() in text_lower:
        return True
    # Stem-prefix match: all words must appear
    for w in words:
        w_clean = _re.sub(r'[^\w]', '', w)
        if not w_clean:
            continue
        if len(w_clean) <= 3:
            if w_clean not in text_lower:
                return False
        elif len(w_clean) == 4:
            stem = _re.escape(w_clean[:3])
            if not _re.search(r'(?:^|\s|>)' + stem + r'\w*', text_lower):
                return False
        else:
            stem = _re.escape(w_clean[:4])
            if not _re.search(r'(?:^|\s|>)' + stem + r'\w*', text_lower):
                return False
    return True



# ============================================================
# v2.4: POLISH TEXT NATURALNESS — stats from NKJP corpus data
# Reference: Moździerz 2020 (90k words), IPI PAN (25M words),
# IFJ PAN 2023 (240 literary works), Jasnopis (SWPS+PAN)
# ============================================================
_PL_DIACRITICS = set("ąęćłńóśźżĄĘĆŁŃÓŚŹŻ")
_PL_VOWELS = set("aeiouyąęóAEIOUYĄĘÓ")

def _compute_polish_text_stats(text: str) -> dict:
    """Compute Polish-specific naturalness metrics against NKJP corpus norms."""
    if not text or len(text) < 200:
        return {"computed": False}

    import re
    # Clean HTML
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"\s+", " ", clean).strip()

    chars = [c for c in clean if c.isalpha()]
    char_count = len(chars)
    if char_count < 50:
        return {"computed": False}

    # 1. Diacritics ratio (NKJP norm: 6.9% ±1%)
    diac_count = sum(1 for c in chars if c in _PL_DIACRITICS)
    diac_ratio = diac_count / char_count if char_count else 0

    # 2. Vowel ratio (NKJP norm: 35-38%)
    vowel_count = sum(1 for c in chars if c in _PL_VOWELS)
    vowel_ratio = vowel_count / char_count if char_count else 0

    # 3. Word length (NKJP norm: 6.0 chars ±0.5)
    words = clean.split()
    word_lengths = [len(w.strip(".,;:!?\"'()[]{}–—-")) for w in words if len(w.strip(".,;:!?\"'()[]{}–—-")) > 0]
    avg_word_len = sum(word_lengths) / len(word_lengths) if word_lengths else 0

    # 4. Sentence length (norm: 10-15 words for publicystyka)
    sentences = re.split(r'[.!?]+', clean)
    sentences = [s.strip() for s in sentences if len(s.strip().split()) >= 3]
    sent_lengths = [len(s.split()) for s in sentences]
    avg_sent_len = sum(sent_lengths) / len(sent_lengths) if sent_lengths else 0

    # 5. FOG-PL (Gunning adapted: hard words = 4+ syllables in Polish)
    def _count_syllables_pl(word):
        """Count Polish syllables (vowel nuclei)."""
        w = word.lower()
        count = 0
        prev_vowel = False
        for ch in w:
            is_v = ch in "aeiouyąęó"
            if is_v and not prev_vowel:
                count += 1
            prev_vowel = is_v
        return max(1, count)

    hard_words = sum(1 for w in word_lengths
                     if _count_syllables_pl(words[word_lengths.index(w)] if w < len(words) else "x") >= 4)
    # Safer: count syllables from actual words
    hard_count = 0
    for w in words:
        clean_w = w.strip(".,;:!?\"'()[]{}–—-")
        if clean_w and _count_syllables_pl(clean_w) >= 4:
            hard_count += 1
    total_words = len(words)
    fog_pl = 0.4 * ((total_words / max(len(sentences), 1)) + 100 * (hard_count / max(total_words, 1))) if total_words else 0

    # 6. Comma density (NKJP: comma > letter "b", ~1.5% of chars)
    all_chars = len(clean)
    comma_count = clean.count(",")
    comma_ratio = comma_count / all_chars if all_chars else 0

    # 7. "że" comma check (100% obligatory in Polish)
    ze_total = len(re.findall(r'\bże\b', clean, re.IGNORECASE))
    ze_with_comma = len(re.findall(r',\s*że\b', clean, re.IGNORECASE))
    ze_comma_pct = ze_with_comma / ze_total if ze_total > 0 else 1.0

    # Scoring
    diac_score = max(0, 100 - abs(diac_ratio - 0.069) * 1000)  # penalty per 0.1% deviation
    word_len_score = max(0, 100 - abs(avg_word_len - 6.0) * 50)  # penalty per 0.5 char
    sent_len_ok = 8 <= avg_sent_len <= 18
    sent_score = 100 if sent_len_ok else max(0, 100 - abs(avg_sent_len - 13) * 5)
    fog_score = 100 if 7 <= fog_pl <= 12 else max(0, 100 - abs(fog_pl - 9.5) * 8)

    composite = round(diac_score * 0.25 + word_len_score * 0.2 + sent_score * 0.2 +
                       fog_score * 0.2 + (ze_comma_pct * 100) * 0.15)

    return {
        "computed": True,
        "score": min(100, max(0, composite)),
        # Raw values
        "diacritics_ratio": round(diac_ratio * 100, 2),  # %
        "diacritics_target": 6.9,
        "vowel_ratio": round(vowel_ratio * 100, 1),
        "avg_word_length": round(avg_word_len, 2),
        "avg_word_length_target": 6.0,
        "avg_sentence_length": round(avg_sent_len, 1),
        "sentence_count": len(sent_lengths),
        "fog_pl": round(fog_pl, 1),
        "fog_level": ("szkoła podst." if fog_pl < 7 else "publicystyka" if fog_pl < 10
                       else "liceum" if fog_pl < 13 else "studia" if fog_pl < 16 else "specjalistyczny"),
        "comma_ratio": round(comma_ratio * 100, 2),
        "ze_comma_pct": round(ze_comma_pct * 100, 1),
        "ze_total": ze_total,
        "hard_words_pct": round(hard_count / max(total_words, 1) * 100, 1),
        # Scores per dimension
        "diacritics_score": round(diac_score),
        "word_len_score": round(word_len_score),
        "sentence_score": round(sent_score),
        "fog_score": round(fog_score),
    }


def _compute_text_dimensions(pl_stats: dict, style: dict) -> dict:
    """Compute 3 composite text quality dimensions from existing metrics.
    
    Spójność (Coherence): How well text flows between sections.
      - transition_ratio (20-35% ideal) → 40%
      - cv_paragraphs (<0.5 ideal) → 30%
      - repetition_ratio (<8% ideal) → 30%
    
    Płynność (Fluency): Sentence rhythm and readability.
      - cv_sentences (0.25-0.5 ideal) → 35%
      - avg_sentence_length (10-18 ideal for Polish) → 25%
      - repetition_ratio (<8%) → 20%
      - fog_score from pl_stats → 20%
    
    Naturalność (Naturalness): How human/native the text sounds.
      - polish_nlp composite (NKJP norms) → 60%
      - passive_ratio (<20% ideal) → 20%
      - style score → 20%
    """
    def _dim(val, low, high, invert=False):
        """Score 0-100: how well val fits [low, high] range."""
        if val is None:
            return 50
        if invert:
            return max(0, min(100, 100 - val * 100)) if val <= 1 else 0
        if low <= val <= high:
            return 100
        if val < low:
            dist = (low - val) / max(low, 0.01)
            return max(0, round(100 - dist * 100))
        else:
            dist = (val - high) / max(high, 0.01)
            return max(0, round(100 - dist * 80))

    # --- Spójność (Coherence) ---
    tr = style.get("transition_ratio")
    tr_sc = _dim(tr, 0.10, 0.35) if tr is not None else 50

    cv_p = style.get("cv_paragraphs")
    cvp_sc = _dim(cv_p, 0.0, 0.50) if cv_p is not None else 50

    rep = style.get("repetition_ratio")
    rep_sc = max(0, round(100 - (rep or 0) * 500)) if rep is not None else 50  # 0%→100, 20%→0

    spojnosc = round(tr_sc * 0.4 + cvp_sc * 0.3 + rep_sc * 0.3)

    # --- Płynność (Fluency) ---
    cv_s = style.get("cv_sentences")
    cvs_sc = _dim(cv_s, 0.25, 0.50) if cv_s is not None else 50

    avg_sl = style.get("avg_sentence_length")
    sl_sc = _dim(avg_sl, 10, 18) if avg_sl is not None else 50

    fog_sc = pl_stats.get("fog_score", 50) if pl_stats else 50

    plynnosc = round(cvs_sc * 0.35 + sl_sc * 0.25 + rep_sc * 0.20 + fog_sc * 0.20)

    # --- Naturalność (Naturalness) ---
    pl_composite = pl_stats.get("score", 50) if pl_stats else 50

    pas = style.get("passive_ratio")
    pas_sc = _dim(pas, 0.0, 0.20) if pas is not None else 50

    sty_sc = style.get("score", 50) if style.get("score") else 50

    naturalnosc = round(pl_composite * 0.60 + pas_sc * 0.20 + sty_sc * 0.20)

    return {
        "spojnosc": {"score": min(100, max(0, spojnosc)), "label": "Spójność",
                     "components": {"transitions": tr_sc, "paragraph_cv": cvp_sc, "no_repetition": rep_sc}},
        "plynnosc": {"score": min(100, max(0, plynnosc)), "label": "Płynność",
                     "components": {"sentence_cv": cvs_sc, "sentence_length": sl_sc, "no_repetition": rep_sc, "readability": fog_sc}},
        "naturalnosc": {"score": min(100, max(0, naturalnosc)), "label": "Naturalność",
                        "components": {"polish_nlp": pl_composite, "low_passive": pas_sc, "style": round(sty_sc)}},
    }


def _compute_semantic_distance(full_text, clean_semantic_kp, clean_entities,
                                concept_entities, clean_must_mention,
                                clean_ngrams, nlp_entities):
    """
    Compute semantic distance between generated article and competitor data.
    Returns dict with 4 sub-metrics + composite score (0-100).
    All data comes from real BRAJEN API + Google NLP — no hallucinations.
    """
    text_lower = full_text.lower() if full_text else ""

    # 1. Keyphrase coverage: check which semantic keyphrases appear in article
    #    v59: fuzzy matching for Polish declension (stem4)
    kp_found = []
    kp_missing = []
    for kp in clean_semantic_kp:
        phrase = (kp.get("phrase", kp) if isinstance(kp, dict) else str(kp)).strip()
        if not phrase:
            continue
        if _fuzzy_phrase_in_text(phrase, text_lower):
            kp_found.append(phrase)
        else:
            kp_missing.append(phrase)
    kp_total = len(kp_found) + len(kp_missing)
    kp_coverage = len(kp_found) / kp_total if kp_total > 0 else 0.0

    # 2. Entity overlap: article entities (NLP) vs competitor entities
    # Build competitor entity name set
    comp_entity_names = set()
    for src in [clean_entities, concept_entities]:
        for e in (src or []):
            name = _extract_text(e)
            if name and len(name) > 1:
                comp_entity_names.add(name.lower().strip())

    # Build article entity name set from Google NLP results
    art_entity_names = set()
    if nlp_entities:
        for e in nlp_entities:
            name = e.get("name", "")
            if name and len(name) > 1:
                art_entity_names.add(name.lower().strip())
    else:
        # Fallback: check which competitor entities appear as substrings
        # v59: fuzzy matching for Polish declension
        for name in comp_entity_names:
            if _fuzzy_phrase_in_text(name, text_lower):
                art_entity_names.add(name)

    shared = art_entity_names & comp_entity_names
    only_article = art_entity_names - comp_entity_names
    only_competitor = comp_entity_names - art_entity_names
    ent_overlap = len(shared) / len(comp_entity_names) if comp_entity_names else 0.0

    # 3. Must-mention coverage (v59: fuzzy matching)
    mm_found = []
    mm_missing = []
    for e in (clean_must_mention or []):
        name = _extract_text(e) if isinstance(e, (dict, str)) else str(e)
        if not name:
            continue
        if _fuzzy_phrase_in_text(name, text_lower):
            mm_found.append(name)
        else:
            mm_missing.append(name)
    mm_total = len(mm_found) + len(mm_missing)
    mm_pct = len(mm_found) / mm_total if mm_total > 0 else 0.0

    # 4. N-gram overlap (v59: fuzzy matching)
    ng_found = 0
    ng_total = 0
    for ng in (clean_ngrams or []):
        ngram_text = (ng.get("ngram", ng) if isinstance(ng, dict) else str(ng)).strip()
        if not ngram_text or len(ngram_text) < 3:
            continue
        ng_total += 1
        if _fuzzy_phrase_in_text(ngram_text, text_lower):
            ng_found += 1
    ng_overlap = ng_found / ng_total if ng_total > 0 else 0.0

    # Composite score: weighted sum
    score = round(kp_coverage * 25 + ent_overlap * 30 + mm_pct * 25 + ng_overlap * 20)
    score = max(0, min(100, score))

    return {
        "enabled": True,
        "score": score,
        "keyphrase_coverage": round(kp_coverage, 3),
        "keyphrases_total": kp_total,
        "keyphrases_found": len(kp_found),
        "keyphrases_found_list": kp_found[:15],
        "keyphrases_missing_list": kp_missing[:10],
        "entity_overlap": round(ent_overlap, 3),
        "entities_article": len(art_entity_names),
        "entities_competitor": len(comp_entity_names),
        "entities_shared_list": sorted(shared)[:15],
        "entities_only_article": sorted(only_article)[:10],
        "entities_only_competitor": sorted(only_competitor)[:10],
        "must_mention_pct": round(mm_pct, 3),
        "must_mention_found": mm_found[:10],
        "must_mention_missing": mm_missing[:10],
        "must_mention_total": mm_total,
        "ngram_overlap": round(ng_overlap, 3),
        "ngrams_found": ng_found,
        "ngrams_total": ng_total,
    }


def _compute_semantic_analysis(full_text, h2_structure,
                                clean_semantic_kp, clean_entities,
                                concept_entities, clean_must_mention,
                                clean_ngrams, competitor_h2_patterns,
                                recommended_length=None):
    """v67: Enhanced semantic analysis for Content Editorial card.
    
    Adds:
    1. Per-H2 section semantic coverage heatmap
    2. Term gap analysis (missing/overused terms)
    3. Entity coverage gap with importance weighting
    4. Composite SEO Similarity score 0-100
    5. Length ratio penalty (articles 2x+ recommended get score reduction)
    
    Uses existing competitor data (entities, n-grams, keyphrases) —
    no new API calls needed.
    """
    import re as _re
    
    if not full_text:
        return {"enabled": False}
    
    text_lower = full_text.lower()
    
    # ── Build unified term pool from all competitor data ──
    # Each term gets a weight: must_mention > entity > keyphrase > ngram
    term_pool = {}  # {term_lower: {"weight": float, "source": str}}
    
    for e in (clean_must_mention or []):
        name = _extract_text(e) if isinstance(e, (dict, str)) else str(e)
        if name and len(name) > 2:
            term_pool[name.lower().strip()] = {"weight": 1.0, "source": "must_mention"}
    
    for src in [clean_entities, concept_entities]:
        for e in (src or []):
            name = _extract_text(e)
            if name and len(name) > 2:
                key = name.lower().strip()
                if key not in term_pool:
                    term_pool[key] = {"weight": 0.8, "source": "entity"}
    
    for kp in (clean_semantic_kp or []):
        phrase = (kp.get("phrase", kp) if isinstance(kp, dict) else str(kp)).strip()
        if phrase and len(phrase) > 2:
            key = phrase.lower().strip()
            if key not in term_pool:
                term_pool[key] = {"weight": 0.6, "source": "keyphrase"}
    
    for ng in (clean_ngrams or []):
        ngram_text = (ng.get("ngram", ng) if isinstance(ng, dict) else str(ng)).strip()
        if ngram_text and len(ngram_text) > 2:
            key = ngram_text.lower().strip()
            if key not in term_pool:
                term_pool[key] = {"weight": 0.4, "source": "ngram"}
    
    # ── Check which terms appear in full article ──
    present_terms = []
    missing_terms = []
    for term, info in term_pool.items():
        if _fuzzy_phrase_in_text(term, text_lower):
            present_terms.append({"term": term, **info})
        else:
            missing_terms.append({"term": term, **info})
    
    # Sort missing by weight (most important first)
    missing_terms.sort(key=lambda x: -x["weight"])
    present_terms.sort(key=lambda x: -x["weight"])
    
    total_weight = sum(t["weight"] for t in term_pool.values()) or 1
    covered_weight = sum(t["weight"] for t in present_terms)
    weighted_coverage = round(covered_weight / total_weight, 3)
    
    # ── Per-H2 section analysis ──
    h2_scores = []
    if h2_structure and full_text:
        # Split article into sections by h2: markers
        sections = _re.split(r'(?i)(?:^|\n)\s*h2:\s*', full_text)
        # First section is intro (before first H2)
        section_texts = []
        section_names = ["Intro"]
        
        for i, sec in enumerate(sections):
            if i == 0:
                section_texts.append(sec)
            else:
                # First line is the H2 title
                lines = sec.split('\n', 1)
                h2_title = lines[0].strip()
                body = lines[1] if len(lines) > 1 else ""
                section_names.append(h2_title[:60])
                section_texts.append(body)
        
        for idx, (sec_name, sec_text) in enumerate(zip(section_names, section_texts)):
            sec_lower = sec_text.lower()
            sec_present = 0
            sec_total = 0
            for term, info in term_pool.items():
                if info["weight"] >= 0.6:  # Only check important terms
                    sec_total += 1
                    if _fuzzy_phrase_in_text(term, sec_lower):
                        sec_present += 1
            sec_pct = round(sec_present / sec_total * 100) if sec_total > 0 else 0
            h2_scores.append({
                "name": sec_name,
                "coverage_pct": sec_pct,
                "terms_found": sec_present,
                "terms_checked": sec_total,
            })
    
    # ── Entity coverage gap (with importance) ──
    comp_entity_names = set()
    for src in [clean_entities, concept_entities]:
        for e in (src or []):
            name = _extract_text(e)
            if name and len(name) > 1:
                comp_entity_names.add(name.lower().strip())
    
    entity_present = []
    entity_missing = []
    for name in sorted(comp_entity_names):
        if _fuzzy_phrase_in_text(name, text_lower):
            entity_present.append(name)
        else:
            entity_missing.append(name)
    
    ent_coverage_pct = round(len(entity_present) / len(comp_entity_names) * 100) if comp_entity_names else 0
    
    # ── Composite score ──
    # Weighted: term coverage 40%, entity coverage 30%, must-mention 30%
    mm_found_count = sum(1 for t in present_terms if t["source"] == "must_mention")
    mm_total_count = sum(1 for t in term_pool.values() if t["source"] == "must_mention") or 1
    mm_pct = mm_found_count / mm_total_count
    
    composite = round(weighted_coverage * 40 + (ent_coverage_pct / 100) * 30 + mm_pct * 30)
    composite = max(0, min(100, composite))
    
    # v67: Length ratio penalty — articles much longer than recommended score too easily
    # A 2400-word article covering 24 terms is trivial; a 1100-word article doing the same is impressive
    length_ratio = 1.0
    _length_penalty_applied = False
    if recommended_length and recommended_length > 0:
        actual_words = len(full_text.split())
        length_ratio = actual_words / recommended_length
        if length_ratio > 1.5:
            # Penalty: reduce score proportional to excess length
            # 1.5x → no penalty, 2x → -10pts, 3x → -20pts
            _penalty = min(25, int((length_ratio - 1.5) * 20))
            composite = max(30, composite - _penalty)
            _length_penalty_applied = True
    
    return {
        "enabled": True,
        "composite_score": composite,
        "weighted_coverage": weighted_coverage,
        "term_pool_size": len(term_pool),
        "terms_present": len(present_terms),
        "terms_missing": len(missing_terms),
        "missing_terms": [{"term": t["term"], "source": t["source"], "weight": t["weight"]} 
                          for t in missing_terms[:15]],
        "present_terms": [{"term": t["term"], "source": t["source"]}
                          for t in present_terms[:15]],
        "entity_coverage_pct": ent_coverage_pct,
        "entities_present": entity_present[:15],
        "entities_missing": entity_missing[:15],
        "must_mention_pct": round(mm_pct, 3),
        "h2_heatmap": h2_scores,
        "length_ratio": round(length_ratio, 2),
        "length_penalty_applied": _length_penalty_applied,
    }


# ============================================================
# v2.3: REDAKTOR NACZELNY — final expert review + auto-fix
# ============================================================

_EDITOR_REVIEW_PROMPT = """Jesteś redaktorem naczelnym pisma o tematyce: {category}.
Przeczytaj artykuł na temat: „{keyword}"

SZUKAJ WYŁĄCZNIE:
1. BŁĘDY KRYTYCZNE (fakty, prawo, medycyna):
   - Błędne numery artykułów / paragrafów / ustaw
   - Pomylone nazwy ustaw (np. „ustawa o ochronie konsumenta" zamiast „Kodeks wykroczeń")
   - Złe jednostki (np. promile zamiast mg/dm³ w kontekście wydychanego powietrza)
   - Zmyślone dane, daty, sygnatury orzeczeń
   - Sprzeczności wewnętrzne (np. raz „2 lata" a dalej „3 lata" za to samo)
   - BŁĘDNE CYTOWANIA I NAZWY ŹRÓDEŁ:
     * Przekręcone nazwy czasopism (np. „J Chin" zamiast „J Clin", „Eur Hart J" zamiast „Eur Heart J")
     * Spolszczone skróty organizacji (np. „ESC/ZAŚ" zamiast „ESC/EAS")
     * Przekręcone nazwiska autorów (np. „Grunty" zamiast „Grundy")
     * Niepoprawne tytuły publikacji / zmyślone PMID
2. ARTEFAKTY TECHNICZNE:
   - Pozostałości HTML (<Tt>, <Span>, <Font> itp.)
   - Urwane zdania, lorem ipsum, placeholder tekst
   - Zdania bez sensu / niedokończone
3. BŁĘDY LOGIKI / STRUKTURY:
   - Powtórzenia tego samego faktu w różnych sekcjach
   - Sprzeczne informacje między sekcjami

NIE oceniaj: stylu, SEO, długości, „ciekawości" tekstu. Tylko TWARDE BŁĘDY.

Odpowiedz TYLKO JSON (bez markdown):
{{
  "krytyczne": [
    {{"cytat": "fragment z artykułu (max 50 słów)", "blad": "co jest źle", "poprawka": "jak powinno być"}}
  ],
  "artefakty": [
    {{"cytat": "fragment", "blad": "opis"}}
  ],
  "logika": [
    {{"opis": "co jest sprzeczne/powtórzone"}}
  ],
  "ocena": "PASS|WARN|FAIL",
  "komentarz": "1-2 zdania podsumowania (max 100 słów)"
}}

Jeśli artykuł jest OK → krytyczne=[], artefakty=[], logika=[], ocena="PASS".

ARTYKUŁ:
{article}"""

_EDITOR_FIX_PROMPT = """Popraw poniższy artykuł. Napraw TYLKO wymienione błędy — nie zmieniaj niczego innego.
Zachowaj DOKŁADNIE tę samą strukturę (h2:, h3:, listy, tabele). Nie dodawaj nowych sekcji.

BŁĘDY DO NAPRAWY:
{errors}

ARTYKUŁ:
{article}

Zwróć CAŁY poprawiony artykuł (bez komentarzy, bez markdown)."""

def _editor_in_chief_review(article_text, main_keyword, detected_category="inne"):
    """v2.4: Final expert review — hardened JSON parsing (never breaks workflow)."""

    if not ANTHROPIC_API_KEY or not article_text or len(article_text) < 200:
        return {"ran": False, "reason": "no_api_key_or_short_text"}

    import anthropic as _anth
    import json as _json
    import re as _re

    _category_names = {
        "prawo": "prawo i przepisy",
        "medycyna": "medycyna i zdrowie",
        "finanse": "finanse i ekonomia",
        "budownictwo": "budownictwo i nieruchomości",
        "technologia": "technologia i IT",
        "inne": "tematyka ogólna",
    }

    cat_name = _category_names.get(detected_category, detected_category or "tematyka ogólna")

    clean_text = _strip_html_for_analysis(article_text) if article_text else article_text

    try:
        client = _anth.Anthropic(api_key=ANTHROPIC_API_KEY, max_retries=1)

        review_prompt = _EDITOR_REVIEW_PROMPT.format(
            category=cat_name,
            keyword=main_keyword,
            article=clean_text[:12000]
        )

        response = client.messages.create(
            model=_get_anthropic_model(),
            max_tokens=2000,
            temperature=0,
            messages=[{"role": "user", "content": review_prompt}]
        )

        raw = response.content[0].text.strip()

        # ─────────────────────────
        # SAFE JSON EXTRACTION
        # ─────────────────────────
        json_match = _re.search(r"\{[\s\S]*\}", raw)

        if not json_match:
            logger.warning(f"[EDITOR] No JSON in response: {raw[:200]}")
            return {"ran": True, "parse_error": True, "raw": raw[:500]}

        json_block = json_match.group()

        try:
            review = _json.loads(json_block)
        except _json.JSONDecodeError as je:
            logger.warning(f"[EDITOR] JSON decode error: {je}")
            return {"ran": True, "parse_error": True, "raw": json_block[:500]}

        if not isinstance(review, dict):
            return {"ran": True, "parse_error": True}

        critical = review.get("krytyczne", [])
        artifacts = review.get("artefakty", [])
        logic = review.get("logika", [])
        verdict = review.get("ocena", "PASS")
        comment = review.get("komentarz", "")

        result = {
            "ran": True,
            "critical_count": len(critical),
            "artifact_count": len(artifacts),
            "logic_count": len(logic),
            "critical": critical[:10],
            "artifacts": artifacts[:5],
            "logic": logic[:5],
            "verdict": verdict,
            "comment": comment,
            "fixed_text": None,
            "input_tokens": getattr(response.usage, "input_tokens", 0),
            "output_tokens": getattr(response.usage, "output_tokens", 0),
        }

        # ─────────────────────────
        # AUTO-FIX
        # ─────────────────────────
        if critical or artifacts:

            errors_desc = ""

            if critical:
                errors_desc += "\n".join(
                    f"{i+1}. CYTAT: \"{e.get('cytat','')}\"\n"
                    f"   BŁĄD: {e.get('blad','')}\n"
                    f"   POPRAWKA: {e.get('poprawka','')}"
                    for i, e in enumerate(critical[:8])
                )

            if artifacts:
                if errors_desc:
                    errors_desc += "\n\n"
                errors_desc += "ARTEFAKTY DO USUNIĘCIA:\n" + "\n".join(
                    f"- \"{a.get('cytat','')}\" → {a.get('blad','')}"
                    for a in artifacts[:5]
                )

            if logic:
                errors_desc += "\n\nPROBLEMY LOGICZNE:\n" + "\n".join(
                    f"- {l.get('opis','')}"
                    for l in logic[:5]
                )

            fix_prompt = _EDITOR_FIX_PROMPT.format(
                errors=errors_desc,
                article=article_text[:12000]
            )

            fix_response = client.messages.create(
                model=_get_anthropic_model(),
                max_tokens=8000,
                temperature=0,
                messages=[{"role": "user", "content": fix_prompt}]
            )

            fixed = fix_response.content[0].text.strip()

            if fixed and len(fixed) > len(article_text) * 0.7:
                result["fixed_text"] = fixed
                result["fix_tokens"] = (
                    getattr(fix_response.usage, "input_tokens", 0)
                    + getattr(fix_response.usage, "output_tokens", 0)
                )
            else:
                logger.warning(
                    f"[EDITOR] Fix text too short ({len(fixed)} vs {len(article_text)})"
                )

        return result

    except Exception as e:
        logger.warning(f"[EDITOR] Review failed safely: {e}")
        return {"ran": False, "error": str(e)[:200]}

def _compute_grade(quality_score, salience_score, semantic_score, style_score=None):
    """
    Compute letter grade from independent scores (A+ through D).

    Salience jest celowo WYKLUCZONA z oceny końcowej — jest matematyczną
    pochodną Semantic Distance (entity_overlap * 60 + must_mention * 40),
    więc jej uwzględnienie podwójnie liczyłoby tę samą informację.

    Wagi niezależnych metryk:
      Quality  (backend final_review)  → 45%  — ocenia treść merytorycznie
      Semantic (competitor distance)   → 35%  — pokrycie tematyczne vs SERP
      Style    (polish NLP + styl)     → 20%  — jakość językowa

    Jeśli dana metryka jest niedostępna (None), wagi są redystrybuowane
    proporcjonalnie między dostępnymi.
    """
    weights = {}
    if quality_score is not None:
        weights["quality"] = (quality_score, 0.45)
    if semantic_score is not None:
        weights["semantic"] = (semantic_score, 0.35)
    if style_score is not None:
        weights["style"] = (style_score, 0.20)

    if not weights:
        return "?"

    # Redystrybuuj wagi gdy brakuje metryk
    total_weight = sum(w for _, w in weights.values())
    weighted_sum = sum(score * (w / total_weight) for score, w in weights.values())
    avg = round(weighted_sum, 1)

    if avg >= 90:
        return "A+"
    elif avg >= 80:
        return "A"
    elif avg >= 70:
        return "B+"
    elif avg >= 60:
        return "B"
    elif avg >= 45:
        return "C"
    else:
        return "D"


# ============================================================
# WORKFLOW ORCHESTRATOR (SSE)
# ============================================================
def run_workflow_sse(job_id, main_keyword, mode, h2_structure, basic_terms, extended_terms, engine="claude", openai_model=None, temperature=None, content_type="article", category_data=None, voice_preset="auto", quality_tier="ekonomiczny"):
    """
    Full BRAJEN workflow as a generator yielding SSE events.
    Follows PROMPT_v45_2.md EXACTLY:
    KROK 1: S1 → 2: YMYL → 3: (H2 already provided) → 4: Create → 5: Hierarchy →
    6: Batch Loop → 7: PAA → 8: Final Review → 9: Editorial → 10: Export

    content_type: "article" (default) or "category" (e-commerce category description)
    category_data: dict with store_name, hierarchy, products, etc. (only for category)
    quality_tier: "ekonomiczny" (Sonnet, cheaper) or "premium" (Opus, more expensive)
    """
    # Per-session model override for OpenAI
    effective_openai_model = openai_model or OPENAI_MODEL

    # v68: Quality tier — model selection per step
    # Ekonomiczny: Sonnet 4 for everything (5× cheaper)
    # Premium: Opus 4 for batch generation + editorial, Sonnet for utility calls
    _SONNET_MODEL = "claude-sonnet-4-6"
    _OPUS_MODEL = "claude-opus-4-6"
    
    if quality_tier == "premium":
        _workflow_model = _OPUS_MODEL
    else:
        _workflow_model = _SONNET_MODEL
    
    # v68 H1: Thread-local model override (thread-safe, no race condition)
    _set_anthropic_model(_workflow_model)

    # Category: force fast mode for short descriptions
    if content_type == "category":
        mode = "fast"

    def emit(event_type, data):
        """Yield SSE event."""
        return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    job = active_jobs.get(job_id, {})
    step_times = {}  # {step_num: {"start": time, "end": time}}
    workflow_start = time.time()

    engine_label = "OpenAI " + effective_openai_model if engine == "openai" else "Claude " + _get_anthropic_model()
    temp_label = f" [temp={temperature}]" if temperature is not None else ""
    ct_label = " [📦 Kategoria]" if content_type == "category" else ""
    tier_label = " [💎 Premium]" if quality_tier == "premium" else " [💰 Ekonomiczny]"
    yield emit("log", {"msg": f"🚀 Workflow: {main_keyword} [{mode}] [🤖 {engine_label}]{tier_label}{temp_label}{ct_label}"})
    
    if engine == "openai" and not OPENAI_API_KEY:
        yield emit("log", {"msg": "⚠️ OPENAI_API_KEY nie ustawiony, fallback na Claude"})
        engine = "claude"

    def step_start(num):
        step_times[num] = {"start": time.time()}

    def step_done(num):
        if num in step_times:
            step_times[num]["end"] = time.time()
            elapsed = step_times[num]["end"] - step_times[num]["start"]
            step_times[num]["elapsed"] = round(elapsed, 1)
            return round(elapsed, 1)
        return 0

    try:
        # ─── KROK 1: S1 Analysis ───
        step_start(1)
        yield emit("step", {"step": 1, "name": "S1 Analysis", "status": "running"})

        # v56: Check S1 cache first (SERP doesn't change within 24h)
        _s1_cached = _s1_cache_get(main_keyword)
        if _s1_cached:
            yield emit("log", {"msg": f"⚡ S1 cache hit: '{main_keyword}' (24h TTL)"})
            s1_raw = _s1_cached
        else:
            yield emit("log", {"msg": f"POST /api/s1_analysis → {main_keyword}"})
            s1_result = brajen_call("post", "/api/s1_analysis", {"main_keyword": main_keyword})
            if not s1_result["ok"]:
                yield emit("workflow_error", {"step": 1, "msg": f"S1 Analysis failed: {s1_result.get('error', 'unknown')}"})
                return
            s1_raw = s1_result["data"]
            _s1_cache_set(main_keyword, s1_raw)
        
        # Debug: log S1 response structure for diagnostics
        la = s1_raw.get("length_analysis", {})
        sa = s1_raw.get("serp_analysis", {})
        logger.info(f"[S1_DEBUG] top keys: {sorted(s1_raw.keys())}")
        logger.info(f"[S1_DEBUG] length_analysis: rec={la.get('recommended')}, med={la.get('median')}, avg={la.get('average')}, urls={la.get('analyzed_urls')}")
        logger.info(f"[S1_DEBUG] serp_analysis keys: {sorted(sa.keys()) if sa else 'EMPTY'}")
        logger.info(f"[S1_DEBUG] recommended_length(top): {s1_raw.get('recommended_length')}, median_length(top): {s1_raw.get('median_length')}")
        # PAA diagnostic — shows in workflow logs
        _paa_raw = s1_raw.get("paa") or s1_raw.get("paa_questions") or sa.get("paa_questions") or []
        yield emit("log", {"msg": f"🔍 S1 PAA debug: s1_raw.paa={len(s1_raw.get('paa') or [])}, s1_raw.paa_questions={len(s1_raw.get('paa_questions') or [])}, serp_analysis.paa_questions={len(sa.get('paa_questions') or [])}, s1_raw top keys={list(s1_raw.keys())[:8]}"})
        
        # ═══ AI MIDDLEWARE: Clean S1 data ═══
        s1 = process_s1_for_pipeline(s1_raw, main_keyword)
        cleanup_stats = s1.get("_cleanup_stats", {})
        cleanup_method = cleanup_stats.get("method", "unknown")
        items_removed = cleanup_stats.get("items_removed", 0)
        ai_entity_panel = s1.get("_ai_entity_panel") or {}
        garbage_summary = ai_entity_panel.get("garbage_summary", "")
        if garbage_summary:
            yield emit("log", {"msg": f"🧹 S1 cleanup ({cleanup_method}): {garbage_summary}"})
        
        h2_patterns = len((s1.get("competitor_h2_patterns") or (s1.get("serp_analysis") or {}).get("competitor_h2_patterns") or []))
        causal_count = (s1.get("causal_triplets") or {}).get("count", 0)
        gaps_count = ({} if not isinstance(s1.get("content_gaps"), dict) else s1.get("content_gaps")).get("total_gaps", 0)
        suggested_h2s = ({} if not isinstance(s1.get("content_gaps"), dict) else s1.get("content_gaps")).get("suggested_new_h2s", [])

        step_done(1)
        yield emit("step", {"step": 1, "name": "S1 Analysis", "status": "done",
                            "detail": f"{h2_patterns} H2 patterns | {causal_count} causal triplets | {gaps_count} content gaps"})
        
        # S1 data for UI, already cleaned by Claude Sonnet middleware
        entity_seo = s1.get("entity_seo") or {}
        raw_entities = entity_seo.get("top_entities", entity_seo.get("entities", []))[:35]
        raw_must_mention = entity_seo.get("must_mention_entities", [])[:15]
        raw_ngrams = (s1.get("ngrams") or s1.get("hybrid_ngrams") or [])[:60]
        serp_analysis = s1.get("serp_analysis") or {}

        # v2.3: Extract competitor first paragraphs/intros for lead generation
        _serp_competitors = serp_analysis.get("competitors", s1.get("competitors", []))
        _competitor_intros = []
        if _serp_competitors and isinstance(_serp_competitors, list):
            _comp0 = _serp_competitors[0] if _serp_competitors else {}
            _comp_keys = sorted(_comp0.keys())[:20] if isinstance(_comp0, dict) else []
            logger.info(f"[COMP_DEBUG] competitors[0] keys: {_comp_keys}")
            yield emit("log", {"msg": f"🔍 Competitors structure: {len(_serp_competitors)} items, keys: {_comp_keys[:12]}"})
            for _comp in _serp_competitors[:5]:
                if not isinstance(_comp, dict):
                    continue
                # Try common field names for intro/content/first paragraph
                _intro_text = (
                    _comp.get("first_paragraph") or _comp.get("intro") or
                    _comp.get("intro_text") or _comp.get("opening") or
                    _comp.get("lead") or _comp.get("first_paragraphs") or
                    _comp.get("content_preview") or _comp.get("excerpt") or
                    _comp.get("text") or _comp.get("content") or ""
                )
                if isinstance(_intro_text, list):
                    _intro_text = " ".join(str(p) for p in _intro_text[:2])
                _intro_text = str(_intro_text).strip()[:500]
                if len(_intro_text) > 50:
                    _comp_title = _comp.get("title", _comp.get("url", ""))[:60]
                    _competitor_intros.append({"title": _comp_title, "intro": _intro_text})
            if _competitor_intros:
                logger.info(f"[COMP_INTRO] Extracted {len(_competitor_intros)} competitor intros")
                yield emit("log", {"msg": f"📝 Wyciągnięto {len(_competitor_intros)} akapitów wstępnych z konkurencji"})

        raw_h2_patterns = (s1.get("competitor_h2_patterns") or serp_analysis.get("competitor_h2_patterns") or [])[:30]

        # v48.0: Claude already cleaned, lightweight safety net only
        clean_entities = _filter_entities(raw_entities)[:18]
        clean_must_mention = _filter_entities(raw_must_mention)[:8]
        clean_ngrams = _filter_ngrams(raw_ngrams)[:30]
        clean_h2_patterns = _filter_h2_patterns(raw_h2_patterns)[:20]

        # v48.0: Read Claude's topical/named entity split
        ai_topical = entity_seo.get("ai_topical_entities", [])
        ai_named = entity_seo.get("ai_named_entities", [])
        ai_entity_panel = s1.get("_ai_entity_panel") or {}

        # ═══ v50.4 FIX 20: TOPICAL ENTITY GENERATOR ═══
        # If N-gram API didn't produce ai_topical_entities (common failure),
        # generate proper topical entities using a fast LLM call.
        # This prevents CSS artifacts (vivid, bluish, reviews) from becoming
        # the "primary entity" in the article.
        topical_gen_result = {}
        topical_gen_entities = []
        topical_gen_placement = ""
        topical_gen_cooc = []
        topical_gen_eav = []   # EAV triples: entity → attribute → value
        topical_gen_svo = []   # SVO triples: subject → verb → object

        if not ai_topical:
            # Check if scraper entities are mostly garbage
            _clean_count = len(clean_entities)
            _raw_count = len(raw_entities)
            _garbage_ratio = 1.0 - (_clean_count / max(_raw_count, 1))
            
            # Generate topical entities if:
            # - No AI topical entities from N-gram API, AND
            # - Either high garbage ratio (>40% filtered) or very few clean entities
            if _garbage_ratio > 0.4 or _clean_count < 4:
                yield emit("log", {"msg": f"🧬 Encje ze scrapera niskiej jakości ({_clean_count}/{_raw_count} przefiltrowanych), generuję topical entities..."})
                topical_gen_result = _generate_topical_entities(main_keyword)
                
                if topical_gen_result:
                    topical_gen_entities = _topical_to_entity_list(topical_gen_result, main_keyword)
                    topical_gen_placement = _topical_to_placement_instruction(topical_gen_result, main_keyword)
                    topical_gen_cooc = _topical_to_cooccurrence(topical_gen_result)
                    topical_gen_ngrams = _topical_to_ngrams(topical_gen_result)
                    topical_gen_eav = _topical_to_eav(topical_gen_result)
                    topical_gen_svo = _topical_to_svo(topical_gen_result)

                    # Override: use topical entities as primary
                    ai_topical = topical_gen_entities
                    clean_entities = topical_gen_entities[:18]

                    # Merge semantic ngrams from topical generator into clean_ngrams
                    existing_ng_texts = set(
                        (ng.get("ngram", "") if isinstance(ng, dict) else str(ng)).lower()
                        for ng in clean_ngrams
                    )
                    new_tg_ngrams = [
                        ng for ng in topical_gen_ngrams
                        if ng.get("ngram", "").lower() not in existing_ng_texts
                    ]
                    clean_ngrams = clean_ngrams + new_tg_ngrams
                    if new_tg_ngrams:
                        yield emit("log", {"msg": f"📐 +{len(new_tg_ngrams)} semantic n-gramów z topical generatora → łącznie {len(clean_ngrams)}"})
                    if topical_gen_eav:
                        yield emit("log", {"msg": f"🔺 EAV trójki: {len(topical_gen_eav)} (encja→atrybut→wartość)"})
                    if topical_gen_svo:
                        yield emit("log", {"msg": f"🔗 SVO trójki: {len(topical_gen_svo)} (podmiot→relacja→obiekt)"})

                    _ent_names = [_extract_text(e) for e in topical_gen_entities[:5]]
                    yield emit("log", {"msg": f"🧬 Topical entities ({len(topical_gen_entities)}): {', '.join(_ent_names)}"})
                else:
                    yield emit("log", {"msg": "⚠️ Topical entity generation failed, używam przefiltrowanych encji ze scrapera"})
            else:
                # Scraper entities OK — still run topical gen for semantic ngrams
                yield emit("log", {"msg": f"✅ Encje ze scrapera OK ({_clean_count} clean) — generuję semantic n-gramy..."})
                topical_gen_result = _generate_topical_entities(main_keyword)
                if topical_gen_result:
                    topical_gen_ngrams = _topical_to_ngrams(topical_gen_result)
                    topical_gen_entities = _topical_to_entity_list(topical_gen_result, main_keyword)
                    topical_gen_placement = _topical_to_placement_instruction(topical_gen_result, main_keyword)
                    topical_gen_cooc = _topical_to_cooccurrence(topical_gen_result)
                    topical_gen_eav = _topical_to_eav(topical_gen_result)
                    topical_gen_svo = _topical_to_svo(topical_gen_result)
                    existing_ng_texts = set(
                        (ng.get("ngram", "") if isinstance(ng, dict) else str(ng)).lower()
                        for ng in clean_ngrams
                    )
                    new_tg_ngrams = [ng for ng in topical_gen_ngrams if ng.get("ngram", "").lower() not in existing_ng_texts]
                    clean_ngrams = clean_ngrams + new_tg_ngrams
                    yield emit("log", {"msg": f"📐 +{len(new_tg_ngrams)} semantic n-gramów → łącznie {len(clean_ngrams)}"})
                    if topical_gen_eav:
                        yield emit("log", {"msg": f"🔺 EAV: {len(topical_gen_eav)} | SVO: {len(topical_gen_svo)} trójek semantycznych"})

        # If Claude/N-gram API produced topical entities, use them as primary
        if ai_topical:
            clean_entities = ai_topical[:18]
            yield emit("log", {"msg": f"🧠 Topical entities: {', '.join(_extract_text(e) for e in ai_topical[:6])}"})
        if ai_named:
            yield emit("log", {"msg": f"🏷️ Named entities (AI, filtered): {', '.join(_extract_text(e) for e in ai_named[:5])}"})

        # Legacy: AI-extracted entities fallback
        ai_entities = entity_seo.get("ai_extracted_entities", [])
        if ai_entities and not ai_topical and len(clean_entities) < 5:
            yield emit("log", {"msg": f"🤖 Uzupełniam encje z AI: {', '.join(str(e) for e in ai_entities[:5])}"})

        # v48.0: concept_entities = topical from generator (or Claude, or backend)
        concept_entities = ai_topical if ai_topical else _filter_entities(
            entity_seo.get("concept_entities", []) or s1.get("concept_entities", [])
        )[:15]
        topical_summary_raw = entity_seo.get("topical_summary", {}) or s1.get("topical_summary", {})
        if isinstance(topical_summary_raw, str):
            topical_summary = {"agent_instruction": topical_summary_raw} if topical_summary_raw else {}
        else:
            topical_summary = topical_summary_raw

        # v48.0: Emit AI entity panel for dashboard
        cleanup_stats = s1.get("_cleanup_stats") or {}
        if ai_entity_panel:
            yield emit("ai_entity_panel", ai_entity_panel)
            gs = ai_entity_panel.get("garbage_summary", "")
            if gs:
                yield emit("log", {"msg": f"🧹 S1 cleanup ({cleanup_stats.get('method', '?')}): {gs[:100]}"})

        # v47.0: Read entity_salience, co-occurrence, placement from backend
        entity_seo_raw = s1.get("entity_seo") or {}
        backend_entity_salience = _filter_entities(entity_seo_raw.get("entity_salience", []) or s1.get("entity_salience", []))
        backend_entity_cooccurrence = _filter_cooccurrence(entity_seo_raw.get("entity_cooccurrence", []) or s1.get("entity_cooccurrence", []))
        backend_entity_placement = (
            s1.get("entity_placement") or
            entity_seo_raw.get("entity_placement", {})
        )
        backend_placement_instruction = _sanitize_placement_instruction(
            (s1.get("semantic_enhancement_hints") or {}).get("placement_instruction", "") or
            (backend_entity_placement.get("placement_instruction", "") if isinstance(backend_entity_placement, dict) else "")
        )
        # v47.0: Read enhanced semantic hints
        sem_hints = s1.get("semantic_enhancement_hints") or s1.get("semantic_hints") or {}
        backend_first_para_entities = _filter_entities(
            sem_hints.get("first_paragraph_entities", []) or
            (backend_entity_placement.get("first_paragraph_entities", []) if isinstance(backend_entity_placement, dict) else [])
        )
        backend_h2_entities = _filter_entities(
            sem_hints.get("h2_entities", []) or
            (backend_entity_placement.get("h2_entities", []) if isinstance(backend_entity_placement, dict) else [])
        )
        backend_cooccurrence_pairs = _filter_cooccurrence(
            sem_hints.get("cooccurrence_pairs", []) or
            (backend_entity_placement.get("cooccurrence_pairs", []) if isinstance(backend_entity_placement, dict) else [])
        )[:5]
        # v47.0: must_cover_concepts & concept_instruction from semantic_enhancement_hints
        must_cover_concepts = _filter_entities(sem_hints.get("must_cover_concepts", []) or (topical_summary.get("must_cover", []) if isinstance(topical_summary, dict) else []))
        concept_instruction = _sanitize_placement_instruction(sem_hints.get("concept_instruction", "") or (topical_summary.get("agent_instruction", "") if isinstance(topical_summary, dict) else ""))
        # v61 FIX: Filter must_cover_concepts — remove n-gram fragments (not true entities)
        must_cover_concepts = _filter_must_cover_concepts(must_cover_concepts)

        # ═══ v50.4 FIX 20: Override backend placement with topical-generated data ═══
        # When topical entity generator was used, its output is BETTER than
        # the scraper-sourced placement (which may contain CSS artifacts,
        # brand contacts, and sentence fragments from competitor pages).
        if topical_gen_placement:
            backend_placement_instruction = topical_gen_placement
            yield emit("log", {"msg": "🧬 Placement instruction: z topical entity generator (zamiast scrapera)"})
        elif ai_topical and not topical_gen_entities:
            # v50.7 FIX 44: N-gram API gave entities but no placement, build from entities
            # v50.7 FIX 47: Use _extract_text(): handles str+dict
            _ai_names = [_extract_text(e) for e in ai_topical[:8] if _extract_text(e)]
            if _ai_names:
                _lines = [
                    f'🎯 ENCJA GŁÓWNA: "{_ai_names[0]}"',
                    f'   → W tytule H1 i w pierwszym zdaniu artykułu',
                ]
                if len(_ai_names) > 1:
                    _lines.append(f'📌 PIERWSZY AKAPIT: Wprowadź razem: {", ".join(_ai_names[:3])}')
                if len(_ai_names) > 3:
                    _lines.append(f'📋 ENCJE TEMATYCZNE:')
                    for _n in _ai_names[1:]:
                        _lines.append(f'   • "{_n}" (CONCEPT)')
                backend_placement_instruction = "\n".join(_lines)
                yield emit("log", {"msg": f"🧬 Placement instruction: wygenerowane z ai_topical entities ({len(_ai_names)} encji)"})
        if topical_gen_cooc:
            backend_cooccurrence_pairs = topical_gen_cooc + backend_cooccurrence_pairs[:2]
            yield emit("log", {"msg": f"🧬 Co-occurrence: {len(topical_gen_cooc)} par z topical generator"})
        if (topical_gen_entities or ai_topical) and not must_cover_concepts:
            # Use clean topical entities as must_cover_concepts
            must_cover_concepts = (topical_gen_entities or ai_topical)[:14]

        # ═══ v50.4 FIX 21 + v50.7 FIX 44: Override ALL contamination paths ═══
        # Override with clean topical entities regardless of source:
        # - topical_gen_entities: from topical generator (when scraper data was garbage)
        # - ai_topical: from N-gram API concept extraction (when API provided entities)
        # Without this, sem_hints/placement/salience keep raw S1 CSS garbage.
        _override_entities = topical_gen_entities or ai_topical or []
        if _override_entities:
            # Override first paragraph entities with topical primary + top 2 secondary
            backend_first_para_entities = _override_entities[:3]
            # Override H2 entities with remaining topical entities
            backend_h2_entities = _override_entities[3:8]
            # Override entity salience with topical-generated entities
            # (prevents "Asturianu Azərbaycanca" as primary in dashboard)
            backend_entity_salience = []
            for i, ent in enumerate(_override_entities[:12]):
                ent_name = _extract_text(ent)
                ent_type = ent.get("type", "CONCEPT") if isinstance(ent, dict) else "CONCEPT"
                if i == 0:
                    # Primary entity always 0.85
                    _sal = 0.85
                elif isinstance(ent, dict) and ent.get("salience"):
                    # v62: Use structurally computed salience (patent-inspired: cooc+svo+type)
                    _sal = ent["salience"]
                else:
                    # Fallback: linear decay
                    _sal = round(0.85 - (i * 0.06), 2)
                backend_entity_salience.append({
                    "entity": ent_name,
                    "salience": max(0.05, _sal),
                    "type": ent_type,
                    "source": "topical_override"
                })
            yield emit("log", {"msg": f"🧬 Entity salience + first_para + H2: nadpisane ({len(backend_entity_salience)} encji, src={'topical_gen' if topical_gen_entities else 'ai_topical'})"})

            # v50.5 FIX 35: Also override backend_entity_placement for dashboard display
            # v50.7 FIX 47: Use _extract_text(): handles str+dict
            _fp_names = [_extract_text(e) for e in backend_first_para_entities]
            _h2_names = [_extract_text(e) for e in backend_h2_entities]
            backend_entity_placement = {
                "first_paragraph_entities": _fp_names,
                "h2_entities": _h2_names,
                "placement_instruction": backend_placement_instruction,
                "source": "topical_override"
            }

            # v50.7 FIX 34: Override sem_hints with clean topical data
            # v50.7 FIX 47: Use _extract_text(): handles str+dict
            _primary_name = _extract_text(_override_entities[0]) if _override_entities else main_keyword
            _secondary_names = [_extract_text(e) for e in _override_entities[1:4]]
            sem_hints = {
                # v50.7 FIX 44: Include BOTH "text" and "entity" keys
                # Dashboard reads .entity, backend reads .text
                "primary_entity": {"text": _primary_name, "entity": _primary_name, "type": "CONCEPT", "salience": 0.85, "source": "topical_override"},
                "secondary_entities": [{"text": n, "entity": n, "type": "CONCEPT"} for n in _secondary_names],
                "must_cover_concepts": [_extract_text(e) for e in (must_cover_concepts or _override_entities[:8])],
                "placement_instruction": backend_placement_instruction,
                "first_paragraph_entities": _fp_names,
                "h2_entities": _h2_names,
                "cooccurrence_pairs": backend_cooccurrence_pairs[:5] if backend_cooccurrence_pairs else [],
                "concept_instruction": (
                    # v61 FIX: Build proper entity-first concept instruction from topical generator
                    # instead of keeping bad n-gram concept_instruction from S1 API
                    _build_concept_instruction_from_topical(topical_gen_result or {}, main_keyword)
                    or _build_concept_instruction_from_topical({"secondary_entities": [{
                        "text": _extract_text(e), "type": (e.get("type","CONCEPT") if isinstance(e,dict) else "CONCEPT")
                    } for e in (_override_entities or [])[:12]]}, main_keyword)
                    or concept_instruction
                ),
                "checkpoints": {
                    "batch_1": f"H1 contains '{_primary_name}', first paragraph mentions {', '.join(_secondary_names[:2])}",
                    "batch_3": "entity_density >= 2.5, min 50% critical entities, min 30% must_cover_concepts",
                    "batch_5": "topic_completeness >= 50%, concept coverage >= 50%",
                    "pre_faq": "all critical entities present, all MUST topics covered",
                },
                "source": "topical_override"
            }
            yield emit("log", {"msg": f"🧬 sem_hints: nadpisane (primary: {_primary_name}, src={'topical_gen' if topical_gen_entities else 'ai_topical'})"})

        if backend_entity_salience:
            yield emit("log", {"msg": f"🔬 Entity Salience: {len(backend_entity_salience)} encji z analizy konkurencji"})
        if backend_entity_cooccurrence:
            yield emit("log", {"msg": f"🔗 Co-occurrence: {len(backend_entity_cooccurrence)} par encji"})
        if backend_placement_instruction:
            yield emit("log", {"msg": "📐 Placement instructions: wygenerowane z analizy konkurencji"})
        if must_cover_concepts:
            yield emit("log", {"msg": f"💡 Must-cover concepts: {len(must_cover_concepts)} pojęć tematycznych"})

        # v45.4.1: Filter semantic_keyphrases (Gemini may return YouTube/JS garbage)
        raw_semantic_kp = s1.get("semantic_keyphrases") or []
        clean_semantic_kp = [kp for kp in raw_semantic_kp if not _is_css_garbage(
            kp.get("phrase", kp) if isinstance(kp, dict) else str(kp)
        )]

        # v45.4.1: Filter causal triplets: remove CSS-contaminated extractions
        def _filter_causal(triplets):
            """Remove causal triplets where cause/effect looks like CSS or truncated."""
            if not triplets:
                return []
            clean = []
            for t in triplets:
                cause = t.get("cause", t.get("from", ""))
                effect = t.get("effect", t.get("to", ""))
                # Skip if cause or effect is too short, too long, or CSS garbage
                if len(cause) < 5 or len(effect) < 5:
                    continue
                if len(cause) > 120 or len(effect) > 120:
                    continue  # Truncated sentence fragments
                if _is_css_garbage(cause) or _is_css_garbage(effect):
                    continue
                # v50.7 FIX 39: Detect truncated sentence fragments
                # "unkiem, że opiera się..." starts mid-word → garbage
                cause_stripped = cause.strip()
                effect_stripped = effect.strip()
                if cause_stripped and cause_stripped[0].islower() and not cause_stripped.startswith(("np.", "tj.", "m.in.")):
                    # Starts mid-word/mid-sentence, likely truncated scrape
                    # Check if first word looks like a Polish suffix (ends with -iem, -iem, -ych, -ów)
                    first_word = cause_stripped.split()[0].rstrip(",.:;")
                    if len(first_word) < 4 or first_word.endswith(("iem", "iem", "ych", "ów", "ami", "ach", "owi")):
                        continue
                if effect_stripped and effect_stripped[0].islower() and not effect_stripped.startswith(("np.", "tj.", "m.in.")):
                    first_word = effect_stripped.split()[0].rstrip(",.:;")
                    if len(first_word) < 4 or first_word.endswith(("iem", "iem", "ych", "ów", "ami", "ach", "owi")):
                        continue
                clean.append(t)
            return clean

        raw_causal_chains = (s1.get("causal_triplets") or {}).get("chains", [])[:10]
        raw_causal_singles = (s1.get("causal_triplets") or {}).get("singles", [])[:10]
        clean_causal_chains = _filter_causal(raw_causal_chains)
        clean_causal_singles = _filter_causal(raw_causal_singles)

        # v50.7 FIX 45: Comprehensive AI cleanup: one call cleans EVERYTHING
        # Replaces regex whack-a-mole with AI that understands context (~$0.008, ~2s)
        try:
            ai_cleanup = _ai_cleanup_all_s1_data(
                main_keyword=main_keyword,
                ngrams=clean_ngrams,
                causal_chains=clean_causal_chains,
                causal_singles=clean_causal_singles,
                placement_instruction=backend_placement_instruction,
                entity_salience=backend_entity_salience,
                entities=clean_entities,
            )
            _pre = {"ng": len(clean_ngrams), "cc": len(clean_causal_chains)+len(clean_causal_singles),
                    "sal": len(backend_entity_salience), "ent": len(clean_entities)}
            
            clean_ngrams = ai_cleanup["ngrams"]
            clean_causal_chains = ai_cleanup["causal_chains"]
            clean_causal_singles = ai_cleanup["causal_singles"]
            total_causal = len(clean_causal_chains) + len(clean_causal_singles)
            if not total_causal:
                yield emit("log", {"msg": f"⚠️ Causal triplets: brak danych (raw chains={len(raw_causal_chains)}, singles={len(raw_causal_singles)})"})
            backend_placement_instruction = ai_cleanup["placement_instruction"]
            backend_entity_salience = ai_cleanup["entity_salience"]
            clean_entities = ai_cleanup["entities"]
            
            _post = {"ng": len(clean_ngrams), "cc": len(clean_causal_chains)+len(clean_causal_singles),
                     "sal": len(backend_entity_salience), "ent": len(clean_entities)}
            
            changes = []
            if _pre["ng"] != _post["ng"]: changes.append(f"n-gramy {_pre['ng']}→{_post['ng']}")
            if _pre["cc"] != _post["cc"]: changes.append(f"kauzalne {_pre['cc']}→{_post['cc']}")
            if _pre["sal"] != _post["sal"]: changes.append(f"salience {_pre['sal']}→{_post['sal']}")
            if _pre["ent"] != _post["ent"]: changes.append(f"encje {_pre['ent']}→{_post['ent']}")
            
            if changes:
                yield emit("log", {"msg": f"🧹 AI cleanup: {' | '.join(changes)}"})
            else:
                yield emit("log", {"msg": "🧹 AI cleanup: dane czyste, bez zmian"})
        except Exception as ai_err:
            logger.warning(f"[AI_CLEANUP] Error in workflow: {ai_err}")

        if concept_entities:
            yield emit("log", {"msg": f"🧠 Concept entities: {len(concept_entities)} (z topical_entity_extractor)"})
        if len(clean_ngrams) < len(raw_ngrams) * 0.5:
            yield emit("log", {"msg": f"⚠️ N-gramy: {len(raw_ngrams) - len(clean_ngrams)}/{len(raw_ngrams)} odfiltrowane jako CSS garbage"})
        # ═══ ENTITY GAP ANALYSIS — find missing entities before writing ═══
        entity_gaps = []
        try:
            all_found_entities = list(ai_topical) + list(ai_named) + list(clean_entities)
            if all_found_entities:
                entity_gaps = analyze_entity_gaps(main_keyword, all_found_entities)
                if entity_gaps:
                    yield emit("log", {"msg": f"🔍 Entity gaps: {len(entity_gaps)} luk encyjnych znalezionych ({sum(1 for g in entity_gaps if g.get('priority')=='high')} high)"})
        except Exception as eg_err:
            logger.warning(f"[ENTITY_GAP] Error: {eg_err}")

        # PAA diagnostics
        paa_debug = s1.get("paa") or s1.get("paa_questions") or serp_analysis.get("paa_questions") or []
        if not paa_debug:
            yield emit("log", {"msg": f"⚠️ PAA: brak pytań w s1.paa={len(s1.get('paa') or [])}, s1.paa_questions={len(s1.get('paa_questions') or [])}, serp.paa_questions={len(serp_analysis.get('paa_questions') or [])}"})
            # v59.1: Client-side PAA fallback — generate with Claude when SERP has none
            paa_fallback = _generate_paa_fallback(main_keyword)
            if paa_fallback:
                s1["paa"] = paa_fallback
                paa_debug = paa_fallback
                yield emit("log", {"msg": f"🤖 PAA fallback: Claude wygenerował {len(paa_fallback)} pytań"})
            else:
                yield emit("log", {"msg": "⚠️ PAA fallback: nie udało się wygenerować pytań"})
        else:
            yield emit("log", {"msg": f"✅ PAA: {len(paa_debug)} pytań z SERP"})
        yield emit("s1_data", {
            # Stats for top bar, backend nests these in length_analysis{}
            "recommended_length": s1.get("recommended_length") or (s1.get("length_analysis") or {}).get("recommended"),
            "median_length": s1.get("median_length") or (s1.get("length_analysis") or {}).get("median", 0),
            "average_length": (s1.get("length_analysis") or {}).get("average") or s1.get("average_length") or s1.get("avg_length"),
            "analyzed_urls": (s1.get("length_analysis") or {}).get("analyzed_urls") or s1.get("analyzed_urls") or s1.get("urls_analyzed") or s1.get("competitor_count"),
            "word_counts": (s1.get("length_analysis") or {}).get("word_counts") or s1.get("word_counts") or [],
            "length_analysis": s1.get("length_analysis") or {},
            # SERP competitor data
            "serp_competitors": (s1.get("serp_analysis") or {}).get("competitors", s1.get("competitors", []))[:10],
            "competitor_titles": serp_analysis.get("competitor_titles", [])[:10],
            "competitor_snippets": serp_analysis.get("competitor_snippets", [])[:10],
            "competitor_intros": _competitor_intros,  # v2.3: first paragraphs from scraped pages
            # Competitor structure
            "h2_patterns_count": len(clean_h2_patterns),
            "competitor_h2_patterns": clean_h2_patterns,
            "search_intent": s1.get("search_intent") or serp_analysis.get("search_intent", ""),
            "serp_sources": s1.get("serp_sources") or serp_analysis.get("competitor_urls") or s1.get("competitor_urls") or [],
            "featured_snippet": s1.get("featured_snippet") or serp_analysis.get("featured_snippet"),
            "ai_overview": s1.get("ai_overview") or serp_analysis.get("ai_overview"),
            "related_searches": s1.get("related_searches") or serp_analysis.get("related_searches") or [],
            "refinement_chips": s1.get("refinement_chips") or serp_analysis.get("refinement_chips") or [],  # v60: Google search chips
            # PAA: check multiple locations
            "paa_questions": (s1.get("paa") or s1.get("paa_questions") or serp_analysis.get("paa_questions") or (s1_raw.get("serp_analysis") or {}).get("paa_questions") or s1_raw.get("paa") or [])[:10],
            # Causal triplets
            "causal_triplets_count": len(clean_causal_chains) + len(clean_causal_singles),
            "causal_count_chains": len(clean_causal_chains),
            "causal_count_singles": len(clean_causal_singles),
            "causal_chains": clean_causal_chains,
            "causal_singles": clean_causal_singles,
            "causal_instruction": (s1.get("causal_triplets") or {}).get("agent_instruction", ""),
            # Gap analysis
            "content_gaps_count": gaps_count,
            "content_gaps": (s1.get("content_gaps") or {}),
            "suggested_h2s": suggested_h2s,
            "paa_unanswered": ({} if not isinstance(s1.get("content_gaps"), dict) else s1.get("content_gaps")).get("paa_unanswered", []),
            "subtopic_missing": ({} if not isinstance(s1.get("content_gaps"), dict) else s1.get("content_gaps")).get("subtopic_missing", []),
            "depth_missing": ({} if not isinstance(s1.get("content_gaps"), dict) else s1.get("content_gaps")).get("depth_missing", []),
            "gaps_instruction": ({} if not isinstance(s1.get("content_gaps"), dict) else s1.get("content_gaps")).get("instruction", ""),
            # Entity SEO: v48.0: topical entities primary
            "entity_seo": {
                "top_entities": clean_entities,
                "must_mention": clean_must_mention,
                "ai_extracted": ai_entities[:5] if ai_entities else [],
                "entity_count": (s1.get("entity_seo") or {}).get("entity_count", len(clean_entities)),
                "relations": (s1.get("entity_seo") or {}).get("relations", [])[:10],
                "topical_coverage": (s1.get("entity_seo") or {}).get("topical_coverage", [])[:10],
                # v48.0: Topical (primary) vs Named (secondary) from Claude
                "topical_entities": ai_topical[:18] if ai_topical else concept_entities[:18],
                "named_entities": ai_named[:8] if ai_named else [],
                "concept_entities": concept_entities,
                "topical_summary": topical_summary,
                # v47.0: Salience, co-occurrence, placement from backend
                "entity_salience": backend_entity_salience[:25],
                "entity_cooccurrence": backend_entity_cooccurrence[:10],
                "entity_placement": backend_entity_placement if isinstance(backend_entity_placement, dict) else {},
                # v48.0: Cleanup info
                "cleanup_method": cleanup_stats.get("method", "unknown"),
                # v2.3: Synonimy — wypełniane po _generate_search_variants (patrz niżej)
                "entity_synonyms": [],
                # v57.1: Multi-entity synonyms usunięte — secondary warianty 
                # są teraz w search_variants.secondary
                "multi_entity_synonyms": {},
            },
            # v47.0: Placement instruction (top-level for easy access)
            "placement_instruction": backend_placement_instruction,
            # v47.0: Concept coverage fields
            "must_cover_concepts": must_cover_concepts[:14],
            "concept_instruction": concept_instruction,
            # N-grams
            "ngrams": clean_ngrams,
            "semantic_keyphrases": clean_semantic_kp,
            # Phrase hierarchy
            "phrase_hierarchy_preview": s1.get("phrase_hierarchy_preview") or {},
            # Depth signals
            "depth_signals": s1.get("depth_signals") or {},
            "depth_missing_items": s1.get("depth_missing_items") or ({} if not isinstance(s1.get("content_gaps"), dict) else s1.get("content_gaps")).get("depth_missing", []),
            # YMYL hints
            "ymyl_hints": s1.get("ymyl_hints") or s1.get("ymyl_signals") or {},
            # PAA (already included above with serp_analysis fallback)
            "paa_unanswered_count": len(({} if not isinstance(s1.get("content_gaps"), dict) else s1.get("content_gaps")).get("paa_unanswered", [])),
            # Agent instructions
            "agent_instructions": s1.get("agent_instructions") or {},
            "semantic_hints": sem_hints,
            # Meta
            "competitive_summary": s1.get("_competitive_summary", ""),
            # v57: Entity gap analysis — missing entities before writing
            "entity_gaps": entity_gaps,
            # v2.3: Entity variant dict + search variants — populated later
            "entity_variant_dict": {},
            "search_variants": {},
        })

        # ═══ v2.3: SERP Features panel — AI Overview, Featured Snippet, competitor snippets ═══
        _fs = s1.get("featured_snippet") or serp_analysis.get("featured_snippet")
        _aio = s1.get("ai_overview") or serp_analysis.get("ai_overview")
        _comp_snippets = serp_analysis.get("competitor_snippets", [])[:10]
        _related = s1.get("related_searches") or serp_analysis.get("related_searches") or []
        _chips = s1.get("refinement_chips") or serp_analysis.get("refinement_chips") or []
        _paa = (s1.get("paa") or s1.get("paa_questions") or serp_analysis.get("paa_questions") or [])[:10]
        _paa_unanswered = ({} if not isinstance(s1.get("content_gaps"), dict) else s1.get("content_gaps")).get("paa_unanswered", [])

        yield emit("serp_features", {
            "featured_snippet": {
                "exists": bool(_fs),
                "title": (_fs or {}).get("title", ""),
                "answer": (_fs or {}).get("answer", ""),
                "source": (_fs or {}).get("source", ""),
                "displayed_link": (_fs or {}).get("displayed_link", ""),
            } if _fs else None,
            "ai_overview": {
                "exists": bool(_aio),
                "text": (_aio or {}).get("text", ""),
                "sources": (_aio or {}).get("sources", [])[:5],
                "block_count": len((_aio or {}).get("text_blocks", [])),
            } if _aio else None,
            "paa": {
                "total": len(_paa),
                "unanswered": len(_paa_unanswered),
                "questions": [q if isinstance(q, str) else q.get("question", q.get("text", str(q))) for q in _paa],
                "unanswered_questions": [q if isinstance(q, str) else q.get("question", q.get("text", str(q))) for q in _paa_unanswered],
            },
            "competitor_snippets": [
                {"title": c.get("title", ""), "snippet": c.get("snippet", c.get("description", "")), "url": c.get("url", "")}
                for c in _comp_snippets if isinstance(c, dict)
            ][:10],
            "related_searches": _related[:8],
            "refinement_chips": _chips[:8],
        })
        _serp_parts = []
        if _fs: _serp_parts.append("snippet ✅")
        if _aio: _serp_parts.append(f"AI overview ✅ ({len((_aio or {}).get('text', ''))} ch)")
        _serp_parts.append(f"PAA {len(_paa)} ({len(_paa_unanswered)} bez odp.)")
        if _comp_snippets: _serp_parts.append(f"snippety {len(_comp_snippets)}")
        if _related: _serp_parts.append(f"related {len(_related)}")
        if _chips: _serp_parts.append(f"chips {len(_chips)}")
        yield emit("log", {"msg": f"🔍 SERP features: {' | '.join(_serp_parts)}"})

        # ═══ ENTITY SALIENCE: Build instructions from topical entities (primary) ═══
        # v48.0: Topical entities first, then NER, then fallback
        s1_must_mention = []
        if ai_topical:
            s1_must_mention = ai_topical[:5]
        elif clean_must_mention:
            s1_must_mention = clean_must_mention
        if ai_entities and len(s1_must_mention) < 5:
            s1_must_mention += ai_entities[:3]
        entity_salience_instructions = build_entity_salience_instructions(
            main_keyword=main_keyword,
            entities_from_s1=s1_must_mention
        )
        if is_salience_available():
            yield emit("log", {"msg": "🔬 Entity Salience: Google NLP API aktywne, walidacja po zakończeniu artykułu"})
        else:
            yield emit("log", {"msg": "ℹ️ Entity Salience: instrukcje pozycjonowania encji aktywne (brak API key dla walidacji)"})

        # ─── KROK 2: YMYL Detection (Unified Claude Classifier) ───
        step_start(2)
        yield emit("step", {"step": 2, "name": "YMYL Detection", "status": "running"})

        # v47.2: ONE Claude Sonnet call → classifies + returns search hints
        # v50.7 FIX 46: Run LOCALLY (Haiku) instead of broken brajen_call to master-seo-api
        # 🆕 Fix #13 v4.2: Use _detect_ymyl (pre-filter + master enrichment) instead of _detect_ymyl_local
        ymyl_data = _detect_ymyl(main_keyword)
        _detected_category = ymyl_data.get("category", "general")  # v2.3: stored for Redaktor Naczelny
        is_legal = ymyl_data.get("is_legal", False)
        is_medical = ymyl_data.get("is_medical", False)
        is_finance = ymyl_data.get("is_finance", False)
        ymyl_confidence = ymyl_data.get("confidence", 0)
        ymyl_reasoning = ymyl_data.get("reasoning", "")
        # v50: YMYL intensity: full/light/none
        ymyl_intensity = ymyl_data.get("ymyl_intensity", "none")
        light_ymyl_note = ymyl_data.get("light_ymyl_note", "")
        
        if ymyl_reasoning:
            intensity_emoji = {"full": "🔴", "light": "🟡", "none": "⚪"}.get(ymyl_intensity, "⚪")
            yield emit("log", {"msg": f"🧠 YMYL klasyfikacja: {ymyl_data.get('category', '?')} ({ymyl_confidence}) intensity={ymyl_intensity} {intensity_emoji} | {ymyl_reasoning[:80]}"})

        legal_context = None
        medical_context = None
        ymyl_enrichment = {}  # Claude's hints for downstream
        judgments_clean = []  # v2.4: init before conditional block

        # ═══ v66: ASYNC YMYL ENRICHMENT — fetch SAOS/PubMed/Wikipedia in background ═══
        # Classification is done (fast). Data fetching is slow (SAOS 30s timeout).
        # Launch in background thread — data will be ready before batch loop.
        import threading
        _ymyl_enrichment_result = {"legal_context": None, "medical_context": None,
                                   "ymyl_enrichment": {}, "judgments_clean": [],
                                   "_wiki_articles": [], "done": False}
        _ymyl_thread = None

        def _fetch_ymyl_enrichment_async():
            """Background thread for YMYL data fetching."""
            try:
                _lc = None
                _mc = None
                _ye = {}
                _jc = []
                _wa = []

                if is_legal:
                    legal_hints = ymyl_data.get("legal", {})
                    articles_raw = legal_hints.get("articles", [])
                    articles = _validate_legal_articles(articles_raw)

                    # SAOS fetch
                    lc = brajen_call("post", "/api/legal/get_context", {
                        "main_keyword": main_keyword,
                        "force_enable": True,
                        "article_hints": articles,
                        "search_queries": legal_hints.get("search_queries", []),
                    }, timeout=30)
                    if lc["ok"]:
                        _lc = lc["data"]

                    # Wikipedia enrichment
                    if articles:
                        _wa = _enrich_legal_with_wikipedia(articles)

                    _ye["legal"] = legal_hints
                    _ye["_wiki_articles"] = _wa

                    # Process judgments
                    if _lc:
                        judgments_raw = _lc.get("top_judgments") or []
                        _legal_enrich_hints = _ye.get("legal", {})
                        _articles_hints = _legal_enrich_hints.get("articles", [])
                        _arts_str = " ".join(_articles_hints).lower()
                        _is_criminal = any(x in _arts_str for x in ["k.k.", "kk", "k.w.", "kw", "kodeks karny"])
                        _is_civil = any(x in _arts_str for x in ["k.c.", "kc", "k.r.o.", "kodeks cywilny"])
                        _CRIM_SIG = ("ii k", "iii k", "iv k", "aka", "ako", "akz", "ii ka", "iii ka", "iv ka")
                        _CIV_SIG = (" i c ", " ii c ", " iii c ", " aca ", " aco ")
                        for j in judgments_raw[:10]:
                            if not isinstance(j, dict): continue
                            sig = (j.get("signature", j.get("caseNumber", "")) or "").lower()
                            sig_p = " " + sig + " "
                            if _is_criminal and not _is_civil and any(p in sig_p for p in _CIV_SIG):
                                continue
                            if _is_civil and not _is_criminal and any(p in sig_p for p in _CRIM_SIG):
                                continue
                            _jc.append({
                                "signature": j.get("signature", j.get("caseNumber", "")),
                                "court": j.get("court", j.get("courtName", "")),
                                "date": j.get("date", j.get("judgmentDate", "")),
                                "summary": (j.get("summary", j.get("excerpt", "")))[:150],
                                "type": j.get("type", j.get("judgmentType", "")),
                                "matched_article": j.get("matched_article", ""),
                            })

                if is_medical:
                    medical_hints = ymyl_data.get("medical", {})
                    mesh = medical_hints.get("mesh_terms", [])
                    mc = brajen_call("post", "/api/medical/get_context", {
                        "main_keyword": main_keyword,
                        "force_enable": True,
                        "mesh_hints": mesh,
                        "condition_en": medical_hints.get("condition_latin", ""),
                        "specialization": medical_hints.get("specialization", ""),
                        "key_drugs": medical_hints.get("key_drugs", []),
                        "evidence_note": medical_hints.get("evidence_note", ""),
                    })
                    if mc["ok"]:
                        _mc = mc["data"]
                    if _mc is None:
                        spec = medical_hints.get("specialization", "")
                        _mc = {
                            "fallback": True,
                            "disclaimer": "Informacje zawarte w artykule mają charakter wyłącznie edukacyjny i informacyjny. Nie zastępują porady lekarskiej ani diagnozy. W razie wątpliwości skonsultuj się z lekarzem.",
                            "institutions": ["WHO", "NFZ", "PTOiAu"],
                            "evidence_note": "Treść oparta na aktualnych wytycznych medycznych.",
                            "mesh_terms": mesh,
                            "specialization": spec,
                        }
                    _ye["medical"] = medical_hints

                if is_finance:
                    _ye["finance"] = ymyl_data.get("finance", {})

                _ymyl_enrichment_result["legal_context"] = _lc
                _ymyl_enrichment_result["medical_context"] = _mc
                _ymyl_enrichment_result["ymyl_enrichment"] = _ye
                _ymyl_enrichment_result["judgments_clean"] = _jc
                _ymyl_enrichment_result["_wiki_articles"] = _wa
            except Exception as _ye_err:
                logger.warning(f"[YMYL_ASYNC] Enrichment failed: {_ye_err}")
            finally:
                _ymyl_enrichment_result["done"] = True

        if is_legal or is_medical or is_finance:
            yield emit("log", {"msg": "🔄 YMYL enrichment: uruchamiam w tle (nie blokuję H2 planning)..."})
            _ymyl_thread = threading.Thread(target=_fetch_ymyl_enrichment_async, daemon=True)
            _ymyl_thread.start()

        ymyl_detail = f"Legal: {'TAK' if is_legal else 'NIE'} | Medical: {'TAK' if is_medical else 'NIE'} | Finance: {'TAK' if is_finance else 'NIE'}"

        # v66: Mark YMYL step as done immediately after classification
        # Enrichment data will be collected before batch loop
        step_done(2)
        yield emit("step", {"step": 2, "name": "YMYL Detection", "status": "done", "detail": ymyl_detail})

        # ─── v51: Auto-generate BASIC phrases from S1 entity + ngram frequency ───
        if not basic_terms:
            auto_basic = []
            auto_extended_long = []  # v60: n-grams ≥4 words → EXTENDED (not BASIC)
            seen_texts = set()
            
            # === 1. ENTITIES (primary, Surfer-style) ===
            # Topical entities have per-source frequency from competition
            all_entity_sources = []
            _first_topical_seen = False  # v57.1: track if first topical entity was processed
            if ai_topical:
                all_entity_sources.extend(ai_topical)
            if clean_entities:
                all_entity_sources.extend(clean_entities)
            
            for ent in all_entity_sources:
                if not isinstance(ent, dict):
                    continue
                text = (ent.get("text") or ent.get("entity") or ent.get("display_text") or "").strip()
                if not text or text.lower() in seen_texts:
                    continue
                
                freq_min = ent.get("freq_min", 0)
                freq_max = ent.get("freq_max", 0)
                freq_median = ent.get("freq_median", 0)
                sources_count = ent.get("sources_count", 0)
                is_topical = (
                    ent.get("source") in ("topical_generator", "ai_cleanup", "concept_entities")
                    or ent.get("type", "").upper() == "TOPICAL"
                    or ent.get("eav") or ent.get("is_primary")
                )
                
                if is_topical:
                    # v57.1 FIX: Topical entities bypass freq filter — use salience-based targets
                    # First topical entity = primary (highest salience), rest = secondary
                    is_primary = ent.get("is_primary") or not _first_topical_seen
                    _first_topical_seen = True
                    if is_primary:
                        target_min, target_max = 3, 8
                    else:
                        target_min, target_max = 2, 5
                elif sources_count >= 2 and freq_median >= 1:
                    # Original: entity with competition frequency data
                    target_min = max(1, freq_median)
                    target_max = max(target_min + 1, (freq_median + freq_max) // 2)
                    target_min = min(target_min, 25)
                    target_max = min(target_max, 30)
                else:
                    continue
                
                auto_basic.append(f"{text}: {target_min}-{target_max}x")
                seen_texts.add(text.lower())
            
            entity_count = len(auto_basic)
            
            # === 2. N-GRAMS (supplementary) ===
            for ng in (clean_ngrams or []):
                if not isinstance(ng, dict):
                    continue
                text = ng.get("ngram", "")
                if not text or text.lower() in seen_texts:
                    continue
                
                freq_median = ng.get("freq_median", 0)
                freq_max = ng.get("freq_max", 0)
                sites = ng.get("site_distribution", "0/0")
                
                try:
                    site_count = int(sites.split("/")[0])
                    site_total = int(sites.split("/")[1]) if "/" in sites else 1
                except (ValueError, IndexError):
                    site_count = 0
                    site_total = 1
                
                # v58: Relaxed filter — include rare but topically valid n-grams
                # OLD: site_count < 2 or freq_median < 2 (missed ~70% of Surfer-comparable phrases)
                # NEW: include if present in ≥1 competitor OR if freq_median ≥ 1
                if site_count < 1 and freq_median < 1:
                    continue
                
                # Rare phrases (in 1 competitor or low freq) → suggest low target
                if site_count <= 1 or freq_median <= 1:
                    target_min = 1
                    target_max = max(2, freq_max or 2)
                else:
                    target_min = max(1, freq_median)
                    target_max = max(target_min + 1, (freq_median + freq_max) // 2)
                target_min = min(target_min, 25)
                target_max = min(target_max, 30)
                
                # v60 FIX: N-grams with ≥4 words → EXTENDED (low targets 1-2)
                # They're too long for BASIC — GPT can't naturally repeat them 3-5x
                word_count_ng = len(text.split())
                if word_count_ng >= 4:
                    auto_extended_long.append(f"{text}: 1-2x")
                else:
                    auto_basic.append(f"{text}: {target_min}-{target_max}x")
                seen_texts.add(text.lower())
            
            if auto_basic:
                basic_terms = auto_basic[:40]
                ngram_count = len(auto_basic) - entity_count
                yield emit("log", {"msg": f"📊 Auto-BASIC z S1: {len(basic_terms)} fraz ({entity_count} encji + {ngram_count} n-gramów)"})
                yield emit("auto_basic_terms", {"terms": basic_terms})
                for term in basic_terms[:5]:
                    yield emit("log", {"msg": f"  • {term}"})
                if len(basic_terms) > 5:
                    yield emit("log", {"msg": f"  ... i {len(basic_terms) - 5} więcej"})
            
            # v60: Merge long n-grams into extended_terms
            if auto_extended_long:
                extended_terms = list(extended_terms) + auto_extended_long
                yield emit("log", {"msg": f"📊 Long n-grams→EXTENDED: {len(auto_extended_long)} fraz (≥4 słowa)"})

            # ═══ v66: Auto-EXTENDED enrichment — related searches, PAA keyphrases, low-salience entities ═══
            auto_extended_extra = []
            _ext_seen = set(t.split(":")[0].strip().lower() for t in extended_terms)
            _ext_seen.update(seen_texts)

            # 1. Related searches → extended (long-tail coverage, low target)
            _related_for_ext = s1.get("related_searches") or serp_analysis.get("related_searches") or []
            for rs in _related_for_ext[:10]:
                rs_text = (rs if isinstance(rs, str) else (rs.get("query", "") or rs.get("text", ""))).strip()
                if rs_text and rs_text.lower() not in _ext_seen and rs_text.lower() != main_keyword.lower():
                    auto_extended_extra.append(f"{rs_text}: 1-2x")
                    _ext_seen.add(rs_text.lower())

            # 2. PAA questions → extract keyphrases for extended
            _paa_for_ext = s1.get("paa") or s1.get("paa_questions") or serp_analysis.get("paa_questions") or []
            for pq in _paa_for_ext[:8]:
                pq_text = (pq.get("question", pq) if isinstance(pq, dict) else str(pq)).strip()
                # Extract the core keyphrase (strip question words)
                _q_strip = pq_text.lower()
                for _qw in ("jak ", "co ", "czy ", "ile ", "jaki ", "jaka ", "jakie ", "kiedy ",
                            "gdzie ", "dlaczego ", "w jaki sposób ", "czym jest ", "co to jest ",
                            "na czym polega "):
                    if _q_strip.startswith(_qw):
                        _q_strip = _q_strip[len(_qw):]
                        break
                _q_strip = _q_strip.rstrip("?").strip()
                if _q_strip and len(_q_strip) >= 5 and _q_strip not in _ext_seen and _q_strip != main_keyword.lower():
                    auto_extended_extra.append(f"{_q_strip}: 1-2x")
                    _ext_seen.add(_q_strip)

            # 3. Low-salience entities (present in competition but marginal)
            _low_sal_entities = []
            for ent in (clean_entities or []):
                if not isinstance(ent, dict):
                    continue
                text = (ent.get("text") or ent.get("entity") or "").strip()
                if not text or text.lower() in _ext_seen:
                    continue
                sal = ent.get("salience", ent.get("entity_salience", 0))
                sources = ent.get("sources_count", 0)
                # Low salience but present in competition = worth mentioning once
                if 0 < sal < 0.3 and sources >= 1 and text.lower() != main_keyword.lower():
                    _low_sal_entities.append(f"{text}: 1x")
                    _ext_seen.add(text.lower())

            auto_extended_extra.extend(_low_sal_entities[:5])

            if auto_extended_extra:
                extended_terms = list(extended_terms) + auto_extended_extra[:15]
                _src_counts = []
                _rs_count = sum(1 for x in auto_extended_extra if any(
                    x.split(":")[0].strip().lower() == (rs if isinstance(rs, str) else rs.get("query", "")).strip().lower()
                    for rs in _related_for_ext[:10]
                ))
                _paa_count = len(auto_extended_extra) - _rs_count - len(_low_sal_entities[:5])
                if _rs_count: _src_counts.append(f"{_rs_count} related")
                if _paa_count > 0: _src_counts.append(f"{_paa_count} PAA")
                if _low_sal_entities: _src_counts.append(f"{len(_low_sal_entities[:5])} low-sal entities")
                yield emit("log", {"msg": f"📊 Auto-EXTENDED enrichment: +{len(auto_extended_extra[:15])} fraz ({', '.join(_src_counts)})"})
                yield emit("auto_extended_terms", {"terms": auto_extended_extra[:15]})

        # ─── KROK 3: H2 Planning (auto from S1 + phrase optimization) ───
        step_start(3)
        yield emit("step", {"step": 3, "name": "H2 Planning", "status": "running"})

        if not h2_structure or len(h2_structure) == 0:
            # Fully automatic: generate H2 from S1
            yield emit("log", {"msg": "Generuję strukturę H2 z analizy S1 (liczba H2 = tyle ile wymaga temat)..."})
            h2_structure = generate_h2_plan(
                main_keyword=main_keyword,
                mode=mode,
                s1_data=s1,
                basic_terms=basic_terms,
                extended_terms=extended_terms
            )
        elif len(h2_structure) > 0:
            # User provided hints, use them as hints, optimize with S1
            user_hints = list(h2_structure)  # save original
            yield emit("log", {"msg": f"Optymalizuję {len(user_hints)} wskazówek H2 na podstawie S1..."})
            h2_structure = generate_h2_plan(
                main_keyword=main_keyword,
                mode=mode,
                s1_data=s1,
                basic_terms=basic_terms,
                extended_terms=extended_terms,
                user_h2_hints=user_hints
            )

        # Emit the final H2 plan for the UI
        yield emit("h2_plan", {"h2_list": h2_structure, "count": len(h2_structure)})
        yield emit("log", {"msg": f"Plan H2 ({len(h2_structure)} sekcji): {' | '.join(h2_structure)}"})
        step_done(3)
        yield emit("step", {"step": 3, "name": "H2 Planning", "status": "done",
                            "detail": f"{len(h2_structure)} nagłówków H2"})

        # ─── KROK 4: Create Project ───
        step_start(4)
        yield emit("step", {"step": 4, "name": "Create Project", "status": "running"})

        # Build keywords array (targets scaled in v61 budget step below, after _target_length is known)
        keywords = [{"keyword": main_keyword, "type": "MAIN", "target_min": 8, "target_max": 25}]
        for term_str in basic_terms:
            parts = term_str.strip().split(":")
            kw = parts[0].strip()
            if not kw or kw == main_keyword:
                continue
            tmin, tmax = 1, 5
            if len(parts) > 1:
                range_str = parts[1].strip()
                if "-" in range_str:
                    try:
                        range_parts = range_str.replace("x", "").split("-")
                        tmin = int(range_parts[0].strip())
                        tmax = int(range_parts[1].strip())
                    except (ValueError, IndexError):
                        pass
            keywords.append({"keyword": kw, "type": "BASIC", "target_min": tmin, "target_max": tmax})

        for term_str in extended_terms:
            parts = term_str.strip().split(":")
            kw = parts[0].strip()
            if not kw or kw == main_keyword:
                continue
            tmin, tmax = 1, 2
            if len(parts) > 1:
                range_str = parts[1].strip()
                if "-" in range_str:
                    try:
                        range_parts = range_str.replace("x", "").split("-")
                        tmin = int(range_parts[0].strip())
                        tmax = int(range_parts[1].strip())
                    except (ValueError, IndexError):
                        pass
            keywords.append({"keyword": kw, "type": "EXTENDED", "target_min": tmin, "target_max": tmax})

        # ═══ v57 FIX: Add concept entities as type="ENTITY" for separate tracking ═══
        # Concept entities from S1/topical generator get tracked like keywords
        # but with type="ENTITY" so panel shows them separately.
        _existing_kw_lower = {k["keyword"].lower() for k in keywords}
        _entity_sources = must_cover_concepts or concept_entities or []
        entity_kw_count = 0
        for ent in _entity_sources[:12]:
            ent_text = (_extract_text(ent) if isinstance(ent, dict) else str(ent)).strip()
            if not ent_text or ent_text.lower() in _existing_kw_lower or ent_text.lower() == main_keyword.lower():
                continue
            is_primary = ent.get("is_primary", False) if isinstance(ent, dict) else False
            tmin = 3 if is_primary else 2
            tmax = 8 if is_primary else 5
            keywords.append({"keyword": ent_text, "type": "ENTITY", "target_min": tmin, "target_max": tmax})
            _existing_kw_lower.add(ent_text.lower())
            entity_kw_count += 1
        if entity_kw_count:
            yield emit("log", {"msg": f"🧬 Entity keywords: {entity_kw_count} encji dodanych jako type=ENTITY"})

        # ═══ v59 FIX: Add semantic keyphrases as EXTENDED keywords (PRIORITY 3) ═══
        # Priority order: 1=Entities (BASIC/ENTITY), 2=N-grams (BASIC), 3=Keyphrases (EXTENDED)
        # Keyphrases are long competitor phrases (e.g. "kara za jazdę po alkoholu").
        # GPT partially covers them by writing about the topic. Low targets = don't crowd out
        # entities and n-grams which have higher SEO value (entity salience, exact phrase match).
        _kp_added = 0
        for kp in clean_semantic_kp:
            phrase = (kp.get("phrase", kp) if isinstance(kp, dict) else str(kp)).strip()
            if not phrase or len(phrase) < 4 or phrase.lower() in _existing_kw_lower:
                continue
            if phrase.lower() == main_keyword.lower():
                continue
            keywords.append({
                "keyword": phrase,
                "type": "EXTENDED",
                "target_min": 1,
                "target_max": 2
            })
            _existing_kw_lower.add(phrase.lower())
            _kp_added += 1
        if _kp_added:
            yield emit("log", {"msg": f"🔑 Keyphrases→EXTENDED (P3): {_kp_added} fraz z competitor overlap"})

        # ═══ v60 FIX: Remove BASIC keywords subsumed by longer BASIC/ENTITY phrases ═══
        # e.g. "pozbawienia wolności" removed if "kara pozbawienia wolności" exists
        pre_remove_count = len(keywords)
        keywords = remove_subsumed_basic(keywords, main_keyword)
        _removed = pre_remove_count - len(keywords)
        if _removed:
            yield emit("log", {"msg": f"🧹 Subsumed BASIC removal: usunięto {_removed} fraz pochłoniętych przez dłuższe"})

        # ═══ Keyword deduplication (word-boundary safe) ═══
        pre_dedup_count = len(keywords)
        keywords = deduplicate_keywords(keywords, main_keyword)
        if len(keywords) < pre_dedup_count:
            yield emit("log", {"msg": f"🧹 Dedup: {pre_dedup_count} → {len(keywords)} keywords (usunięto {pre_dedup_count - len(keywords)} duplikatów)"})

        yield emit("log", {"msg": f"Keywords: {len(keywords)} ({sum(1 for k in keywords if k['type']=='BASIC')} BASIC, {sum(1 for k in keywords if k['type']=='EXTENDED')} EXTENDED, {sum(1 for k in keywords if k['type']=='ENTITY')} ENTITY)"})

        # Filter entity_seo before sending to project (remove CSS garbage)
        filtered_entity_seo = (s1.get("entity_seo") or {}).copy()
        if "top_entities" in filtered_entity_seo:
            filtered_entity_seo["top_entities"] = _filter_entities(filtered_entity_seo["top_entities"])
        if "entities" in filtered_entity_seo:
            filtered_entity_seo["entities"] = _filter_entities(filtered_entity_seo["entities"])
        if "must_mention_entities" in filtered_entity_seo:
            filtered_entity_seo["must_mention_entities"] = _filter_entities(filtered_entity_seo["must_mention_entities"])

        # v59.1 FIX: Normalize all entity lists to dicts before backend
        # Backend final_review calls .get() on entities — crashes on bare strings
        # Error: "'str' object has no attribute 'get'"
        def _normalize_ent_list(lst):
            if not lst:
                return lst
            return [
                e if isinstance(e, dict) else {"text": str(e), "type": "CONCEPT"}
                for e in lst
            ]
        
        clean_entities = _normalize_ent_list(clean_entities)
        clean_must_mention = _normalize_ent_list(clean_must_mention)
        concept_entities = _normalize_ent_list(concept_entities)
        if ai_topical:
            ai_topical = _normalize_ent_list(ai_topical)
        if ai_named:
            ai_named = _normalize_ent_list(ai_named)
        for _key in ("top_entities", "entities", "must_mention_entities",
                      "topical_entities", "named_entities", "concept_entities"):
            if _key in filtered_entity_seo and isinstance(filtered_entity_seo[_key], list):
                filtered_entity_seo[_key] = _normalize_ent_list(filtered_entity_seo[_key])

        # Wyciagnij synonimy encji głównej z entity_seo (zapisane z topical entity generator)
        _entity_synonyms = filtered_entity_seo.get("entity_synonyms", [])
        if _entity_synonyms:
            yield emit("log", {"msg": f"🔄 Synonimy głównej frazy: {', '.join(str(s) for s in _entity_synonyms[:5])}"})

        # ═══ v2.3: SEARCH VARIANT GENERATOR ═══
        search_variants = {}
        entity_variant_dict = {}
        if content_type != "category":
            yield emit("log", {"msg": "🔎 Generuję warianty wyszukiwania..."})
            # Collect secondary keywords from must_cover_concepts
            _sec_kws = []
            for c in (must_cover_concepts or [])[:6]:
                name = (_extract_text(c) if isinstance(c, dict) else str(c)).strip()
                if name and name.lower() != main_keyword.lower():
                    _sec_kws.append(name)
            search_variants = _generate_search_variants(main_keyword, secondary_keywords=_sec_kws)
            if search_variants:
                _sv_total = len(search_variants.get("all_flat", []))
                _sv_cats = [k for k in search_variants if k not in ("all_flat", "secondary") and search_variants[k]]
                # Build entity_variant_dict from secondary variants
                entity_variant_dict = search_variants.get("secondary", {})
                _sec_count = len(entity_variant_dict)
                yield emit("log", {"msg": f"🔎 Warianty: {_sv_total} main + {_sec_count} secondary w {len(_sv_cats)} kategoriach"})
                yield emit("search_variants", search_variants)
            else:
                yield emit("log", {"msg": "⚠️ Warianty wyszukiwania: brak danych"})

        # v2.3: Backfill entity_synonyms from search_variants
        if search_variants:
            _sv_synonyms = (search_variants.get("peryfrazy", []) + search_variants.get("fleksyjne", []))[:8]
            if _sv_synonyms:
                filtered_entity_seo["entity_synonyms"] = _sv_synonyms

        # Fix #59: Oblicz target_length z recommended_length S1 zamiast hardcode 3500/2000
        if content_type == "category":
            # Category descriptions: 200-500 (parent) or 500-1200 (subcategory)
            _cat_type = (category_data or {}).get("category_type", "subcategory")
            if _cat_type == "parent":
                _target_length = 400
            else:
                _target_length = 1000
        else:
            _s1_recommended = s1.get("recommended_length") or (s1.get("length_analysis") or {}).get("recommended")
            if _s1_recommended and int(_s1_recommended) > 200:
                _target_length = int(_s1_recommended * 1.05)  # 5% margines na intro/outro
            else:
                _target_length = 3500 if mode == "standard" else 2000

            # Scale target_length if H2 plan needs more space
            _WORDS_PER_H2 = 250
            _min_length_for_all_h2 = len(h2_structure) * _WORDS_PER_H2 + 150
            if _target_length < _min_length_for_all_h2:
                _old_target = _target_length
                _target_length = min(_min_length_for_all_h2, int(_target_length * 1.5))  # cap at 1.5x
                yield emit("log", {"msg": f"📏 target_length {_old_target}→{_target_length} (for {len(h2_structure)} H2)"})

            # Ensure target_length covers remaining H2 sections
            _min_length_for_h2 = len(h2_structure) * 200 + 150
            if _target_length < _min_length_for_h2:
                yield emit("log", {"msg": f"📏 target_length {_target_length} < min dla {len(h2_structure)} H2 ({_min_length_for_h2}) — podwyższam"})
                _target_length = _min_length_for_h2

        # Calculate total_batches: 1 INTRO + 1 per H2
        _planned_total_batches = len(h2_structure) + 1

        # ═══ v61: KEYWORD BUDGET SCALER — prevent keyword soup ═══
        # Problem: n-gram targets from competition (e.g. "pod wpływem alkoholu: 7-17x")
        # are raw frequencies from articles that may be 3000+ words,
        # applied to our ~1600 word article. Result: keyword every 16-33 words = unnatural.
        #
        # Fix: Scale targets to article length, cap total budget, overflow → EXTENDED.
        _BUDGET_PER_100_WORDS = 2.0  # max 2 keyword mentions per 100 words (natural density)
        _MAX_SINGLE_BASIC = max(4, _target_length // 400)    # BASIC: ~1 per 400 words
        _MAX_SINGLE_MAIN = max(5, min(12, _target_length // 200))  # MAIN: ~1 per 200 words
        _total_budget = int(_target_length * _BUDGET_PER_100_WORDS / 100)

        # 1. Scale MAIN keyword
        for kw in keywords:
            if kw["type"] == "MAIN":
                kw["target_max"] = _MAX_SINGLE_MAIN
                kw["target_min"] = max(3, kw["target_max"] // 2)
                break

        # 2. Cap individual keyword targets
        for kw in keywords:
            if kw["type"] in ("BASIC", "ENTITY"):
                cap = _MAX_SINGLE_BASIC
                if kw["target_max"] > cap:
                    kw["target_max"] = cap
                if kw["target_min"] > kw["target_max"]:
                    kw["target_min"] = max(1, kw["target_max"] - 1)

        # 3. Check total budget — if over, push lowest-priority BASIC → EXTENDED
        _total_max = sum(kw["target_max"] for kw in keywords)
        if _total_max > _total_budget * 1.5:  # use target_max, not min — model aims for max
            # Sort BASIC by target_max desc — highest targets get demoted first
            _basic_by_target = sorted(
                [kw for kw in keywords if kw["type"] == "BASIC"],
                key=lambda k: k["target_max"], reverse=True
            )
            _overflow_count = 0
            for kw in _basic_by_target:
                if _total_max <= _total_budget * 1.5:
                    break
                _old_max = kw["target_max"]
                kw["type"] = "EXTENDED"
                kw["target_max"] = min(2, kw["target_max"])
                kw["target_min"] = 1
                _total_max -= (_old_max - kw["target_max"])
                _overflow_count += 1
            if _overflow_count:
                yield emit("log", {"msg": f"📊 Budget overflow: {_overflow_count} BASIC→EXTENDED (budget: {_total_budget} mentions for {_target_length} words)"})

        _final_basic = sum(1 for k in keywords if k['type'] == 'BASIC')
        _final_ext = sum(1 for k in keywords if k['type'] == 'EXTENDED')
        _final_total_min = sum(kw['target_min'] for kw in keywords)
        _final_total_max = sum(kw['target_max'] for kw in keywords)
        yield emit("log", {"msg": f"📊 Budget: {_final_total_min}-{_final_total_max} mentions in {_target_length} words ({_final_basic} BASIC, {_final_ext} EXTENDED, density: {_final_total_min*100/_target_length:.1f}-{_final_total_max*100/_target_length:.1f}/100w)"})

        # ═══ v68: CASCADE DEDUCTION (Inclusion-Exclusion) ═══
        # When "olej z czarnuszki dla dzieci" (MAIN) has target [4,7],
        # every use also counts as "olej z czarnuszki" and "czarnuszka".
        # So standalone targets for sub-phrases must be reduced.
        _pre_cascade_max = sum(kw['target_max'] for kw in keywords)
        keywords = cascade_deduct_targets(keywords, main_keyword)
        _post_cascade_max = sum(kw['target_max'] for kw in keywords)
        _cascade_count = sum(1 for kw in keywords if kw.get("_cascade_deducted"))
        if _cascade_count:
            yield emit("log", {"msg": f"🔗 Cascade deduction: {_cascade_count} fraz zredukowanych, target_max: {_pre_cascade_max}→{_post_cascade_max} (Δ-{_pre_cascade_max - _post_cascade_max})"})

        # ═══ v67 FIX: Second dedup pass after budget overflow ═══
        # Budget overflow demotes BASIC→EXTENDED. The first dedup pass only checked BASIC.
        # Now re-run dedup to catch the demoted keywords.
        _pre_dedup2 = sum(kw['target_max'] for kw in keywords)
        keywords = deduplicate_keywords(keywords, main_keyword)
        _post_dedup2 = sum(kw['target_max'] for kw in keywords)
        if _post_dedup2 < _pre_dedup2:
            yield emit("log", {"msg": f"🧹 Post-overflow dedup: target_max reduced {_pre_dedup2}→{_post_dedup2} (Δ-{_pre_dedup2 - _post_dedup2})"})

        project_payload = {
            "main_keyword": main_keyword,
            "mode": mode,
            "h2_structure": h2_structure,
            "keywords": keywords,
            "total_planned_batches": _planned_total_batches,
            "s1_data": {
                "causal_triplets": (s1.get("causal_triplets") or {}),
                "content_gaps": (s1.get("content_gaps") or {}),
                "entity_seo": filtered_entity_seo,
                "paa": (s1.get("paa") or []),
                "ngrams": _filter_ngrams((s1.get("ngrams") or [])[:30]),
                "competitor_h2_patterns": _filter_h2_patterns((s1.get("competitor_h2_patterns") or [])[:30]),
                # v55.1: SERP data needed by pre-batch (featured_snippet, ai_overview, related_searches)
                "featured_snippet": s1.get("featured_snippet") or serp_analysis.get("featured_snippet"),
                "ai_overview": s1.get("ai_overview") or serp_analysis.get("ai_overview"),
                "related_searches": (s1.get("related_searches") or serp_analysis.get("related_searches") or [])[:10],
                "semantic_keyphrases": (s1.get("semantic_keyphrases") or [])[:15],
                "search_intent": s1.get("search_intent") or serp_analysis.get("search_intent", "informational"),
            },
            "target_length": _target_length,
            "is_legal": is_legal,
            "is_medical": is_medical,
            "is_finance": is_finance,
            "is_ymyl": is_legal or is_medical or is_finance,
            # v50: YMYL intensity for conditional pipeline behavior
            "ymyl_intensity": ymyl_intensity,
            "light_ymyl_note": light_ymyl_note,
            "legal_context": legal_context,
            "legal_wiki_articles": ymyl_enrichment.get("_wiki_articles", []),
            "medical_context": medical_context,
            # v47.2: Claude's YMYL enrichment (articles, MeSH, evidence notes)
            "ymyl_enrichment": ymyl_enrichment,
        }

        create_result = brajen_call("post", "/api/project/create", project_payload)
        if not create_result["ok"]:
            yield emit("workflow_error", {"step": 4, "msg": f"Create Project failed: {create_result.get('error', 'unknown')}"})
            return

        project = create_result["data"]
        project_id = project.get("project_id")
        total_batches = project.get("total_planned_batches", len(h2_structure))
        # +1 for INTRO batch which doesn't write any H2 content
        if total_batches <= len(h2_structure):
            total_batches = len(h2_structure) + 1

        step_done(4)
        yield emit("step", {"step": 4, "name": "Create Project", "status": "done",
                            "detail": f"ID: {project_id} | Mode: {mode} | Batche: {total_batches} (w tym INTRO)"})
        yield emit("project", {"project_id": project_id, "total_batches": total_batches})

        # Store project_id in job
        job["project_id"] = project_id

        # ─── KROK 5: Phrase Hierarchy ───
        step_start(5)
        yield emit("step", {"step": 5, "name": "Phrase Hierarchy", "status": "running"})
        hier_result = brajen_call("get", f"/api/project/{project_id}/phrase_hierarchy")
        phrase_hierarchy_data = {}
        if hier_result["ok"]:
            hier = hier_result["data"]
            phrase_hierarchy_data = hier  # Store for injection into pre_batch
            strategy = (hier.get("strategies") or {})
            # Emit phrase hierarchy preview to frontend
            hier_preview = hier.get("strategies") or hier.get("phrase_hierarchy") or hier
            if isinstance(hier_preview, dict):
                yield emit("log", {"msg": f"🔤 Phrase Hierarchy: {len(hier_preview)} strategii ({', '.join(list(hier_preview.keys())[:3])})"})
                yield emit("phrase_hierarchy", {"phrase_hierarchy_preview": hier_preview})
            step_done(5)
            yield emit("step", {"step": 5, "name": "Phrase Hierarchy", "status": "done",
                                "detail": json.dumps(strategy, ensure_ascii=False)[:200]})
        else:
            yield emit("step", {"step": 5, "name": "Phrase Hierarchy", "status": "warning",
                                "detail": "Nie udało się pobrać, kontynuuję"})

        # ─── KROK 6: Batch Loop ───
        step_start(6)
        yield emit("step", {"step": 6, "name": "Batch Loop", "status": "running",
                            "detail": f"0/{total_batches} batchy"})

        # ═══ AI MIDDLEWARE: Track accepted batches for memory ═══
        accepted_batches_log = []
        _structured_memory = {}  # v66: structured memory tracker (replaces Haiku calls)
        _style_anchor = ""  # v2.5: voice continuity — representative sentences from INTRO

        # ═══ v2: Entity tracker — tracks which entities introduced in which batch ═══
        _entity_tracker = {
            "entities": {},      # {name: {"introduced_in": batch_num, "count": N}}
            "terminology": {},   # {old_form: replacement}
        }

        # ═══ ENTITY CONTENT PLAN — assign lead entity per batch/H2 ═══
        # Each H2 section gets ONE lead entity as "paragraph subject opener".
        # Prevents every akapit from starting with the same main keyword.
        #
        # Algorithm:
        # - Batch 1 (INTRO): always main keyword
        # - Batch N (H2): pick secondary entity whose text overlaps most with H2 title
        # - Fallback: cycle through secondary entities in order (1, 2, 3…)
        # ═══ v2.3: SMART S1 DISTRIBUTOR — match S1 data to current H2 ═══
        def _h2_relevance(text, h2_words):
            """Score how relevant a text is to H2 by word overlap."""
            if not text or not h2_words:
                return 0
            text_words = set(text.lower().split())
            # Remove very common Polish words
            _stop = {"w", "z", "i", "na", "do", "dla", "po", "od", "o", "się", "to", "jest",
                     "jak", "co", "czy", "nie", "za", "a", "lub", "oraz", "przez", "przy"}
            text_words -= _stop
            overlap = len(h2_words & text_words)
            # Partial: substring match + Polish stem match (first 4 chars)
            partial = 0
            for tw in text_words:
                for hw in h2_words:
                    if len(tw) > 3 and len(hw) > 3:
                        if tw in hw or hw in tw:
                            partial += 1
                        elif tw[:4] == hw[:4]:  # Polish stem match: kara/kary/karze
                            partial += 1
            return overlap * 3 + partial

        def _build_batch_s1_context(current_h2, batch_num, batch_type,
                                     eav_triples, svo_triples, causal_chains, causal_singles,
                                     content_gaps, must_cover, entity_gaps, cooc_pairs,
                                     entity_plan, main_kw):
            """Build per-batch S1 context — only data relevant to current H2.
            
            Returns dict with keys: eav, svo, causal, gaps, concepts, cooc, lead_entity.
            Each value is a filtered/scored subset of the full S1 data.
            """
            _stop = {"w", "z", "i", "na", "do", "dla", "po", "od", "o", "się", "to", "jest",
                     "jak", "co", "czy", "nie", "za", "a", "lub", "oraz", "przez", "przy"}
            h2_words = set(current_h2.lower().split()) - _stop
            # Also include main keyword words for INTRO
            if batch_type in ("INTRO", "intro"):
                h2_words |= set(main_kw.lower().split()) - _stop

            ctx = {}

            # ── EAV: score each triple, take top 4 + always include primary ──
            if eav_triples:
                scored = []
                primary = None
                for eav in eav_triples:
                    text = f"{eav.get('entity','')} {eav.get('attribute','')} {eav.get('value','')}"
                    score = _h2_relevance(text, h2_words)
                    if eav.get("is_primary"):
                        primary = eav
                    else:
                        scored.append((score, eav))
                scored.sort(key=lambda x: -x[0])
                result = []
                if primary:
                    result.append(primary)
                result.extend([eav for _, eav in scored[:4] if _ > 0])
                # If nothing matched, take top 2 anyway (always useful)
                if not result and scored:
                    result = [eav for _, eav in scored[:2]]
                ctx["eav"] = result

            # ── SVO: score and take top 3 matching ──
            if svo_triples:
                scored = []
                for svo in svo_triples:
                    text = f"{svo.get('subject','')} {svo.get('verb','')} {svo.get('object','')} {svo.get('context','')}"
                    score = _h2_relevance(text, h2_words)
                    scored.append((score, svo))
                scored.sort(key=lambda x: -x[0])
                ctx["svo"] = [svo for s, svo in scored[:3] if s > 0]

            # ── Causal chains: score and take top 2 matching ──
            all_causal = (causal_chains or []) + (causal_singles or [])
            if all_causal:
                scored = []
                for chain in all_causal:
                    if isinstance(chain, dict):
                        text = chain.get("chain", chain.get("text", str(chain)))
                    else:
                        text = str(chain)
                    score = _h2_relevance(text, h2_words)
                    scored.append((score, chain))
                scored.sort(key=lambda x: -x[0])
                ctx["causal"] = [c for s, c in scored[:2] if s > 0]

            # ── Content gaps: filter subtopic/depth by H2 relevance ──
            if content_gaps and isinstance(content_gaps, dict):
                subtopic = content_gaps.get("subtopic_missing", [])
                depth = content_gaps.get("depth_missing", [])
                matched_gaps = []
                for item in (subtopic + depth)[:15]:
                    text = item.get("topic", item.get("text", str(item))) if isinstance(item, dict) else str(item)
                    if _h2_relevance(text, h2_words) > 0:
                        matched_gaps.append(text)
                ctx["gaps"] = matched_gaps[:3]

            # ── Must-cover concepts: filter by H2 relevance ──
            if must_cover:
                scored = []
                for c in must_cover:
                    name = c.get("text", c) if isinstance(c, dict) else str(c)
                    score = _h2_relevance(name, h2_words)
                    scored.append((score, name))
                scored.sort(key=lambda x: -x[0])
                # Take top-matching + any with score 0 only if batch has room
                matched = [n for s, n in scored if s > 0][:5]
                if len(matched) < 2 and scored:
                    # Include some even if no direct match (spread coverage)
                    unmatched = [n for s, n in scored if s == 0]
                    # Round-robin: each batch gets different unmatched concepts
                    start = ((batch_num - 1) * 2) % max(1, len(unmatched))
                    matched.extend(unmatched[start:start+2])
                ctx["concepts"] = matched[:5]

            # ── Entity gaps: filter by H2 relevance ──
            if entity_gaps:
                matched = []
                for g in entity_gaps:
                    name = g.get("entity", "") if isinstance(g, dict) else str(g)
                    if _h2_relevance(name, h2_words) > 0:
                        matched.append(name)
                ctx["entity_gaps"] = matched[:3]

            # ── Co-occurrence pairs: filter by H2 ──
            if cooc_pairs:
                matched = []
                for pair in cooc_pairs:
                    if isinstance(pair, dict):
                        e1 = pair.get("entity1", pair.get("source", ""))
                        e2 = pair.get("entity2", pair.get("target", ""))
                        text = f"{e1} {e2}"
                        if _h2_relevance(text, h2_words) > 0:
                            matched.append(f"{e1} + {e2}")
                ctx["cooc"] = matched[:4]

            # ── Lead entity from content plan ──
            if entity_plan and batch_num <= len(entity_plan):
                ctx["lead_entity"] = entity_plan[batch_num - 1]

            return ctx

        def _build_entity_content_plan(h2_list, main_kw, secondary_entities):
            """v66: LLM-based semantic entity→H2 assignment.
            Returns list[str]: lead entity name per batch (index 0 = batch 1).
            Uses Haiku for semantic matching instead of word overlap."""
            if not secondary_entities or not h2_list:
                return [main_kw] * len(h2_list)

            ent_names = []
            for e in secondary_entities:
                name = (_extract_text(e) if isinstance(e, dict) else str(e))
                if name and name != main_kw:
                    ent_names.append(name)

            if not ent_names:
                return [main_kw] * len(h2_list)

            # Build H2 list (skip first = INTRO)
            h2_for_matching = []
            for i, h2 in enumerate(h2_list):
                if i == 0:
                    continue  # INTRO always gets main_kw
                h2_for_matching.append({"idx": i, "title": h2})

            if not h2_for_matching:
                return [main_kw] * len(h2_list)

            # LLM call for semantic matching
            try:
                _ent_list = "\n".join(f"  {i+1}. {n}" for i, n in enumerate(ent_names[:15]))
                _h2_list = "\n".join(f"  {h['idx']}. {h['title']}" for h in h2_for_matching)
                _match_prompt = (
                    f'Artykuł o: "{main_kw}"\n\n'
                    f'ENCJE TEMATYCZNE (secondary entities):\n{_ent_list}\n\n'
                    f'NAGŁÓWKI H2 (sekcje artykułu):\n{_h2_list}\n\n'
                    f'Przypisz JEDNĄ najlepiej pasującą encję do każdego H2.\n'
                    f'Encja powinna dominować semantycznie w danej sekcji.\n'
                    f'Każda encja może być użyta max 1 raz. Jeśli żadna nie pasuje, użyj "{main_kw}".\n\n'
                    f'Zwróć TYLKO JSON object: {{"idx": "entity_name", ...}}\n'
                    f'Przykład: {{"1": "odpowiedzialność karna", "2": "badanie alkomatem"}}'
                )
                _match_response = _generate_claude(
                    system_prompt="Przypisujesz encje tematyczne do sekcji artykułu. Zwracasz TYLKO JSON.",
                    user_prompt=_match_prompt,
                    temperature=0,
                )
                _match_clean = _match_response.replace("```json", "").replace("```", "").strip()
                _match_map = json.loads(_match_clean)

                plan = []
                for i, h2 in enumerate(h2_list):
                    if i == 0:
                        plan.append(main_kw)
                    else:
                        assigned = _match_map.get(str(i), main_kw)
                        # Validate assigned entity exists in our list
                        if assigned not in ent_names and assigned != main_kw:
                            # Fuzzy fallback: find closest match
                            _best = main_kw
                            for en in ent_names:
                                if en.lower() in assigned.lower() or assigned.lower() in en.lower():
                                    _best = en
                                    break
                            assigned = _best
                        plan.append(assigned)
                return plan

            except Exception as ecp_err:
                logger.warning(f"[ENTITY_PLAN] LLM matching failed: {ecp_err}, falling back to word overlap")
                # ═══ FALLBACK: original word-overlap method ═══
                plan = []
                used_indices = set()
                for i, h2 in enumerate(h2_list):
                    if i == 0:
                        plan.append(main_kw)
                    else:
                        h2_words = set(h2.lower().split())
                        best_idx, best_score = None, 0
                        for j, ent in enumerate(secondary_entities):
                            if j in used_indices:
                                continue
                            name = (_extract_text(ent) if isinstance(ent, dict) else str(ent)).lower()
                            ent_words = set(name.split())
                            overlap = len(h2_words & ent_words)
                            partial = sum(1 for w in ent_words if any(w in hw or hw in w for hw in h2_words))
                            score = overlap * 2 + partial
                            if score > best_score:
                                best_idx, best_score = j, score
                        if best_idx is not None and best_score > 0:
                            ent = secondary_entities[best_idx]
                            plan.append(_extract_text(ent) if isinstance(ent, dict) else str(ent))
                            used_indices.add(best_idx)
                        else:
                            cycle_idx = (i - 1) % max(1, len(secondary_entities))
                            ent = secondary_entities[cycle_idx]
                            plan.append(_extract_text(ent) if isinstance(ent, dict) else str(ent))
                return plan

        _secondary_for_plan = [e for e in (must_cover_concepts or []) if
                               (_extract_text(e) if isinstance(e, dict) else str(e)) != main_keyword]
        _entity_content_plan = _build_entity_content_plan(
            h2_structure, main_keyword, _secondary_for_plan
        )
        if _entity_content_plan:
            plan_preview = " | ".join(
                f"B{i+1}:{n}" for i, n in enumerate(_entity_content_plan)
            )
            yield emit("log", {"msg": f"🗂️ Entity content plan: {plan_preview}"})

        # Fix #56: Globalny licznik głównego keywordu przez wszystkie batche
        _GLOBAL_KW_MAX = 6  # max 6 wystąpień main keyword w całym artykule
        _global_main_kw_count = 0

        # ═══ v66: COLLECT ASYNC YMYL ENRICHMENT — wait for background thread ═══
        if _ymyl_thread is not None:
            yield emit("log", {"msg": "⏳ Czekam na YMYL enrichment z tła..."})
            _ymyl_thread.join(timeout=35)  # Max wait = SAOS timeout + margin
            if _ymyl_enrichment_result.get("done"):
                legal_context = _ymyl_enrichment_result["legal_context"]
                medical_context = _ymyl_enrichment_result["medical_context"]
                ymyl_enrichment = _ymyl_enrichment_result["ymyl_enrichment"]
                judgments_clean = _ymyl_enrichment_result["judgments_clean"]

                _src_parts = []
                if legal_context:
                    _src_parts.append(f"orzeczenia: {len(judgments_clean)}")
                _wa = _ymyl_enrichment_result.get("_wiki_articles", [])
                if _wa:
                    _src_parts.append(f"Wikipedia: {len(_wa)}")
                    yield emit("legal_wiki_sources", {"articles": _wa})
                if medical_context:
                    _pubs = (medical_context.get("top_publications") or [])
                    _src_parts.append(f"publikacje: {len(_pubs)}")
                if _src_parts:
                    yield emit("log", {"msg": f"✅ YMYL enrichment gotowy: {', '.join(_src_parts)}"})
                else:
                    yield emit("log", {"msg": "⚠️ YMYL enrichment: brak danych (SAOS/PubMed niedostępne)"})

                # Emit YMYL context panel
                ymyl_panel_data = {
                    "is_legal": is_legal, "is_medical": is_medical, "is_finance": is_finance,
                    "ymyl_intensity": ymyl_intensity,
                    "classification": {
                        "category": ymyl_data.get("category", "general"),
                        "confidence": ymyl_confidence, "reasoning": ymyl_reasoning,
                        "method": ymyl_data.get("detection_method", "unknown"),
                        "ymyl_intensity": ymyl_intensity,
                    },
                    "enrichment": ymyl_enrichment, "legal": {}, "medical": {},
                }
                if legal_context:
                    legal_enrich = ymyl_enrichment.get("legal", {})
                    legal_acts = legal_enrich.get("acts", [])
                    if legal_acts and isinstance(legal_acts, list):
                        legal_acts = [{"name": a} if isinstance(a, str) else a for a in legal_acts[:8]]
                    else:
                        legal_acts = legal_context.get("legal_acts") or legal_context.get("acts") or []
                    legal_articles = legal_enrich.get("articles", [])
                    ymyl_panel_data["legal"] = {
                        "instruction_preview": (legal_context.get("legal_instruction", ""))[:300],
                        "judgments": judgments_clean,
                        "judgments_count": len(legal_context.get("top_judgments") or []),
                        "legal_acts": legal_acts[:8],
                        "legal_articles": legal_articles[:6],
                        "citation_hint": legal_context.get("citation_hint", ""),
                        "wiki_articles": _wa,
                    }
                if medical_context:
                    pubs_raw = medical_context.get("top_publications") or []
                    pubs_clean = [{
                        "title": (p.get("title", ""))[:120],
                        "authors": (p.get("authors", ""))[:80],
                        "year": p.get("year", ""), "pmid": p.get("pmid", ""),
                        "journal": (p.get("journal", ""))[:60],
                        "evidence_level": p.get("evidence_level", p.get("level", "")),
                        "study_type": p.get("study_type", p.get("type", "")),
                    } for p in pubs_raw[:10] if isinstance(p, dict)]
                    evidence_levels = {}
                    for p in pubs_clean:
                        lvl = p.get("evidence_level") or p.get("study_type") or "unknown"
                        evidence_levels[lvl] = evidence_levels.get(lvl, 0) + 1
                    ymyl_panel_data["medical"] = {
                        "instruction_preview": (medical_context.get("medical_instruction", ""))[:300],
                        "publications": pubs_clean, "publications_count": len(pubs_raw),
                        "evidence_levels": evidence_levels,
                        "guidelines": medical_context.get("guidelines") or [],
                    }
                yield emit("ymyl_context", ymyl_panel_data)
            else:
                yield emit("log", {"msg": "⚠️ YMYL enrichment timeout — kontynuuję bez danych"})

        # Bug A Fix: Lokalny tracker zuzycia H2
        # Gdy backend (brajen_api) utknął na tym samym h2_remaining[0] (tryb FINAL),
        # app.py sam awansuje wskaznik i wybiera kolejny H2 z lokalnego planu.
        _h2_local_done = []   # lista H2 juz wygenerowanych (string, lowercase)
        _h2_local_idx = 0     # nastepny wolny index w h2_structure

        for batch_num in range(1, total_batches + 1):
            yield emit("batch_start", {"batch": batch_num, "total": total_batches})
            yield emit("log", {"msg": f"── BATCH {batch_num}/{total_batches} ──"})

            # 6a: Get pre_batch_info
            yield emit("log", {"msg": f"GET /pre_batch_info"})
            pre_result = brajen_call("get", f"/api/project/{project_id}/pre_batch_info")
            if not pre_result["ok"]:
                yield emit("log", {"msg": f"⚠️ pre_batch_info error: {pre_result.get('error', '')[:100]}"})
                continue

            pre_batch = pre_result["data"]
            # v55.1: Guard against pre_batch being a string instead of dict
            if not isinstance(pre_batch, dict):
                logger.warning(f"[BATCH] pre_batch is {type(pre_batch).__name__}, forcing empty dict")
                pre_batch = {}
            batch_type = pre_batch.get("batch_type", "CONTENT")
            # UI voice preset (AUTO jeśli brak)
            pre_batch["voice_preset"] = voice_preset or "auto"
            batch_type = pre_batch.get("batch_type", "CONTENT")
            
            # ═══ BATCH 1 = INTRO: First batch must always be introduction ═══
            if batch_num == 1 and batch_type not in ("INTRO", "intro"):
                batch_type = "INTRO"
                yield emit("log", {"msg": "📝 Batch 1 → wymuszony typ INTRO (wstęp artykułu)"})

            # ═══ INTRO SERP INJECTION: pass snippet/AI overview to prompt builder ═══
            if batch_num == 1 and batch_type in ("INTRO", "intro"):
                _serp_for_intro = pre_batch.get("serp_enrichment") or {}
                _fs = s1.get("featured_snippet") or serp_analysis.get("featured_snippet") or ""
                _aov = s1.get("ai_overview") or serp_analysis.get("ai_overview") or ""
                _sint = s1.get("search_intent") or serp_analysis.get("search_intent") or ""
                _comp_titles = serp_analysis.get("competitor_titles", [])[:5]
                _comp_snippets = serp_analysis.get("competitor_snippets", [])[:5]
                _paa = (s1.get("paa") or s1.get("paa_questions") or serp_analysis.get("paa_questions") or [])[:5]
                # ALWAYS inject — not just when snippet/AIO exist
                _serp_for_intro["featured_snippet"] = _fs
                _serp_for_intro["ai_overview"] = _aov
                _serp_for_intro["search_intent"] = _sint
                _serp_for_intro["competitor_titles"] = _comp_titles
                _serp_for_intro["competitor_snippets"] = _comp_snippets
                _serp_for_intro["competitor_intros"] = _competitor_intros  # v2.3: first paragraphs from competitor pages
                _serp_for_intro["paa_questions"] = _paa
                pre_batch["serp_enrichment"] = _serp_for_intro
                yield emit("log", {"msg": f"📰 INTRO SERP: snippet={'✅' if _fs else '❌'}, AI overview={'✅' if _aov else '❌'}, titles={len(_comp_titles)}, PAA={len(_paa)}, intros={len(_competitor_intros)}, intent={_sint[:40] if _sint else '?'}"})

            # ═══ v60: Inject refinement chips for all batches ═══
            _chips = s1.get("refinement_chips") or serp_analysis.get("refinement_chips") or []
            if _chips:
                _se = pre_batch.get("serp_enrichment") or {}
                _se["refinement_chips"] = _chips
                pre_batch["serp_enrichment"] = _se
            # ═══ Inject phrase hierarchy data for prompt_builder ═══
            if phrase_hierarchy_data:
                pre_batch["_phrase_hierarchy"] = phrase_hierarchy_data

            # ═══ Inject entity salience instructions for prompt_builder ═══
            if entity_salience_instructions:
                pre_batch["_entity_salience_instructions"] = entity_salience_instructions

            # ═══ Inject YMYL flags for depth signals ═══
            pre_batch["_is_ymyl"] = is_legal or is_medical or is_finance
            # Fix #56: Przekaż budżet keywordu do prompt_buildera
            pre_batch["_kw_global_used"] = _global_main_kw_count
            pre_batch["_kw_global_remaining"] = max(0, _GLOBAL_KW_MAX - _global_main_kw_count)
            # v56: Hard keyword overflow ceiling — force-ban when >150% target
            _KW_OVERFLOW_FACTOR = 1.5
            _kw_hard_ceiling = int(_GLOBAL_KW_MAX * _KW_OVERFLOW_FACTOR)
            pre_batch["_kw_force_ban"] = _global_main_kw_count >= _kw_hard_ceiling
            # v50: Pass intensity to prompt_builder for conditional legal/medical injection
            pre_batch["_ymyl_intensity"] = ymyl_intensity
            if light_ymyl_note:
                pre_batch["_light_ymyl_note"] = light_ymyl_note
            
            # ═══ v47.2: Inject YMYL enrichment for prompt builder ═══
            if ymyl_enrichment:
                pre_batch["_ymyl_enrichment"] = ymyl_enrichment
                # v50: Removed redundant aliases (_ymyl_key_concepts, _ymyl_evidence_note,
                # _ymyl_specialization) , data consumed through _ymyl_enrichment parent dict
                # in _fmt_legal_medical() as ymyl_enrich.get("legal"/"medical").

            # ═══ Inject last depth score for adaptive depth signals ═══
            if accepted_batches_log:
                last_accepted = accepted_batches_log[-1]
                last_depth = last_accepted.get("depth_score")
                if last_depth is not None:
                    pre_batch["_last_depth_score"] = last_depth

            # ═══ v47.0: Inject backend placement instructions for prompt_builder ═══
            if backend_placement_instruction:
                pre_batch["_backend_placement_instruction"] = backend_placement_instruction
            if backend_cooccurrence_pairs:
                pre_batch["_cooccurrence_pairs"] = backend_cooccurrence_pairs
            if backend_first_para_entities:
                pre_batch["_first_paragraph_entities"] = backend_first_para_entities
            if backend_h2_entities:
                pre_batch["_h2_entities"] = backend_h2_entities
            # v47.0: Concept coverage for prompt
            if concept_instruction:
                pre_batch["_concept_instruction"] = concept_instruction
            if must_cover_concepts:
                pre_batch["_must_cover_concepts"] = must_cover_concepts

            # ═══ Inject EAV + SVO semantic triples ═══
            if topical_gen_eav:
                pre_batch["_eav_triples"] = topical_gen_eav
            if topical_gen_svo:
                pre_batch["_svo_triples"] = topical_gen_svo

            # ═══ v57: Inject entity gaps as informational hints ═══
            if entity_gaps:
                pre_batch["_entity_gaps"] = entity_gaps

            # ═══ v2.3: Inject entity variant dictionary ═══
            if entity_variant_dict:
                pre_batch["_entity_variants"] = entity_variant_dict

            # ═══ ENTITY CONTENT PLAN — inject lead entity for this batch/H2 ═══
            if _entity_content_plan and batch_num <= len(_entity_content_plan):
                pre_batch["_section_lead_entity"] = _entity_content_plan[batch_num - 1]
            elif main_keyword:
                pre_batch["_section_lead_entity"] = main_keyword

            # Get current H2 from API (most reliable) or fallback to our plan
            h2_remaining = (pre_batch.get("h2_remaining") or [])
            semantic_plan = pre_batch.get("semantic_batch_plan") or {}
            if h2_remaining:
                api_h2 = h2_remaining[0]
                # Bug A Fix: Sprawdz czy backend nie utknał na tym samym H2
                # (objaw: api_h2 jest już w _h2_local_done I dostepne są inne H2 z planu)
                api_h2_key = api_h2.strip().lower()
                if api_h2_key in _h2_local_done and _h2_local_idx < len(h2_structure):
                    # Backend wraca ten sam H2 — wybierz nastepny z lokalnego planu
                    current_h2 = h2_structure[_h2_local_idx]
                    yield emit("log", {"msg": f"⚠️ Bug A: h2_remaining powtarza '{api_h2[:40]}' — lokalny awans → '{current_h2[:40]}'"})
                else:
                    current_h2 = api_h2
            elif semantic_plan.get("h2"):
                current_h2 = semantic_plan["h2"]
            else:
                current_h2 = h2_structure[min(batch_num-1, len(h2_structure)-1)]

            # ═══ KEYWORD DISTRIBUTION: use API remaining counts to prioritize ═══
            # Brajn API tracks per-keyword usage (actual/target_max/remaining).
            # Problem: API sends ALL basic keywords as MUST to every batch.
            # Fix: keep only high-remaining keywords as MUST, demote rest to EXTENDED.
            _kw_dict = pre_batch.get("keywords") or {}
            _all_must = _kw_dict.get("basic_must_use", [])
            _MAX_MUST_PER_BATCH = 3  # main + 2 others max

            if _all_must and len(_all_must) > _MAX_MUST_PER_BATCH:
                _raw_main_kw = pre_batch.get("main_keyword") or {}
                _main_name = (_raw_main_kw.get("keyword", "") if isinstance(_raw_main_kw, dict)
                              else str(_raw_main_kw)).lower().strip()

                _main_kws = []
                _scoreable = []
                for kw in _all_must:
                    kw_name = (kw.get("keyword", "") if isinstance(kw, dict) else str(kw)).lower().strip()
                    if kw_name == _main_name:
                        _main_kws.append(kw)
                        continue
                    if isinstance(kw, dict):
                        actual = kw.get("actual", kw.get("actual_uses", kw.get("current_count", 0))) or 0
                        target_max = kw.get("target_max", 0) or 0
                        remaining = kw.get("remaining", kw.get("remaining_max", 0))
                        if not remaining and target_max:
                            remaining = max(0, int(target_max) - int(actual))
                        _scoreable.append((int(remaining) if remaining else 99, kw))
                    else:
                        _scoreable.append((99, kw))  # no data = assume needed

                # Sort by remaining desc: keywords most needing coverage first
                _scoreable.sort(key=lambda x: -x[0])
                _slots = _MAX_MUST_PER_BATCH - len(_main_kws)
                _keep_must = [kw for _, kw in _scoreable[:_slots]]
                _demote = [kw for _, kw in _scoreable[_slots:]]

                if _demote:
                    _kw_dict["basic_must_use"] = _main_kws + _keep_must
                    _existing_ext = _kw_dict.get("extended_this_batch", [])
                    _kw_dict["extended_this_batch"] = _existing_ext + _demote
                    pre_batch["keywords"] = _kw_dict
                    yield emit("log", {"msg": f"🔄 KW dist: {len(_all_must)} → MUST {len(_main_kws) + len(_keep_must)}, EXT +{len(_demote)}"})

            must_kw = (pre_batch.get("keywords") or {}).get("basic_must_use", [])
            ext_kw = (pre_batch.get("keywords") or {}).get("extended_this_batch", [])
            stop_kw = (pre_batch.get("keyword_limits") or {}).get("stop_keywords", [])

            yield emit("log", {"msg": f"Typ: {batch_type} | H2: {current_h2}"})
            yield emit("log", {"msg": f"MUST: {len(must_kw)} | EXTENDED: {len(ext_kw)} | STOP: {len(stop_kw)}"})

            # ═══ v2.3: SMART S1 CONTEXT — distribute S1 data per H2 ═══
            _s1_ctx = _build_batch_s1_context(
                current_h2=current_h2,
                batch_num=batch_num,
                batch_type=batch_type,
                eav_triples=topical_gen_eav,
                svo_triples=topical_gen_svo,
                causal_chains=clean_causal_chains,
                causal_singles=clean_causal_singles,
                content_gaps=(s1.get("content_gaps") or {}),
                must_cover=must_cover_concepts,
                entity_gaps=entity_gaps,
                cooc_pairs=backend_cooccurrence_pairs,
                entity_plan=_entity_content_plan,
                main_kw=main_keyword,
            )
            pre_batch["_s1_context"] = _s1_ctx
            pre_batch["_search_variants"] = search_variants
            _ctx_items = sum(len(v) if isinstance(v, list) else (1 if v else 0) for v in _s1_ctx.values())
            yield emit("log", {"msg": f"🎯 S1 context: {_ctx_items} items matched to H2"})

            # v67: Word budget cap — prevent article from being 2x+ recommended length
            # Calculate max words per batch from target_length
            _budget_per_batch = max(150, _target_length // total_batches)
            _batch_bl = pre_batch.get("batch_length") or {}
            _orig_max = _batch_bl.get("suggested_max", _batch_bl.get("max_words", 500))
            if isinstance(_orig_max, (int, float)) and _orig_max > _budget_per_batch * 1.3:
                # Cap the batch word range to fit target_length
                _capped_max = int(_budget_per_batch * 1.2)
                _capped_min = max(100, int(_budget_per_batch * 0.7))
                pre_batch["batch_length"] = {
                    **_batch_bl,
                    "suggested_min": _capped_min,
                    "suggested_max": _capped_max,
                    "min_words": _capped_min,
                    "max_words": _capped_max,
                    "_original_max": _orig_max,
                    "_capped_by": "target_length_guard",
                }
                yield emit("log", {"msg": f"📏 Word cap: {_orig_max}→{_capped_max} words/batch (target {_target_length} / {total_batches} batchy)"})


            # Emit batch instructions for UI display
            caution_kw = (pre_batch.get("keyword_limits") or {}).get("caution_keywords", [])
            batch_length_info = pre_batch.get("batch_length") or {}
            enhanced_data = pre_batch.get("enhanced") or {}
            
            yield emit("batch_instructions", {
                "batch": batch_num,
                "total": total_batches,
                "batch_type": batch_type,
                "h2": current_h2,
                "h2_remaining": h2_remaining[:5],
                "target_words": batch_length_info.get("suggested_min", batch_length_info.get("target", "?")),
                "word_range": f"{batch_length_info.get('suggested_min', '?')}-{batch_length_info.get('suggested_max', '?')}",
                "must_keywords": [kw.get("keyword", kw) if isinstance(kw, dict) else kw for kw in must_kw],
                "extended_keywords": [kw.get("keyword", kw) if isinstance(kw, dict) else kw for kw in ext_kw],
                "stop_keywords": [kw.get("keyword", kw) if isinstance(kw, dict) else kw for kw in stop_kw][:10],
                "caution_keywords": [kw.get("keyword", kw) if isinstance(kw, dict) else kw for kw in caution_kw][:10],
                "coverage": pre_batch.get("coverage") or {},
                "density": pre_batch.get("density") or {},
                "has_gpt_instructions": bool(pre_batch.get("gpt_instructions_v39")),
                "has_gpt_prompt": bool(pre_batch.get("gpt_prompt")),
                "has_article_memory": bool(pre_batch.get("article_memory")),
                "has_enhanced": bool(enhanced_data),
                "has_style": bool(pre_batch.get("style_instructions")),
                "has_legal": bool((pre_batch.get("legal_context") or {}).get("active")),
                "has_medical": bool((pre_batch.get("medical_context") or {}).get("active")),
                "semantic_plan": {
                    "h2": (pre_batch.get("semantic_batch_plan") or {}).get("h2"),
                    "profile": (pre_batch.get("semantic_batch_plan") or {}).get("profile"),
                    "score": (pre_batch.get("semantic_batch_plan") or {}).get("score")
                },
                "entities_to_define": (enhanced_data.get("entities_to_define") or [])[:5],
                "experience_markers": bool(enhanced_data.get("experience_markers")),
                "continuation_context": bool(enhanced_data.get("continuation_context")),
                "paa_from_serp": (enhanced_data.get("paa_from_serp") or [])[:3],
                "main_keyword_ratio": (pre_batch.get("main_keyword") or {}).get("ratio"),
                "intro_guidance_active": bool(pre_batch.get("intro_guidance")) if batch_type == "INTRO" else False,
                "lead_serp_signals": {
                    "has_snippet": bool((pre_batch.get("serp_enrichment") or {}).get("featured_snippet")),
                    "has_ai_overview": bool((pre_batch.get("serp_enrichment") or {}).get("ai_overview")),
                    "search_intent": (pre_batch.get("serp_enrichment") or {}).get("search_intent", ""),
                    "snippet_preview": str((pre_batch.get("serp_enrichment") or {}).get("featured_snippet", ""))[:150],
                    "ai_overview_preview": str(
                        (lambda a: a if isinstance(a, str) else (a.get("text", "") if isinstance(a, dict) else str(a)))(
                            (pre_batch.get("serp_enrichment") or {}).get("ai_overview", "")
                        )
                    )[:200],
                } if batch_type in ("INTRO", "intro") else {},
                # v45 flags
                "has_causal_context": bool(enhanced_data.get("causal_context")),
                "has_information_gain": bool(enhanced_data.get("information_gain")),
                "has_smart_instructions": bool(enhanced_data.get("smart_instructions")),
                "has_phrase_hierarchy": bool(enhanced_data.get("phrase_hierarchy")),
                "has_entity_salience": bool(entity_salience_instructions),
                "has_continuation_v39": bool(pre_batch.get("continuation_v39")),
                # v47.0 flags
                "has_backend_placement": bool(backend_placement_instruction),
                "has_cooccurrence": bool(backend_cooccurrence_pairs),
                "has_concepts": bool(must_cover_concepts or concept_instruction),
                # v2.3: S1 smart context per H2
                "s1_context": {
                    "lead_entity": _s1_ctx.get("lead_entity", ""),
                    "eav_count": len(_s1_ctx.get("eav", [])),
                    "eav_preview": [f'{e.get("entity","")}: {e.get("value","")}' for e in _s1_ctx.get("eav", [])[:3]],
                    "svo_count": len(_s1_ctx.get("svo", [])),
                    "svo_preview": [f'{s.get("subject","")} → {s.get("verb","")} → {s.get("object","")}' for s in _s1_ctx.get("svo", [])[:2]],
                    "causal_count": len(_s1_ctx.get("causal", [])),
                    "causal_preview": [
                        (c.get("chain", c.get("text", str(c)))[:80] if isinstance(c, dict) else str(c)[:80])
                        for c in _s1_ctx.get("causal", [])[:2]
                    ],
                    "gaps": _s1_ctx.get("gaps", [])[:3],
                    "concepts": _s1_ctx.get("concepts", [])[:5],
                    "cooc": _s1_ctx.get("cooc", [])[:4],
                    "entity_gaps": _s1_ctx.get("entity_gaps", [])[:3],
                } if _s1_ctx else {},
            })

            # 6c: Generate text
            has_instructions = bool(pre_batch.get("gpt_instructions_v39"))
            has_enhanced = bool(pre_batch.get("enhanced"))
            has_memory = bool(pre_batch.get("article_memory"))
            has_causal = bool(enhanced_data.get("causal_context"))
            has_smart = bool(enhanced_data.get("smart_instructions"))
            # v50.8 FIX 49: Determine effort/web_search for logging
            _is_ymyl = pre_batch.get("_is_ymyl", False)
            _ymyl_int = pre_batch.get("_ymyl_intensity", "none")
            _effort = "high" if _ymyl_int == "full" else ("medium" if _ymyl_int == "light" else None)
            _effort_label = _effort or f"temp={temperature or 0.7}"
            _web = _is_ymyl and _ymyl_int == "full"
            yield emit("log", {"msg": f"Generuję tekst przez {'🟢 ' + effective_openai_model if engine == 'openai' else '🟣 ' + _get_anthropic_model()}... [effort={_effort_label} web={'✅' if _web else '—'} instr={'✅' if has_instructions else '❌'} enhanced={'✅' if has_enhanced else '❌'} memory={'✅' if has_memory else '❌'}]"})

            if batch_type == "FAQ":
                # FAQ batch: first analyze PAA
                paa_result = brajen_call("get", f"/api/project/{project_id}/paa/analyze")
                paa_data = paa_result["data"] if paa_result["ok"] else {}
                text = generate_faq_text(paa_data, pre_batch, engine=engine, openai_model=effective_openai_model, temperature=temperature)
            else:
                # ═══ v66: STRUCTURED ARTICLE MEMORY — zero LLM calls, deterministic ═══
                article_memory = pre_batch.get("article_memory")
                if not article_memory and accepted_batches_log:
                    # v66: Structured tracker — incremental update, no Haiku call
                    _structured_memory = structured_article_memory(
                        accepted_batches_log, main_keyword, prev_memory=_structured_memory
                    )
                    article_memory = _structured_memory
                    _rep_count = len(_structured_memory.get("avoid_repetition", []))
                    _fact_count = len(_structured_memory.get("key_facts", []))
                    _def_count = len(_structured_memory.get("definitions_given", []))
                    yield emit("log", {"msg": f"🧠 Structured memory: {_fact_count} faktów, {_def_count} definicji, {_rep_count} do unikania"})
                
                # ═══ v2.5: VOICE CONTINUITY — inject style reference into pre_batch ═══
                if batch_num > 1 and accepted_batches_log:
                    _prev_text = accepted_batches_log[-1].get("text", "")
                    if _prev_text:
                        # Extract last 3 sentences for smooth transition
                        import re as _re_vc
                        _prev_sents = [s.strip() for s in _re_vc.split(r'(?<=[.!?])\s+', _prev_text) if len(s.strip()) > 15]
                        _last_3 = _prev_sents[-3:] if len(_prev_sents) >= 3 else _prev_sents
                        pre_batch["_voice_last_sentences"] = "\n".join(_last_3)
                    if _style_anchor:
                        pre_batch["_voice_style_anchor"] = _style_anchor

                    # ═══ v2: Inject entity tracker ═══
                    if _entity_tracker and _entity_tracker.get("entities"):
                        pre_batch["_entity_tracker"] = _entity_tracker

                text = generate_batch_text(
                    pre_batch, current_h2, batch_type,
                    article_memory, engine=engine, openai_model=effective_openai_model,
                    temperature=temperature,
                    content_type=content_type, category_data=category_data
                )

            word_count = len(text.split())
            # v67: Estimate cost from output size (avg 1.3 tokens/word for Polish)
            _est_out = int(word_count * 1.3)
            _est_in = int(len(json.dumps(pre_batch, ensure_ascii=False)) * 0.3)  # rough prompt estimate
            _cost_model = _get_anthropic_model() if engine == "claude" else (effective_openai_model or "gpt-5.2")
            cost_tracker.record(job_id, _cost_model, _est_in, _est_out, step="batch_generation")
            yield emit("log", {"msg": f"Wygenerowano {word_count} słów"})

            # Post-process: strip duplicate ## headers (Claude sometimes outputs both h2: and ##)
            text = _clean_batch_text(text)

            # 6d-6g: Submit with retry logic
            # v66: Adaptive retry strategy:
            # attempt 1: submit as-is (normal validation)
            # attempt 2: relaxed threshold (85%) — accept if quality decent
            # attempt 3: ADAPTIVE — shorten batch + relax keyword requirements
            # No more forced save — quality over completion.
            max_attempts = 3
            batch_accepted = False
            _failed_keywords = set()  # Track which keywords keep failing

            for attempt in range(max_attempts):
                submit_data = {"text": text, "attempt": attempt + 1}
                if attempt >= 2:
                    # v66: ADAPTIVE strategy — relax keyword requirements instead of forced save
                    # Tell backend to relax: drop EXTENDED requirements, lower BASIC thresholds
                    submit_data["relaxed_threshold"] = 60  # Accept at 60% quality
                    submit_data["drop_extended"] = True  # Don't fail on EXTENDED keywords
                    submit_data["relax_basic_factor"] = 0.5  # Accept 50% of BASIC targets
                    yield emit("log", {"msg": f"🔧 Adaptive strategy: relaxed requirements (attempt {attempt + 1}/{max_attempts})"})
                elif attempt >= 1:
                    # v62: Relax threshold earlier — accept on attempt 2 if quality decent
                    submit_data["relaxed_threshold"] = 70 + (attempt) * 15  # 85% on attempt 2
                    yield emit("log", {"msg": f"🔧 Relaxed threshold: {submit_data['relaxed_threshold']}% (attempt {attempt + 1})"})

                yield emit("log", {"msg": f"POST /batch_simple (próba {attempt + 1}/{max_attempts})"})
                submit_result = brajen_call("post", f"/api/project/{project_id}/batch_simple", submit_data)

                if not submit_result["ok"]:
                    yield emit("log", {"msg": f"❌ Submit error: {submit_result.get('error', '')[:100]}"})
                    break

                result = submit_result["data"]
                accepted = result.get("accepted", False)
                action = result.get("action", "CONTINUE")
                quality = (result.get("quality") or {})
                depth = result.get("depth_score")
                exceeded = (result.get("exceeded_keywords") or [])

                yield emit("batch_result", {
                    "batch": batch_num,
                    "accepted": accepted,
                    "action": action,
                    "quality_score": quality.get("score"),
                    "quality_grade": quality.get("grade"),
                    "depth_score": depth,
                    "exceeded": [e.get("keyword", "") for e in exceeded] if exceeded else [],
                    "word_count": len(text.split()) if text else 0,
                    "text_preview": text if accepted else ""
                })

                if accepted:
                    batch_accepted = True
                    _score = quality.get('score')
                    if _score is None:
                        yield emit("log", {"msg": f"⚠️ Batch {batch_num} accepted ale quality=null — backend mógł nie zapisać tekstu"})
                    else:
                        yield emit("log", {"msg": f"✅ Batch {batch_num} accepted! Score: {_score}/100"})
                    # Content integrity check
                    if text:
                        _ci = []; tl = text.lower()
                        if "mg/100 ml" in tl or "mg/100ml" in tl:
                            _ci.append("❌ JEDNOSTKI: 'mg/100 ml' → promile lub mg/dm³")
                        if "odpowiednich przepisów" in tl or "właściwych przepisów" in tl:
                            _ci.append("❌ PLACEHOLDER: wstaw konkretny artykuł (art. X k.k.)")
                        if ("do 2 lat" in tl or "2 lata więzienia" in tl) and "alkohol" in tl:
                            _ci.append("❌ KARA: 'do 2 lat' → art. 178a §1 = do 3 lat (2023)")
                        if "ciągu 2 lat" in tl and "recydyw" in tl:
                            _ci.append("❌ RECYDYWA: brak limitu czasowego w art. 178a §4")
                        for w in _ci:
                            yield emit("log", {"msg": w})
                    # ── v62: Post-acceptance cleanup — MAX 1 Sonnet rewrite ──
                    # Each rewrite "smooths" the text. 3 rewrites = robotic.
                    # Priority: domain (YMYL safety) > anaphora > sentence length
                    _post_rewrite_done = False

                    # ═══ DOMAIN VALIDATOR (Warstwa 2) — highest priority ═══
                    _dv_category = "prawo" if is_legal else ("medycyna" if is_medical else ("finanse" if is_finance else ""))
                    if _dv_category and text and not _post_rewrite_done:
                        _dv = validate_batch_domain(text, _dv_category, batch_num)
                        if not _dv.get("skipped"):
                            if not _dv.get("clean"):
                                _dv_errors = _dv.get("errors", [])
                                _dv_quick = _dv.get("quick_hits", [])
                                _dv_log = [e.get("found", e.get("type", "?")) for e in _dv_errors[:3]]
                                if _dv_quick:
                                    _dv_log = _dv_quick[:3]
                                yield emit("log", {"msg": f"🔴 DOMAIN VALIDATOR: {len(_dv_errors or _dv_quick)} błędów terminologicznych — naprawiam... ({', '.join(_dv_log)})"})
                                text = fix_batch_domain_errors(text, _dv, _dv_category, h2=current_h2)
                                yield emit("log", {"msg": f"✅ Domain fix: tekst poprawiony ({len(text.split())} słów)"})
                                _post_rewrite_done = True
                            else:
                                yield emit("log", {"msg": f"✅ Domain validator: czysto [{_dv_category}]"})

                    # ── Anaphora check — only if no domain rewrite was needed ──
                    if main_keyword and text and not _post_rewrite_done:
                        _an = check_anaphora(text, main_entity=main_keyword)
                        if _an["needs_fix"]:
                            yield emit("log", {"msg": f"🔁 ANAPHORA: {_an['anaphora_count']}× seria '{main_keyword[:30]}...' — naprawiam podmiot..."})
                            text_fixed = anaphora_retry(text, main_entity=main_keyword, h2=current_h2)
                            _an_after = check_anaphora(text_fixed, main_entity=main_keyword)
                            if not _an_after["needs_fix"] or _an_after["anaphora_count"] < _an["anaphora_count"]:
                                text = text_fixed
                                yield emit("log", {"msg": f"✅ Anaphora naprawiona"})
                                _post_rewrite_done = True
                            else:
                                yield emit("log", {"msg": f"⚠️ Anaphora nie poprawiona, zostawiam oryginał"})

                    # ── Sentence length — per-batch retry (batches ~400 words = OK for Haiku) ──
                    sl = check_sentence_length(text)
                    if sl["needs_retry"] and not _post_rewrite_done:
                        comma_info = f", {sl.get('comma_count', 0)} zdań z 3+ przecinkami" if sl.get("comma_count", 0) > 0 else ""
                        yield emit("log", {"msg": f"✂️ Zdania długie (śr. {sl['avg_len']} słów{comma_info}) — rozbijam..."})
                        text_fixed = sentence_length_retry(
                            text, h2=current_h2,
                            avg_len=sl["avg_len"],
                            long_count=sl["long_count"],
                            comma_count=sl.get("comma_count", 0)
                        )
                        if text_fixed and text_fixed != text and len(text_fixed) > len(text) * 0.7:
                            sl_after = check_sentence_length(text_fixed)
                            if sl_after["avg_len"] < sl["avg_len"] or sl_after.get("comma_count", 0) < sl.get("comma_count", 0):
                                text = text_fixed
                                _post_rewrite_done = True
                                yield emit("log", {"msg": f"✅ Zdania rozbite: śr. {sl['avg_len']}→{sl_after['avg_len']} słów, przecinki: {sl.get('comma_count',0)}→{sl_after.get('comma_count',0)}"})
                            else:
                                yield emit("log", {"msg": f"⚠️ Sentence retry nie poprawił — zostawiam oryginał"})
                        else:
                            yield emit("log", {"msg": f"⚠️ Sentence retry zwrócił garbage — zostawiam oryginał"})
                    elif sl["needs_retry"]:
                        comma_info = f", {sl.get('comma_count', 0)} zdań z 3+ przecinkami" if sl.get("comma_count", 0) > 0 else ""
                        yield emit("log", {"msg": f"ℹ️ Zdania długie (śr. {sl['avg_len']} słów{comma_info}) — skip (anaphora już poprawiła)"})

                    # Fix #56: Update globalny licznik głównego keywordu
                    # Note: exact match jest OK jako local budget tracker —
                    # prawdziwe zliczanie z lematyzacją robi Brajen API (keyword_counter.py + spaCy)
                    if text and main_keyword:
                        import re as _re_kw
                        _kw_lower = main_keyword.lower()
                        _kw_count_batch = len(_re_kw.findall(r'\b' + _re_kw.escape(_kw_lower) + r'\b', text.lower()))
                        _global_main_kw_count += _kw_count_batch
                        _kw_remaining = max(0, _GLOBAL_KW_MAX - _global_main_kw_count)
                        yield emit("log", {"msg": f"📊 KW global: {_global_main_kw_count}/{_GLOBAL_KW_MAX} wystąpień '{main_keyword}' (pozostało: {_kw_remaining})"})

                    # Bug A Fix: Zaktualizuj lokalny tracker H2 po zaakceptowanym batchu
                    # INTRO nie pisze treści H2 — nie oznaczaj H2 jako zużytego
                    if batch_type not in ("INTRO", "intro"):
                        _h2_key = current_h2.strip().lower()
                        if _h2_key not in _h2_local_done:
                            _h2_local_done.append(_h2_key)
                        # Znajdz nastepny H2 z planu ktory nie byl jeszcze uzyty
                        while _h2_local_idx < len(h2_structure) and \
                              h2_structure[_h2_local_idx].strip().lower() in _h2_local_done:
                            _h2_local_idx += 1

                    # Track for memory
                    accepted_batches_log.append({
                        "text": text, "h2": current_h2, "batch_num": batch_num,
                        "depth_score": depth
                    })

                    # ═══ v66: CONSISTENCY CHECK — detect contradictions between batches ═══
                    if batch_num >= 3 and len(accepted_batches_log) >= 2 and ANTHROPIC_API_KEY:
                        try:
                            _prev_texts = []
                            for _pb in accepted_batches_log[-3:-1]:  # previous 2 batches
                                _pt = _pb.get("text", "")
                                if _pt:
                                    _prev_texts.append(_pt[:400])
                            if _prev_texts:
                                _consist_prompt = (
                                    f'POPRZEDNIE SEKCJE artykułu o "{main_keyword}":\n'
                                    + "\n---\n".join(_prev_texts) + "\n\n"
                                    f'NOWA SEKCJA:\n{text[:500]}\n\n'
                                    f'Czy nowa sekcja ZAPRZECZA czemuś z poprzednich? '
                                    f'Szukaj: sprzecznych liczb, dat, definicji, twierdzeń.\n'
                                    f'Odpowiedz TYLKO: "OK" jeśli brak sprzeczności, '
                                    f'lub "SPRZECZNOŚĆ: [opis]" jeśli jest.'
                                )
                                _consist_res = _generate_claude(
                                    system_prompt="Sprawdzasz spójność artykułu. Zwracasz TYLKO 'OK' lub 'SPRZECZNOŚĆ: [opis]'.",
                                    user_prompt=_consist_prompt,
                                    temperature=0,
                                )
                                if _consist_res and "SPRZECZNOŚĆ" in _consist_res.upper():
                                    yield emit("log", {"msg": f"⚠️ CONSISTENCY: {_consist_res[:120]}"})
                                    yield emit("consistency_warning", {
                                        "batch": batch_num,
                                        "warning": _consist_res[:200]
                                    })
                        except Exception as _ce:
                            pass  # Non-critical, don't block pipeline

                    break

                # Not accepted, decide retry strategy
                if attempt == max_attempts - 1:
                    # v66: Last attempt with adaptive strategy — accept with warning
                    # Quality is likely decent after relaxed thresholds
                    yield emit("log", {"msg": f"⚠️ Batch {batch_num}: accepting after adaptive strategy (attempt {attempt + 1})"})
                    # Bug A Fix: update H2 tracker also in adaptive mode (INTRO excluded)
                    if batch_type not in ("INTRO", "intro"):
                        _h2_key_f = current_h2.strip().lower()
                        if _h2_key_f not in _h2_local_done:
                            _h2_local_done.append(_h2_key_f)
                        while _h2_local_idx < len(h2_structure) and \
                              h2_structure[_h2_local_idx].strip().lower() in _h2_local_done:
                            _h2_local_idx += 1
                    accepted_batches_log.append({
                        "text": text, "h2": current_h2, "batch_num": batch_num,
                        "depth_score": depth
                    })
                    batch_accepted = True
                    break

                # ═══ AI MIDDLEWARE: Smart retry ═══
                # v62: Only retry for EXCEEDED (overstuffed) keywords.
                # Missing keywords = acceptable, model wrote naturally.
                # Only exceeded = reader experience harmed by repetition.
                if exceeded and should_use_smart_retry(result, attempt + 1):
                    yield emit("log", {"msg": f"🤖 AI Smart Retry: Sonnet przepisuje tekst (redukcja {len(exceeded)} przekroczonych fraz)..."})
                    text = smart_retry_batch(
                        original_text=text,
                        exceeded_keywords=exceeded,
                        pre_batch=pre_batch,
                        h2=current_h2,
                        batch_type=batch_type,
                        attempt_num=attempt + 1
                    )
                    new_word_count = len(text.split())
                    yield emit("log", {"msg": f"🔄 Smart retry: {new_word_count} słów, próba {attempt + 2}/{max_attempts}"})
                    text = _clean_batch_text(text)
                elif not exceeded:
                    # v62: Not accepted but no exceeded keywords = missing keywords only.
                    # Don't retry — accept as-is to preserve natural text.
                    yield emit("log", {"msg": f"ℹ️ Batch odrzucony za brakujące frazy — akceptuję naturalny tekst (attempt {attempt + 1})"})
                    batch_accepted = True
                    accepted_batches_log.append({
                        "text": text, "h2": current_h2, "batch_num": batch_num,
                        "depth_score": depth
                    })
                    if batch_type not in ("INTRO", "intro"):
                        _h2_key = current_h2.strip().lower()
                        if _h2_key not in _h2_local_done:
                            _h2_local_done.append(_h2_key)
                        while _h2_local_idx < len(h2_structure) and \
                              h2_structure[_h2_local_idx].strip().lower() in _h2_local_done:
                            _h2_local_idx += 1
                    break
                else:
                    # Exceeded but smart retry not applicable — simple retry
                    yield emit("log", {"msg": f"🔄 Retry: exceeded keywords, próba {attempt + 2}/{max_attempts}"})

            # ═══ v2.5: VOICE CONTINUITY — extract style anchor from INTRO ═══
            if batch_accepted and accepted_batches_log:
                _last_text = accepted_batches_log[-1].get("text", "")

                # Extract style anchor from batch 1 (INTRO) — best sentences for voice reference
                if batch_num == 1 and _last_text and not _style_anchor:
                    import re as _re_sa
                    _sents = [s.strip() for s in _re_sa.split(r'(?<=[.!?])\s+', _last_text) if len(s.strip()) > 30]
                    # v2: Pick sentences that best represent the article style:
                    # - Not headers (h2:/h3:)
                    # - Have at least one number or specific fact (good anchor)
                    # - Between 40-200 chars (not too short/long)
                    _good = []
                    _ok = []
                    for s in _sents:
                        if s.startswith("h2:") or s.startswith("h3:"):
                            continue
                        if len(s) < 40 or len(s) > 200:
                            continue
                        # Prefer sentences with numbers (more concrete = better anchor)
                        if any(c.isdigit() for c in s):
                            _good.append(s)
                        else:
                            _ok.append(s)
                    # Take best: numbered sentences first, then ok sentences
                    _selected = (_good + _ok)[:3]
                    _style_anchor = "\n".join(_selected)
                    if _style_anchor:
                        yield emit("log", {"msg": f"🎨 v2 Kotwica stylu z INTRO: {len(_selected)} zdań ({len(_good)} z liczbami)"})

            # Save FAQ if applicable
            if batch_type == "FAQ" and batch_accepted:
                yield emit("log", {"msg": "Zapisuję FAQ/PAA (Schema.org)..."})
                questions = []
                lines = text.split("\n")
                current_q, current_a = None, []
                for line in lines:
                    stripped = line.strip()
                    if stripped.startswith("h3:") or stripped.startswith("### "):
                        if current_q and current_a:
                            questions.append({"question": current_q, "answer": " ".join(current_a)})
                        current_q = stripped.replace("h3:", "").replace("###", "").strip()
                        current_a = []
                    elif current_q and stripped:
                        current_a.append(stripped)
                if current_q and current_a:
                    questions.append({"question": current_q, "answer": " ".join(current_a)})
                if questions:
                    brajen_call("post", f"/api/project/{project_id}/paa/save", {"questions": questions})

            yield emit("step", {"step": 6, "name": "Batch Loop", "status": "running",
                                "detail": f"{batch_num}/{total_batches} batchy"})

        step_done(6)
        yield emit("step", {"step": 6, "name": "Batch Loop", "status": "done",
                            "detail": f"{total_batches}/{total_batches} batchy"})

        # Emit article memory state for dashboard
        if article_memory:
            mem = article_memory if isinstance(article_memory, dict) else {}
            yield emit("article_memory", {
                "topics_covered": mem.get("topics_covered", [])[:20],
                "open_threads": mem.get("open_threads", [])[:10],
                "entities_introduced": mem.get("entities_introduced", [])[:15],
                "defined_terms": mem.get("defined_terms", [])[:15],
                "thesis": mem.get("thesis", ""),
                "tone": mem.get("tone", ""),
                "batch_count": len(accepted_batches_log),
            })

        # ─── KROK 7: PAA Check ───
        step_start(7)
        yield emit("step", {"step": 7, "name": "PAA Analyze & Save", "status": "running"})
        try:
            paa_check = brajen_call("get", f"/api/project/{project_id}/paa")
            paa_data_check = paa_check.get("data") if paa_check.get("ok") else None
            paa_has_section = isinstance(paa_data_check, dict) and paa_data_check.get("paa_section")
            if not paa_has_section:
                yield emit("log", {"msg": f"Brak sekcji FAQ w artykule — generuję z {len(s1.get('paa') or s1.get('paa_questions') or [])} pytań PAA..."})
                paa_analyze = brajen_call("get", f"/api/project/{project_id}/paa/analyze")
                if paa_analyze["ok"] and paa_analyze.get("data"):
                    # Fetch pre_batch for FAQ context (stop keywords, style, memory)
                    faq_pre = brajen_call("get", f"/api/project/{project_id}/pre_batch_info", timeout=HEAVY_REQUEST_TIMEOUT)
                    faq_pre_batch = faq_pre["data"] if faq_pre.get("ok") and isinstance(faq_pre.get("data"), dict) else None
                    paa_data_for_faq = paa_analyze["data"] if isinstance(paa_analyze.get("data"), dict) else {}
                    # v50.7 FIX 37: Ensure faq_pre_batch is a dict (some endpoints return str)
                    if faq_pre_batch and not isinstance(faq_pre_batch, dict):
                        logger.warning(f"[FAQ] pre_batch is {type(faq_pre_batch).__name__}, forcing None")
                        faq_pre_batch = None
                    try:
                        faq_text = generate_faq_text(paa_data_for_faq, faq_pre_batch, engine=engine, openai_model=effective_openai_model, temperature=temperature)
                    except AttributeError as ae:
                        logger.warning(f"[FAQ] generate_faq_text AttributeError: {ae}, retrying without pre_batch")
                        faq_text = generate_faq_text(paa_data_for_faq, None, engine=engine, openai_model=effective_openai_model, temperature=temperature)
                    if faq_text and faq_text.strip():
                        brajen_call("post", f"/api/project/{project_id}/batch_simple", {"text": faq_text})
                        # Extract and save
                        questions = []
                        lines = faq_text.split("\n")
                        cq, ca = None, []
                        for line in lines:
                            s = line.strip()
                            if s.startswith("h3:") or s.startswith("### "):
                                if cq and ca:
                                    questions.append({"question": cq, "answer": " ".join(ca)})
                                cq = s.replace("h3:", "").replace("###", "").strip()
                                ca = []
                            elif cq and s:
                                ca.append(s)
                        if cq and ca:
                            questions.append({"question": cq, "answer": " ".join(ca)})
                        if questions:
                            brajen_call("post", f"/api/project/{project_id}/paa/save", {"questions": questions})

                        # Emit PAA data for dashboard
                        paa_from_serp = (s1.get("paa") or s1.get("paa_questions") or [])
                        yield emit("paa_data", {
                            "questions_generated": len(questions) if questions else 0,
                            "faq_text_length": len(faq_text) if faq_text else 0,
                            "paa_questions_from_serp": len(paa_from_serp),
                            "paa_unanswered": len(({} if not isinstance(s1.get("content_gaps"), dict) else s1.get("content_gaps")).get("paa_unanswered", [])),
                            "status": "generated",
                        })
                    else:
                        yield emit("log", {"msg": "⚠️ Brak danych PAA, pomijam FAQ"})
                else:
                    yield emit("log", {"msg": "⚠️ PAA analyze pusty, pomijam FAQ"})
                step_done(7)
                yield emit("step", {"step": 7, "name": "PAA Analyze & Save", "status": "done"})
            else:
                yield emit("step", {"step": 7, "name": "PAA Analyze & Save", "status": "done",
                                    "detail": "FAQ już zapisane"})
        except Exception as faq_err:
            logger.warning(f"FAQ generation error (non-fatal): {faq_err}")
            yield emit("log", {"msg": f"⚠️ FAQ error: {str(faq_err)[:80]}, pomijam, kontynuuję"})
            yield emit("step", {"step": 7, "name": "PAA Analyze & Save", "status": "warning",
                                "detail": "Błąd FAQ, pominięto"})

        # ─── KROK 8+9: Content Editorial + Editorial Review (PARALLEL) ───
        # v68: Run both concurrently — Content Editorial is analysis-only,
        # Editorial Review is rewrite. Both read the same text, don't conflict.
        import concurrent.futures

        step_start(8)
        step_start(9)
        yield emit("step", {"step": 8, "name": "Content Editorial", "status": "running"})
        yield emit("step", {"step": 9, "name": "Editorial Review", "status": "running"})
        yield emit("log", {"msg": "🔀 Content Editorial + Editorial Review (równolegle)..."})

        _ce_article = "\n\n".join(b.get("text", "") for b in accepted_batches_log if b.get("text"))
        _ce_payload = {"article_text": _ce_article} if _ce_article else {}

        def _run_content_editorial():
            return brajen_call("post", f"/api/project/{project_id}/content_editorial", json_data=_ce_payload, timeout=HEAVY_REQUEST_TIMEOUT)

        def _run_editorial_review():
            return brajen_call("post", f"/api/project/{project_id}/editorial_review", json_data={}, timeout=HEAVY_REQUEST_TIMEOUT)

        content_editorial_result = {"ok": False}
        editorial_result = {"ok": False}
        editorial_score = None

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as _pool:
            _ce_future = _pool.submit(_run_content_editorial)
            _er_future = _pool.submit(_run_editorial_review)
            
            # Collect results (with timeout safety)
            try:
                content_editorial_result = _ce_future.result(timeout=HEAVY_REQUEST_TIMEOUT + 10)
            except Exception as _ce_ex:
                yield emit("log", {"msg": f"⚠️ Content Editorial error: {str(_ce_ex)[:100]}"})
            
            try:
                editorial_result = _er_future.result(timeout=HEAVY_REQUEST_TIMEOUT + 10)
            except Exception as _er_ex:
                yield emit("log", {"msg": f"⚠️ Editorial Review error: {str(_er_ex)[:100]}"})

        # Process Content Editorial result
        if content_editorial_result["ok"]:
            ced = content_editorial_result["data"]
            ced_status = ced.get("status", "OK")
            ced_score = ced.get("score", 100)
            ced_critical = ced.get("critical_count", 0)
            ced_warnings = ced.get("warning_count", 0)
            detail = f"Status: {ced_status} | Score: {ced_score}/100 | Krytyczne: {ced_critical} | Ostrzeżenia: {ced_warnings}"
            yield emit("content_editorial", {
                "status": ced_status,
                "score": ced_score,
                "critical_count": ced_critical,
                "warning_count": ced_warnings,
                "issues": ced.get("issues", [])[:5],
                "summary": ced.get("summary", ""),
                "blocked": ced.get("blocked", False),
            })
            if ced.get("blocked"):
                yield emit("log", {"msg": f"⚠️ Content Editorial: BLOCKED — {ced.get('blocked_reason', '')}. Artykuł wymaga poprawy merytorycznej."})
                yield emit("step", {"step": 8, "name": "Content Editorial", "status": "warning", "detail": f"BLOCKED: {ced.get('blocked_reason', '')[:80]}"})
            else:
                step_done(8)
                yield emit("step", {"step": 8, "name": "Content Editorial", "status": "done", "detail": detail})
        else:
            _ce_err = content_editorial_result.get("error", "Unknown error")
            yield emit("log", {"msg": f"⚠️ Content Editorial failed: {str(_ce_err)[:100]}"})
            yield emit("content_editorial", {
                "status": "ERROR", "score": 0, "critical_count": 0, "warning_count": 0,
                "issues": [{"severity": "info", "message": f"Analiza niedostępna: {str(_ce_err)[:80]}"}],
                "summary": "Content editorial nie zwrócił wyniku — artykuł kontynuuje normalnie.",
                "blocked": False,
            })
            yield emit("step", {"step": 8, "name": "Content Editorial", "status": "warning", "detail": f"Błąd: {str(_ce_err)[:60]}"})

        # Process Editorial Review result (from parallel execution above)
        if editorial_result["ok"]:
            ed = editorial_result["data"]
            score = ed.get("overall_score", "?")
            diff = (ed.get("diff_result") or {})
            rollback = (ed.get("rollback") or {})
            word_guard = (ed.get("word_count_guard") or {})

            detail = f"Ocena: {score}/10 | Zmiany: {diff.get('applied', 0)}/{diff.get('total_changes_parsed', 0)}"
            if word_guard:
                detail += f" | Słowa: {word_guard.get('original', '?')}→{word_guard.get('corrected', '?')}"

            yield emit("editorial", {
                "score": score,
                "changes_applied": diff.get("applied", 0),
                "changes_failed": diff.get("failed", 0),
                "word_count_before": word_guard.get("original"),
                "word_count_after": word_guard.get("corrected"),
                "rollback": rollback.get("triggered", False),
                "rollback_reason": rollback.get("reason", ""),
                "feedback": (ed.get("editorial_feedback") or {}),
                "applied_changes": (ed.get("applied_changes") or diff.get("applied_changes") or [])[:20],
                "failed_changes": (ed.get("failed_changes") or diff.get("failed_changes") or [])[:15],
                "summary": (ed.get("editorial_feedback") or {}).get("summary", ed.get("summary", "")),
                "errors_found": (ed.get("editorial_feedback") or {}).get("errors_to_fix", [])[:15],
                "grammar_fixes": (ed.get("grammar_correction") or {}).get("fixes", 0),
                "grammar_removed": (ed.get("grammar_correction") or {}).get("removed", [])[:5],
            })

            if rollback.get("triggered"):
                yield emit("log", {"msg": f"⚠️ ROLLBACK: {rollback.get('reason', 'unknown')}"})

            # Integrity checks — don't apply corrupted/truncated editorial
            if not rollback.get("triggered"):
                corrected_text = ed.get("corrected_article", "")
                original_wc = word_guard.get("original", 0) or 0
                corrected_wc = len(corrected_text.split()) if corrected_text else 0
                changes_parsed = diff.get("total_changes_parsed", 0)
                editorial_score = score if isinstance(score, (int, float)) else 0

                skip_reason = None
                if not corrected_text or len(corrected_text.strip()) <= 50:
                    skip_reason = "tekst pusty lub za krótki"
                elif original_wc > 0 and corrected_wc < original_wc * 0.6:
                    skip_reason = f"obcięty ({corrected_wc} vs {original_wc} słów)"
                elif ("h2" not in corrected_text.lower() and "h3:" not in corrected_text.lower()
                      and "<p" not in corrected_text.lower()):
                    skip_reason = "brak struktury HTML (h2/p)"
                elif editorial_score <= 2 and changes_parsed == 0:
                    skip_reason = f"niska ocena ({editorial_score}/10) i 0 zmian"

                if skip_reason:
                    yield emit("log", {"msg": f"⚠️ Editorial: pominięto aktualizację — {skip_reason}"})
                else:
                    corrected_text = _normalize_html_tags(corrected_text)
                    yield emit("article", {
                        "text": corrected_text,
                        "word_count": corrected_wc,
                        "source": "editorial_review",
                    })
                    yield emit("log", {"msg": f"📝 Podgląd zaktualizowany po editorial ({corrected_wc} słów)"})
            step_done(9)
            yield emit("step", {"step": 9, "name": "Editorial Review", "status": "done", "detail": detail})
        else:
            ed_error = editorial_result.get("error", "unknown")
            ed_status = editorial_result.get("status", "?")
            yield emit("log", {"msg": f"⚠️ Editorial Review → {ed_status}: {str(ed_error)[:200]}"})
            yield emit("step", {"step": 9, "name": "Editorial Review", "status": "warning",
                                "detail": f"Nie udało się ({ed_status}), artykuł bez recenzji"})

        # ─── KROK 10: Final Review + YMYL Validation ─── [v67: now runs AFTER editorial]
        step_start(10)
        yield emit("step", {"step": 10, "name": "Final Review", "status": "running"})
        yield emit("log", {"msg": "GET /final_review (po editorial — ocena finalnego tekstu)..."})
        final_score = None

        final_result = brajen_call("get", f"/api/project/{project_id}/final_review", timeout=HEAVY_REQUEST_TIMEOUT)
        if final_result["ok"]:
            final = final_result["data"]
            # Unwrap cached response format
            if final.get("status") == "EXISTS" and "final_review" in final:
                final = final["final_review"]
            final_score = final.get("quality_score", final.get("score", "?"))
            final_status = final.get("status", "?")

            # v51 FIX: Read structured data from correct paths
            validations = final.get("validations") or {}
            kw_validation = validations.get("missing_keywords") or {}

            # Build proper missing/overuse lists from structured data
            actual_missing = []
            for kw in (kw_validation.get("priority_to_add", {}).get("to_add_by_claude", []) or [])[:5]:
                actual_missing.append(f"Wpleć '{kw.get('keyword', '')}' min. {kw.get('target_min', 1)}x")

            # Overuse warnings (separate from missing)
            overuse_warnings = []
            for kw in (kw_validation.get("within_tolerance", []) or [])[:3]:
                excess = kw.get("actual", 0) - kw.get("target_max", 0)
                overuse_warnings.append(f"🟡 Rozważ usunięcie {excess}x '{kw.get('keyword', '')}' ({kw.get('actual', 0)}/{kw.get('target_max', 0)})")
            for kw in (kw_validation.get("stuffing", []) or [])[:3]:
                excess = kw.get("actual", 0) - kw.get("target_max", 0)
                overuse_warnings.append(f"🔴 USUŃ {excess}x '{kw.get('keyword', '')}' ({kw.get('actual', 0)}/{kw.get('target_max', 0)})")

            # H3 length issues
            h3_issues = []
            for issue in (validations.get("h3_length", {}).get("issues", []) or [])[:3]:
                h3_issues.append(f"Rozbuduj H3 '{issue.get('h3', '')}' o {issue.get('deficit', 0)} słów")

            # Combined recommendations from API (fallback)
            all_recommendations = final.get("recommendations") or []
            missing_kw = actual_missing
            issues = (final.get("issues") or final.get("all_issues") or [])

            yield emit("final_review", {
                "score": final_score,
                "status": final_status,
                "missing_keywords_count": len(missing_kw),
                "missing_keywords": missing_kw[:10],
                "overuse_warnings": overuse_warnings[:5],
                "h3_issues": h3_issues[:5],
                "issues_count": len(issues) if isinstance(issues, list) else 0,
                "issues": issues[:5] if isinstance(issues, list) else [],
                "recommendations": all_recommendations[:10],
                "recommendations_count": len(all_recommendations),
                "issues_summary": final.get("issues_summary") or {},
                "stuffing": (final.get("validations") or {}).get("missing_keywords", {}).get("stuffing", [])[:5],
                "priority_to_add": (final.get("validations") or {}).get("missing_keywords", {}).get("priority_to_add", {}).get("to_add_by_claude", [])[:5],
                "density": final.get("density") or final.get("keyword_density"),
                "word_count": final.get("word_count") or final.get("total_words"),
                "basic_coverage": final.get("basic_coverage"),
                "extended_coverage": final.get("extended_coverage"),
                "entity_scoring": final.get("entity_scoring") or {},
                "keyword_budget_summary": final.get("keyword_budget_summary") or {},
            })

            step_done(10)
            yield emit("step", {"step": 10, "name": "Final Review", "status": "done",
                                "detail": f"Score: {final_score}/100 | Status: {final_status}"})

            # YMYL validation (on post-editorial text)
            ymyl_validation = {"legal": None, "medical": None}
            if is_legal:
                yield emit("log", {"msg": "Walidacja prawna..."})
                full_art = brajen_call("get", f"/api/project/{project_id}/full_article")
                if full_art["ok"] and full_art["data"].get("full_article"):
                    legal_val = brajen_call("post", "/api/legal/validate",
                               {"full_text": full_art["data"]["full_article"]})
                    if legal_val["ok"]:
                        ymyl_validation["legal"] = legal_val.get("data") or {}
                        yield emit("log", {"msg": f"⚖️ Legal validation: {(legal_val.get('data') or {}).get('status', 'done')}"})
            if is_medical:
                yield emit("log", {"msg": "Walidacja medyczna..."})
                full_art = brajen_call("get", f"/api/project/{project_id}/full_article")
                if full_art["ok"] and full_art["data"].get("full_article"):
                    med_val = brajen_call("post", "/api/medical/validate",
                               {"full_text": full_art["data"]["full_article"]})
                    if med_val["ok"]:
                        ymyl_validation["medical"] = med_val.get("data") or {}
                        yield emit("log", {"msg": f"🏥 Medical validation: {(med_val.get('data') or {}).get('status', 'done')}"})
            if ymyl_validation["legal"] or ymyl_validation["medical"]:
                yield emit("ymyl_validation", ymyl_validation)
        else:
            fr_error = final_result.get("error", "unknown")
            yield emit("log", {"msg": f"⚠️ Final Review failed: {fr_error[:150]}"})
            yield emit("step", {"step": 10, "name": "Final Review", "status": "warning",
                                "detail": "Nie udało się, kontynuuję"})

        # ─── CITATION PASS (YMYL only) ───
        _wiki_arts_for_cit = ymyl_enrichment.get("_wiki_articles", [])
        if is_legal and (judgments_clean or _wiki_arts_for_cit):
            yield emit("log", {"msg": "📎 Citation pass — dopasowuję cytaty do tekstu..."})
            try:
                _cit_art = brajen_call("get", f"/api/project/{project_id}/full_article")
                if _cit_art["ok"] and _cit_art["data"].get("full_article"):
                    _art_text = _cit_art["data"]["full_article"]
                    _cit_sources = []
                    for j in judgments_clean[:5]:
                        sig = j.get("signature", "")
                        if not sig: continue
                        _cit_sources.append(
                            "ORZECZENIE [" + (j.get("matched_article") or "prawo karne") + "]: "
                            + sig + ", " + j.get("court","") + " (" + j.get("date","") + ")"
                            + (" — " + j.get("summary","")[:100] if j.get("summary") else "")
                        )
                    for w in _wiki_arts_for_cit[:3]:
                        _cit_sources.append(
                            "WIKIPEDIA [" + w.get("article_ref","") + "]: "
                            + w.get("title","") + " — " + w.get("extract","")[:150]
                            + " (" + w.get("url","") + ")"
                        )
                    if _cit_sources:
                        _cit_sys = (
                            "Jesteś redaktorem prawnym. Wstaw cytaty do artykułu TYLKO tam gdzie "
                            "akapit merytorycznie pokrywa się z danym orzeczeniem lub przepisem.\n\n"
                            "ZASADY:\n"
                            "1. Cytuj orzeczenie TYLKO gdy akapit dotyczy dokładnie tego zagadnienia\n"
                            "2. Wikipedia: wstaw '(zob. Wikipedia: [tytuł])' tylko przy pierwszym użyciu przepisu\n"
                            "3. NIE zmieniaj treści — tylko dopisz cytat w nawiasie na końcu zdania\n"
                            "4. Jeśli akapit nie pasuje — zostaw bez zmian\n"
                            "5. Zwróć TYLKO artykuł, bez komentarzy\n"
                            "6. Orzeczenia karne (II K, AKa) → tylko akapity o sankcjach karnych"
                        )
                        _sep = chr(10)
                        _cit_usr = ("ARTYKUL:" + _sep + _art_text + _sep + _sep + "---" + _sep + "DOSTEPNE CYTATY:" + _sep + _sep.join(_cit_sources) + _sep + _sep + "Zwroc artykul z wstawionymi cytatami.")
                        _cit_res = _generate_claude(_cit_sys, _cit_usr, effort="low", web_search=False, temperature=0.1)
                        if _cit_res and len(_cit_res) > len(_art_text) * 0.8:
                            yield emit("article_citation_pass", {"text": _cit_res, "sources_count": len(_cit_sources)})
                            yield emit("log", {"msg": f"✅ Citation pass: {len(_cit_sources)} źródeł wstawionych"})
                        else:
                            yield emit("log", {"msg": "⚠️ Citation pass: wynik zbyt krótki, pomijam"})
            except Exception as _ce:
                yield emit("log", {"msg": f"⚠️ Citation pass błąd: {str(_ce)[:80]}"})


        # ─── KROK 11: Export ───
        step_start(11)
        yield emit("step", {"step": 12, "name": "Export", "status": "running"})

        # Safe defaults for variables used in EVALUATION SUMMARY (outside if full_result block)
        full_text = None
        sal_score = None
        is_dominant = None
        st_score = None
        semantic_dist_result = {"enabled": False, "score": 0}

        # Get full article
        full_result = brajen_call("get", f"/api/project/{project_id}/full_article", timeout=HEAVY_REQUEST_TIMEOUT)
        if full_result["ok"]:
            full = full_result["data"]
            stats = (full.get("stats") or {})
            coverage = (full.get("coverage") or {})

            # v50.7 FIX 41: Use editorial corrected article if available
            article_text = full.get("full_article", "")
            full_article_wc = len(article_text.split()) if article_text else 0
            if editorial_result and editorial_result.get("ok"):
                ed_corrected = (editorial_result.get("data") or {}).get("corrected_article", "")
                if ed_corrected and len(ed_corrected.strip()) > 50:
                    ed_rollback = ((editorial_result.get("data") or {}).get("rollback") or {}).get("triggered", False)
                    ed_wc = len(ed_corrected.split())
                    # v56 FIX: Don't replace full article with truncated editorial output
                    # editorial_review reads from Firestore full_article field which may be stale
                    # while GET /full_article joins ALL batches correctly
                    if not ed_rollback and full_article_wc > 0 and ed_wc < full_article_wc * 0.75:
                        yield emit("log", {"msg": f"⚠️ Editorial truncated: {ed_wc} vs {full_article_wc} słów ({round(ed_wc/full_article_wc*100)}%) — zostawiam pełny artykuł"})
                    elif not ed_rollback:
                        article_text = ed_corrected
                        yield emit("log", {"msg": f"📝 Export: użyto tekst po editorial review ({ed_wc} słów)"})
                        
                        # v59→v65 FIX: Keep article_text in HTML format for frontend.
                        # Create stripped copy ONLY for analysis tools (LanguageTool, grammar).
                        _analysis_text = _strip_html_for_analysis(article_text)
                        # v59 FIX: DISABLED post-editorial sentence_length_retry.
                        # Reason: sentence_length_retry sends text[:4000] to Haiku (~700 words).
                        # Full article is 2000-3000 words → Haiku only sees 30% → produces garbage.
                        # Per-batch retry (in batch loop) still works fine (batches are ~400 words).
                        # Post-editorial retry was the root cause of the degradation chain:
                        #   editorial 2336 words → Haiku chops to 8.8 avg → grammar 58 false positives → 37/100
                        try:
                            sl_post = check_sentence_length(_analysis_text)
                            if sl_post["needs_retry"]:
                                yield emit("log", {"msg": f"ℹ️ Post-editorial: śr. {sl_post['avg_len']} słów/zdanie (skip retry — per-batch retry wystarczy)"})
                        except Exception as _sl_err:
                            yield emit("log", {"msg": f"⚠️ Post-editorial sentence check error: {str(_sl_err)[:60]}"})

                        # Fix #64: Post-editorial anaphora check na całym artykule
                        # Analysis tools need stripped text (h2: format), but final article stays HTML.
                        try:
                            _an_final = check_anaphora(_analysis_text, main_entity=main_keyword)
                            if _an_final["needs_fix"]:
                                yield emit("log", {"msg": f"🔁 Post-editorial anaphora: {_an_final['anaphora_count']}× seria — naprawiam..."})
                                _an_fixed = anaphora_retry(_analysis_text, main_entity=main_keyword, h2="cały artykuł")
                                _an_check = check_anaphora(_an_fixed, main_entity=main_keyword)
                                if len(_an_fixed) > 100:
                                    _analysis_text = _an_fixed
                                    article_text = _clean_batch_text(_an_fixed)  # back to HTML
                                    remaining_runs = _an_check["anaphora_count"]
                                    if remaining_runs == 0:
                                        yield emit("log", {"msg": "✅ Post-editorial anaphora — pełna korekta"})
                                    else:
                                        yield emit("log", {"msg": f"✅ Post-editorial anaphora — {remaining_runs}× pozostało (czyszczenie częściowe)"})
                        except Exception as _an_err:
                            yield emit("log", {"msg": f"⚠️ Post-editorial anaphora error: {str(_an_err)[:60]}"})

                        # v55.1 Fix A: Grammar auto-fix AFTER all post-editorial processing
                        try:
                            from grammar_checker import auto_fix as grammar_auto_fix
                            gfix = grammar_auto_fix(_analysis_text)
                            if gfix["grammar_fixes"] > 0 or gfix["phrases_removed"]:
                                _analysis_text = gfix["corrected"]
                                article_text = _clean_batch_text(gfix["corrected"])  # back to HTML
                                yield emit("log", {"msg": f"✅ Grammar auto-fix: {gfix['grammar_fixes']} poprawek, {len(gfix['phrases_removed'])} fraz AI usunięto"})
                        except ImportError:
                            pass
                        except Exception as _gfix_err:
                            yield emit("log", {"msg": f"⚠️ Grammar auto-fix error: {str(_gfix_err)[:60]}"})

                        # v67: YMYL citation cleanup — fix common LLM hallucinations in references
                        if is_legal or is_medical:
                            try:
                                _cit_fixes = _fix_citation_hallucinations(article_text)
                                if _cit_fixes["fixes"]:
                                    article_text = _cit_fixes["text"]
                                    _analysis_text = _strip_html_for_analysis(article_text) if article_text else article_text
                                    yield emit("log", {"msg": f"🔬 Citation cleanup: {len(_cit_fixes['fixes'])} poprawek ({', '.join(_cit_fixes['fixes'][:3])})"})
                            except Exception as _cit_err:
                                yield emit("log", {"msg": f"⚠️ Citation cleanup error: {str(_cit_err)[:60]}"})

            # v56: Safety net — normalize HTML tags before final emit
            article_text = _normalize_html_tags(article_text)

            yield emit("article", {
                "text": article_text,
                "word_count": len(article_text.split()) if article_text else 0,
                "h2_count": stats.get("h2_count", 0),
                "h3_count": stats.get("h3_count", 0),
                "coverage": coverage,
                "density": (full.get("density") or {})
            })

            # ═══ ENTITY SALIENCE: Google NLP API validation ═══
            full_text = article_text
            _full_text_clean = _strip_html_for_analysis(full_text) if full_text else full_text
            salience_result = {}
            nlp_entities = []
            subject_pos = {}
            sal_score = None
            is_dominant = None
            st_score = None
            
            # Subject position analysis: always runs (free, no API)
            if full_text:
                try:
                    # v58: pass top-3 secondary entities for panel display
                    _sec_kws = []
                    _topical = s1.get("topical_entities") or {}
                    _sec_raw = _topical.get("secondary_entities") or []
                    if isinstance(_sec_raw, list):
                        for _se in _sec_raw[:3]:
                            if isinstance(_se, dict):
                                _sec_kws.append(_se.get("name") or _se.get("entity") or "")
                            elif isinstance(_se, str):
                                _sec_kws.append(_se)
                    _sec_kws = [s for s in _sec_kws if s and s.lower() != main_keyword.lower()][:3]
                    subject_pos = analyze_subject_position(_full_text_clean, main_keyword, secondary_keywords=_sec_kws or None)
                    sp_score = subject_pos.get("score", 0)
                    sr = subject_pos.get("subject_ratio", 0)
                    yield emit("log", {"msg": (
                        f"📐 Subject Position: score {sp_score}/100 | "
                        f"podmiot: {subject_pos.get('subject_position', 0)}/{subject_pos.get('sentences_with_entity', 0)} zdań ({sr:.0%}) | "
                        f"H2: {subject_pos.get('h2_entity_count', 0)} | "
                        f"1. zdanie: {'✅' if subject_pos.get('first_sentence_has_entity') else '❌'}"
                    )})
                except Exception as sp_err:
                    logger.warning(f"Subject position analysis failed: {sp_err}")

            # ═══ ANTI-FRANKENSTEIN: Style consistency analysis (free, always runs) ═══
            style_metrics = {}
            if full_text:
                try:
                    style_metrics = analyze_style_consistency(_full_text_clean)
                    st_score = style_metrics.get("score", 0)
                    yield emit("log", {"msg": (
                        f"🎭 Anti-Frankenstein: score {st_score}/100 | "
                        f"CV zdań: {style_metrics.get('cv_sentences', 0):.2f} | "
                        f"passive: {style_metrics.get('passive_ratio', 0):.0%} | "
                        f"śr. zdanie: {style_metrics.get('avg_sentence_length', 0):.0f} słów"
                    )})
                    yield emit("style_analysis", {
                        "score": st_score,
                        "sentence_count": style_metrics.get("sentence_count", 0),
                        "paragraph_count": style_metrics.get("paragraph_count", 0),
                        "avg_sentence_length": style_metrics.get("avg_sentence_length", 0),
                        "cv_sentences": style_metrics.get("cv_sentences", 0),
                        "avg_paragraph_length": style_metrics.get("avg_paragraph_length", 0),
                        "cv_paragraphs": style_metrics.get("cv_paragraphs", 0),
                        "passive_ratio": style_metrics.get("passive_ratio", 0),
                        "transition_ratio": style_metrics.get("transition_ratio", 0),
                        "repetition_ratio": style_metrics.get("repetition_ratio", 0),
                        "issues": style_metrics.get("issues", []),
                    })
                except Exception as style_err:
                    logger.warning(f"Style analysis failed: {style_err}")

            # ═══ POLISH NLP VALIDATOR: NKJP corpus norms check (free, always runs) ═══
            polish_nlp = {}
            if full_text and POLISH_NLP_AVAILABLE:
                try:
                    polish_nlp = validate_polish_text(_full_text_clean)
                    pn_score = polish_nlp.get("score", 0)
                    m = polish_nlp.get("metrics", {})
                    yield emit("log", {"msg": (
                        f"🇵🇱 Polish NLP: score {pn_score}/100 | "
                        f"śr. wyraz: {m.get('avg_word_length', 0):.1f} zn | "
                        f"śr. zdanie: {m.get('avg_sentence_length', 0):.0f} słów | "
                        f"diakrytyki: {m.get('diacritics_pct', 0):.1f}% | "
                        f"FOG-PL: {m.get('fog_pl', 0):.0f} | "
                        f"przecinki: {m.get('comma_conjunction_ratio', 0):.0%}"
                    )})
                    # Log issues
                    issues = polish_nlp.get("issues", [])
                    if issues:
                        yield emit("log", {"msg": f"   ⚠️ Issues: {' | '.join(issues[:3])}"})
                    # Log collocation errors
                    coll_issues = polish_nlp.get("collocation_issues", [])
                    if coll_issues:
                        for ci in coll_issues[:3]:
                            yield emit("log", {"msg": f"   📝 Kolokacja: \"{ci['wrong']}\" → \"{ci['correct']}\" ({ci['count']}×)"})
                    # Emit to dashboard
                    yield emit("polish_nlp", {
                        "score": pn_score,
                        "avg_word_length": m.get("avg_word_length", 0),
                        "avg_sentence_length": m.get("avg_sentence_length", 0),
                        "diacritics_pct": m.get("diacritics_pct", 0),
                        "vowel_pct": m.get("vowel_pct", 0),
                        "fog_pl": m.get("fog_pl", 0),
                        "comma_conjunction_ratio": m.get("comma_conjunction_ratio", 0),
                        "sentence_cv": m.get("sentence_length_cv", 0),
                        "collocation_errors": m.get("collocation_errors", 0),
                        "hapax_ratio": m.get("hapax_ratio", 0),
                        "type_token_ratio": m.get("type_token_ratio", 0),
                        "issues": issues,
                        "recommendations": polish_nlp.get("recommendations", []),
                    })
                except Exception as pnlp_err:
                    logger.warning(f"Polish NLP validation failed: {pnlp_err}")

            # ═══ LANGUAGETOOL: Corpus-based grammar/collocation/punctuation check ═══
            lt_result = {}
            if full_text and LANGUAGETOOL_AVAILABLE:
                try:
                    # v59: Strip HTML tags before LanguageTool — <p> tags cause 49 false "typos"
                    _lt_clean = _strip_html_for_analysis(full_text)
                    lt_result = lt_check_text(_lt_clean)
                    lt_score = lt_result.get("score", 0)
                    cats = lt_result.get("categories", {})
                    available = lt_result.get("api_available", False)
                    if available:
                        yield emit("log", {"msg": (
                            f"🔍 LanguageTool: score {lt_score}/100 | "
                            f"gramatyka: {cats.get('GRAMMAR', 0)} | "
                            f"kolokacje: {cats.get('COLLOCATIONS', 0)} | "
                            f"interpunkcja: {cats.get('PUNCTUATION', 0)} | "
                            f"styl: {cats.get('STYLE', 0) + cats.get('REDUNDANCY', 0)} | "
                            f"literówki: {cats.get('TYPOS', 0)}"
                        )})
                        # Log top issues
                        for issue in lt_result.get("issues", [])[:5]:
                            yield emit("log", {"msg": (
                                f"   📝 [{issue['category_name']}] {issue['message'][:80]}"
                                + (f" → {', '.join(issue['replacements'][:2])}" if issue.get('replacements') else "")
                            )})
                        # Emit to dashboard
                        yield emit("languagetool", {
                            "score": lt_score,
                            "total_issues": lt_result.get("total_issues", 0),
                            "categories": cats,
                            "collocation_issues": lt_result.get("collocation_issues", []),
                            "grammar_issues": lt_result.get("grammar_issues", []),
                            "punctuation_issues": lt_result.get("punctuation_issues", []),
                            "style_issues": lt_result.get("style_issues", []),
                        })
                    else:
                        yield emit("log", {"msg": "⚠️ LanguageTool API niedostępne, pominięto sprawdzanie"})
                except Exception as lt_err:
                    logger.warning(f"LanguageTool check failed: {lt_err}")

            # v55.1 Fix D: Deterministic YMYL disclaimer BEFORE scoring
            # Export (HTML/DOCX) adds disclaimer during export, but scoring happens before export.
            # Add it now so analyze_ymyl_references sees it and scores disclaimer_present: True.
            if full_text and is_medical and "zastrzeżenie" not in full_text.lower():
                _disclaimer = (
                    "\n\n<p><strong>Zastrzeżenie medyczne:</strong> Niniejszy artykuł ma charakter wyłącznie informacyjny "
                    "i edukacyjny. Nie stanowi porady medycznej ani nie zastępuje konsultacji "
                    "z lekarzem lub innym wykwalifikowanym specjalistą.</p>"
                )
                article_text = article_text + _disclaimer if article_text else article_text
                full_text = full_text + _disclaimer if full_text else full_text
                yield emit("log", {"msg": "🏥 Dodano disclaimer medyczny (deterministyczny, YMYL=zdrowie)"})
            elif full_text and is_legal and "zastrzeżenie" not in full_text.lower():
                _disclaimer = (
                    "\n\n<p><strong>Zastrzeżenie prawne:</strong> Niniejszy artykuł ma charakter wyłącznie informacyjny "
                    "i nie stanowi porady prawnej. W indywidualnych sprawach zalecamy konsultację "
                    "z wykwalifikowanym prawnikiem.</p>"
                )
                article_text = article_text + _disclaimer if article_text else article_text
                full_text = full_text + _disclaimer if full_text else full_text
                yield emit("log", {"msg": "⚖️ Dodano disclaimer prawny (deterministyczny, YMYL=prawo)"})

            # ═══ YMYL INTELLIGENCE: Analyze legal/medical references in text ═══
            if full_text and (is_legal or is_medical):
                try:
                    ymyl_refs = analyze_ymyl_references(full_text, legal_context, medical_context)
                    
                    if is_legal:
                        lr = ymyl_refs.get("legal", {})
                        yield emit("log", {"msg": (
                            f"⚖️ YMYL Legal: score {lr.get('score', 0)}/100 | "
                            f"akty: {len(lr.get('acts_found', []))} | "
                            f"orzeczenia: {len(lr.get('judgments_found', []))} | "
                            f"art.: {len(lr.get('articles_cited', []))} | "
                            f"disclaimer: {'✅' if lr.get('disclaimer_present') else '❌'}"
                        )})
                    
                    if is_medical:
                        mr = ymyl_refs.get("medical", {})
                        yield emit("log", {"msg": (
                            f"🏥 YMYL Medical: score {mr.get('score', 0)}/100 | "
                            f"PMID: {len(mr.get('pmids_found', []))} | "
                            f"badania: {len(mr.get('studies_referenced', []))} | "
                            f"instytucje: {len(mr.get('institutions_found', []))} | "
                            f"disclaimer: {'✅' if mr.get('disclaimer_present') else '❌'}"
                        )})
                    
                    yield emit("ymyl_analysis", ymyl_refs)
                except Exception as ymyl_err:
                    logger.warning(f"YMYL analysis failed: {ymyl_err}")
            
            # ═══ SEMANTIC DISTANCE: Article vs Competitor data ═══
            # (must run before salience — salience block reads semantic_dist_result)
            semantic_dist_result = {"enabled": False, "score": 0}
            if full_text:
                try:
                    yield emit("log", {"msg": "📐 Semantic Distance: porównanie artykułu z konkurencją..."})
                    semantic_dist_result = _compute_semantic_distance(
                        full_text=full_text,
                        clean_semantic_kp=clean_semantic_kp,
                        clean_entities=clean_entities,
                        concept_entities=concept_entities,
                        clean_must_mention=clean_must_mention,
                        clean_ngrams=clean_ngrams,
                        nlp_entities=nlp_entities,
                    )
                    sem_score = semantic_dist_result["score"]
                    yield emit("log", {"msg": (
                        f"📐 Semantic Distance: {sem_score}/100 | "
                        f"KP: {semantic_dist_result['keyphrases_found']}/{semantic_dist_result['keyphrases_total']} | "
                        f"Entity: {round(semantic_dist_result['entity_overlap']*100)}% | "
                        f"Must-mention: {round(semantic_dist_result['must_mention_pct']*100)}%"
                    )})
                    yield emit("semantic_distance", semantic_dist_result)
                except Exception as sd_err:
                    logger.warning(f"Semantic distance calculation failed: {sd_err}")
                    yield emit("log", {"msg": f"⚠️ Semantic distance error: {str(sd_err)[:80]}"})
                
                # v67: Enhanced semantic analysis for Content Editorial
                try:
                    sem_analysis = _compute_semantic_analysis(
                        full_text=_full_text_clean or full_text,
                        h2_structure=h2_structure,
                        clean_semantic_kp=clean_semantic_kp,
                        clean_entities=clean_entities,
                        concept_entities=concept_entities,
                        clean_must_mention=clean_must_mention,
                        clean_ngrams=clean_ngrams,
                        competitor_h2_patterns=clean_h2_patterns,
                        recommended_length=_target_length,
                    )
                    if sem_analysis.get("enabled"):
                        _lp_msg = ""
                        if sem_analysis.get("length_penalty_applied"):
                            _lp_msg = f" | ⚠️ length penalty (ratio {sem_analysis.get('length_ratio', '?')}x)"
                        yield emit("log", {"msg": (
                            f"🔬 SEO Similarity: {sem_analysis['composite_score']}/100 | "
                            f"Terms: {sem_analysis['terms_present']}/{sem_analysis['term_pool_size']} | "
                            f"Entity: {sem_analysis['entity_coverage_pct']}% | "
                            f"H2 sections: {len(sem_analysis.get('h2_heatmap', []))}{_lp_msg}"
                        )})
                        yield emit("semantic_analysis", sem_analysis)
                except Exception as sa_err:
                    logger.warning(f"Semantic analysis failed: {sa_err}")
                    yield emit("log", {"msg": f"⚠️ Semantic analysis error: {str(sa_err)[:80]}"})

            # v55.1 Fix C: Polish — skip Google NLP (returns 400), use entity coverage score
            # System is Polish-only; Google NLP returns 400 for pl, spaCy fallback returns 404
            if full_text:
                # Compute salience from entity coverage (semantic_dist already has this data)
                _ent_cov = semantic_dist_result.get("entity_overlap", 0) if semantic_dist_result.get("enabled") else 0
                _must_cov = semantic_dist_result.get("must_mention_pct", 0) if semantic_dist_result.get("enabled") else 0
                sal_score = min(100, int((_ent_cov * 60) + (_must_cov * 40)))
                is_dominant = _ent_cov >= 0.8
                yield emit("log", {"msg": f"🔬 Entity Salience (PL): score {sal_score}/100 (entity_cov={_ent_cov:.0%}, must_mention={_must_cov:.0%}) [Google NLP nie obsługuje polskiego]"})
                yield emit("entity_salience", {
                    "enabled": True,
                    "score": sal_score,
                    "engine": "entity_coverage_pl",
                    "main_keyword": main_keyword,
                    "main_salience": round(_ent_cov, 4),
                    "is_dominant": is_dominant,
                    "top_entity": None,
                    "entities": [],
                    "issues": [] if sal_score >= 60 else ["Pokrycie encji tematycznych poniżej 60%"],
                    "recommendations": [],
                    "subject_position": subject_pos,
                })
            elif full_text and is_salience_available():
                yield emit("log", {"msg": "🔬 Entity Salience: analiza artykułu przez Google NLP API..."})
                try:
                    salience_result = check_entity_salience(full_text, main_keyword)
                    nlp_entities = salience_result.get("entities", [])

                    main_sal = salience_result.get("main_salience", 0)
                    is_dominant = salience_result.get("is_main_dominant", False)
                    sal_score = salience_result.get("score", 0)
                    top_ent = salience_result.get("top_entity") or {}

                    top_name = top_ent.get("name", "?")
                    top_sal = top_ent.get("salience", 0)
                    dom_str = "DOMINUJE" if is_dominant else f"Dominuje: {top_name} ({top_sal:.2f})"
                    yield emit("log", {"msg": f"Salience: {main_keyword} = {main_sal:.2f} | {dom_str} | Score: {sal_score}/100"})

                    yield emit("entity_salience", {
                        "enabled": True,
                        "score": sal_score,
                        "main_keyword": main_keyword,
                        "main_salience": round(main_sal, 4),
                        "is_dominant": is_dominant,
                        "top_entity": {
                            "name": top_ent.get("name", ""),
                            "salience": round(top_ent.get("salience", 0), 4),
                            "type": top_ent.get("type", ""),
                        } if top_ent else None,
                        "entities": [
                            {"name": e["name"], "salience": round(e["salience"], 4),
                             "type": e["type"], "has_wikipedia": bool(e.get("wikipedia_url")),
                             "has_kg": bool(e.get("mid"))}
                            for e in nlp_entities[:12]
                        ],
                        "issues": salience_result.get("issues", []),
                        "recommendations": salience_result.get("recommendations", []),
                        "subject_position": subject_pos,
                    })
                except Exception as sal_err:
                    logger.warning(f"Entity salience check failed: {sal_err}")
                    yield emit("log", {"msg": f"⚠️ Salience check error: {str(sal_err)[:80]}"})
            elif full_text:
                yield emit("entity_salience", {
                    "enabled": False,
                    "score": None,
                    "message": "Ustaw GOOGLE_NLP_API_KEY aby włączyć walidację salience",
                    "subject_position": subject_pos,
                })

            # ═══ SCHEMA.ORG JSON-LD: Generate from real NLP entities ═══
            try:
                article_schema = generate_article_schema(
                    main_keyword=main_keyword,
                    entities=nlp_entities,
                    date_published=datetime.now().strftime("%Y-%m-%d"),
                    date_modified=datetime.now().strftime("%Y-%m-%d"),
                    h2_list=h2_structure,
                )
                schema_html = schema_to_html(article_schema)
                
                yield emit("schema_org", {
                    "json_ld": article_schema,
                    "html": schema_html,
                    "entity_count": len(nlp_entities),
                    "has_main_entity": bool(article_schema.get("@graph", [{}])[0].get("about")),
                    "mentions_count": len(article_schema.get("@graph", [{}])[0].get("mentions", [])),
                })
                yield emit("log", {"msg": f"📋 Schema.org: Article + {len(article_schema.get('@graph', [{}])[0].get('mentions', []))} mentions generated"})
            except Exception as schema_err:
                logger.warning(f"Schema generation error: {schema_err}")

            # ═══ TOPICAL MAP: Entity-based content architecture ═══
            try:
                topical_map = generate_topical_map(
                    main_keyword=main_keyword,
                    s1_data=s1,
                    nlp_entities=nlp_entities,
                )
                clusters = topical_map.get("clusters", [])
                if clusters:
                    yield emit("topical_map", {
                        "pillar": topical_map["pillar"],
                        "clusters": clusters[:12],
                        "internal_links": topical_map.get("internal_links", [])[:20],
                        "total_clusters": len(clusters),
                    })
                    yield emit("log", {"msg": f"🗺️ Topical Map: {len(clusters)} klastrów treści wokół \"{main_keyword}\""})
            except Exception as tm_err:
                logger.warning(f"Topical map error: {tm_err}")

        # ═══ EVALUATION SUMMARY: At-a-glance article assessment ═══
        try:
            _sem_score = semantic_dist_result.get("score", 0) if semantic_dist_result.get("enabled") else None
            _sal_score = sal_score  # initialized to None, set if salience check ran
            _st_score = st_score   # initialized to None, set if style analysis ran
            _q_score = final_score if isinstance(final_score, (int, float)) else None
            _word_count = len(full_text.split()) if full_text else 0
            _rec_length = s1.get("recommended_length", 3000) if s1 else 3000

            # Salience wykluczona z oceny — jest pochodna Semantic Distance
            # (entity_overlap*60 + must_mention*40) i podwojnie liczyloby te sama informacje
            # Wagi: Quality 45% + Semantic 35% + Style 20%
            grade = _compute_grade(_q_score, None, _sem_score, _st_score)
            yield emit("evaluation_summary", {
                "quality_score": _q_score,
                "salience_score": _sal_score,
                "salience_dominant": is_dominant,
                "semantic_distance_score": _sem_score,
                "style_score": _st_score,
                "word_count": _word_count,
                "recommended_length": _rec_length,
                "keyphrase_coverage_pct": round(semantic_dist_result.get("keyphrase_coverage", 0) * 100) if semantic_dist_result.get("enabled") else None,
                "must_mention_coverage_pct": round(semantic_dist_result.get("must_mention_pct", 0) * 100) if semantic_dist_result.get("enabled") else None,
                "entity_coverage_pct": round(semantic_dist_result.get("entity_overlap", 0) * 100) if semantic_dist_result.get("enabled") else None,
                "grade": grade,
                "grade_weights": {"quality": 45, "semantic": 35, "style": 20},
            })
            yield emit("log", {"msg": f"🎯 Ocena: {grade} | Quality: {_q_score} (45%) | Semantic: {_sem_score} (35%) | Style: {_st_score} (20%) | Salience: {_sal_score} [info]"})
        except Exception as eval_err:
            logger.warning(f"Evaluation summary failed: {eval_err}")

        # ═══ v2.4: ENTITY INTELLIGENCE PANEL — real metrics only ═══
        try:
            _ei_text = full_text or article_text or ""
            if _ei_text and len(_ei_text) > 200:
                yield emit("log", {"msg": "🧬 Entity Intelligence: analiza encji i naturalności tekstu..."})

                # Safe access to variables from earlier blocks
                try:
                    _style_m = style_metrics
                except (NameError, UnboundLocalError):
                    _style_m = {}
                try:
                    _st_sc = st_score
                except (NameError, UnboundLocalError):
                    _st_sc = None

                # A. Polish NLP stats (NKJP-based)
                _pl_stats = _compute_polish_text_stats(_ei_text)

                # B. Entity placement: main keyword in text
                _ei_lower = _ei_text.lower()
                _kw_lower = main_keyword.lower().strip()
                _kw_mentions = _ei_lower.count(_kw_lower) if _kw_lower else 0
                _word_count_ei = len(_ei_text.split())
                _entity_density = round(_kw_mentions / max(_word_count_ei, 1) * 1000, 1)  # per 1000 words

                # First sentence check
                import re as _re_ei
                _first_sent = _re_ei.split(r'[.!?]', _ei_text, maxsplit=1)[0] if _ei_text else ""
                _kw_in_first_sent = _kw_lower in _first_sent.lower() if _kw_lower else False

                # H2 headings with main entity
                _h2_matches = _re_ei.findall(r'<h2[^>]*>(.*?)</h2>', _ei_text, _re_ei.IGNORECASE)
                _h2_with_entity = sum(1 for h in _h2_matches if _kw_lower in h.lower())

                # C. Semantic distance data (already computed)
                try:
                    _sd = semantic_dist_result if semantic_dist_result.get("enabled") else {}
                except (NameError, UnboundLocalError):
                    _sd = {}

                # D. Subject position data (already computed)
                try:
                    _sp = subject_pos if isinstance(subject_pos, dict) else {}
                except (NameError, UnboundLocalError):
                    _sp = {}

                # E. Co-occurrence pairs check — safe access
                _cooc_data = []
                try:
                    _cooc_pairs = backend_cooccurrence_pairs
                except (NameError, UnboundLocalError):
                    _cooc_pairs = []
                for pair in (_cooc_pairs or [])[:10]:
                    try:
                        if isinstance(pair, dict):
                            e1 = str(pair.get("entity_1", pair.get("e1", ""))).lower()
                            e2 = str(pair.get("entity_2", pair.get("e2", ""))).lower()
                        elif isinstance(pair, (list, tuple)) and len(pair) >= 2:
                            e1, e2 = str(pair[0]).lower(), str(pair[1]).lower()
                        else:
                            continue
                        if e1 and e2:
                            found = e1 in _ei_lower and e2 in _ei_lower
                            _cooc_data.append({"e1": e1[:30], "e2": e2[:30], "found": found})
                    except Exception:
                        pass

                _cooc_found = sum(1 for c in _cooc_data if c["found"])
                _cooc_total = len(_cooc_data)

                # F. Entity gaps (from S1) — safe access
                _entity_gaps_list = []
                try:
                    try:
                        _s1_ref = s1 if s1 else {}
                    except (NameError, UnboundLocalError):
                        _s1_ref = {}
                    _eg_raw = _s1_ref.get("entity_gaps", []) if isinstance(_s1_ref, dict) else []
                    for gap in (_eg_raw or [])[:8]:
                        if isinstance(gap, dict):
                            _g_name = gap.get("entity", gap.get("item", gap.get("name", "")))
                            _g_prio = gap.get("priority", "medium")
                            if _g_name:
                                _in_art = str(_g_name).lower() in _ei_lower
                                _entity_gaps_list.append({"entity": str(_g_name)[:40], "priority": _g_prio, "covered": _in_art})
                except Exception:
                    pass

                yield emit("entity_intelligence", {
                    # A. Polish NLP naturalness
                    "polish_nlp": _pl_stats,
                    # B. Entity placement
                    "placement": {
                        "main_keyword": main_keyword,
                        "mentions": _kw_mentions,
                        "density_per_1k": _entity_density,
                        "in_first_sentence": _kw_in_first_sent,
                        "h2_count": len(_h2_matches),
                        "h2_with_entity": _h2_with_entity,
                    },
                    # C. Semantic distance
                    "semantic_distance": {
                        "enabled": bool(_sd.get("enabled")),
                        "score": _sd.get("score"),
                        "keyphrase_coverage": round((_sd.get("keyphrase_coverage", 0)) * 100, 1),
                        "keyphrase_found": _sd.get("keyphrases_found", 0),
                        "keyphrase_total": _sd.get("keyphrases_total", 0),
                        "keyphrase_missing": _sd.get("keyphrases_missing_list", [])[:8],
                        "entity_overlap": round((_sd.get("entity_overlap", 0)) * 100, 1),
                        "entities_shared": _sd.get("entities_shared_list", [])[:10],
                        "entities_only_competitor": _sd.get("entities_only_competitor", [])[:8],
                        "must_mention_pct": round((_sd.get("must_mention_pct", 0)) * 100, 1),
                        "must_mention_found": _sd.get("must_mention_found", [])[:8],
                        "must_mention_missing": _sd.get("must_mention_missing", [])[:8],
                        "ngram_overlap": round((_sd.get("ngram_overlap", 0)) * 100, 1),
                    },
                    # D. Subject position
                    "subject_position": {
                        "score": _sp.get("score"),
                        "subject_ratio": round((_sp.get("subject_ratio", 0)) * 100, 1) if _sp.get("subject_ratio") else None,
                        "first_sentence_has_entity": _sp.get("first_sentence_has_entity"),
                        "h2_entity_count": _sp.get("h2_entity_count"),
                        "total_sentences": _sp.get("total_sentences"),
                        "sentences_with_entity": _sp.get("sentences_with_entity"),
                    },
                    # E. Co-occurrence
                    "cooccurrence": {
                        "found": _cooc_found,
                        "total": _cooc_total,
                        "pairs": _cooc_data[:8],
                    },
                    # F. Entity gaps
                    "entity_gaps": _entity_gaps_list[:8],
                    # G. Style consistency (Anti-Frankenstein data)
                    "style": {
                        "score": _st_sc if isinstance(_st_sc, (int, float)) else None,
                        "cv_sentences": _style_m.get("cv_sentences") if _style_m else None,
                        "cv_paragraphs": _style_m.get("cv_paragraphs") if _style_m else None,
                        "passive_ratio": _style_m.get("passive_ratio") if _style_m else None,
                        "transition_ratio": _style_m.get("transition_ratio") if _style_m else None,
                        "repetition_ratio": _style_m.get("repetition_ratio") if _style_m else None,
                        "avg_sentence_length": _style_m.get("avg_sentence_length") if _style_m else None,
                        "issues": (_style_m.get("issues") or [])[:5] if _style_m else [],
                    },
                    # H. Composite dimensions (0-100)
                    "dimensions": _compute_text_dimensions(_pl_stats, _style_m or {}),
                })
                yield emit("log", {"msg": f"🧬 Entity Intelligence: PL={_pl_stats.get('score', '?')}/100 | mentions={_kw_mentions} | cooc={_cooc_found}/{_cooc_total}"})
        except Exception as ei_err:
            logger.warning(f"Entity intelligence panel failed: {ei_err}")

        # ═══ v2.3: REDAKTOR NACZELNY — final expert review ═══
        try:
            _editor_article = article_text or full_text or ""
            if _editor_article and len(_editor_article) > 300:
                yield emit("log", {"msg": "📝 Redaktor Naczelny — recenzja ekspercka..."})
                yield emit("step", {"step": 11, "name": "Redaktor Naczelny", "status": "running"})

                editor_result = _editor_in_chief_review(
                    _editor_article, main_keyword, _detected_category
                )

                if editor_result.get("ran"):
                    _crit = editor_result.get("critical_count", 0)
                    _art = editor_result.get("artifact_count", 0)
                    _logic = editor_result.get("logic_count", 0)
                    _verdict = editor_result.get("verdict", "?")
                    _comment = editor_result.get("comment", "")

                    yield emit("editor_review", {
                        "verdict": _verdict,
                        "comment": _comment,
                        "critical_count": _crit,
                        "artifact_count": _art,
                        "logic_count": _logic,
                        "critical": editor_result.get("critical", []),
                        "artifacts": editor_result.get("artifacts", []),
                        "logic": editor_result.get("logic", []),
                        "auto_fixed": editor_result.get("fixed_text") is not None,
                        "tokens": editor_result.get("input_tokens", 0) + editor_result.get("output_tokens", 0),
                    })
                    # v67: Track cost
                    cost_tracker.record(job_id, _get_anthropic_model(),
                        editor_result.get("input_tokens", 0),
                        editor_result.get("output_tokens", 0),
                        step="editor_in_chief")

                    _status_emoji = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(_verdict, "❓")
                    yield emit("log", {"msg": f"{_status_emoji} Redaktor: {_verdict} | {_crit} krytycznych, {_art} artefaktów, {_logic} logiki | {_comment[:120]}"})

                    # Auto-fix: replace article if critical errors were found and fixed
                    if editor_result.get("fixed_text"):
                        _fixed = _clean_batch_text(editor_result["fixed_text"])
                        _fixed = _normalize_html_tags(_fixed)

                        # Validate fix didn't corrupt text
                        _orig_wc = len(_editor_article.split())
                        _fix_wc = len(_fixed.split())
                        if _fix_wc >= _orig_wc * 0.85 and _fix_wc <= _orig_wc * 1.15:
                            article_text = _fixed
                            full_text = _fixed
                            yield emit("article_update", {"full_text": _fixed})
                            yield emit("log", {"msg": f"🔧 Auto-fix: {_crit} błędów poprawionych ({_orig_wc}→{_fix_wc} słów)"})

                            # Re-submit fixed article to Brajn
                            try:
                                brajen_call("post", f"/api/project/{project_id}/batch_simple", {"text": _fixed})
                                yield emit("log", {"msg": "📤 Poprawiony artykuł przesłany do Brajn"})
                            except Exception:
                                pass
                        else:
                            yield emit("log", {"msg": f"⚠️ Auto-fix odrzucony: {_fix_wc} słów vs {_orig_wc} oryginał (>15% różnicy)"})

                    yield emit("step", {"step": 11, "name": "Redaktor Naczelny", "status": "done",
                                        "detail": f"{_verdict} | {_crit} krytycznych"})
                else:
                    _reason = editor_result.get("reason", editor_result.get("error", "?"))
                    yield emit("log", {"msg": f"⚠️ Redaktor Naczelny pominięty: {_reason}"})
                    yield emit("step", {"step": 11, "name": "Redaktor Naczelny", "status": "warning",
                                        "detail": f"Pominięty: {_reason[:60]}"})
        except Exception as editor_err:
            logger.warning(f"Editor-in-chief review failed: {editor_err}")
            yield emit("log", {"msg": f"⚠️ Redaktor Naczelny error: {str(editor_err)[:100]}"})

        # Export HTML
        import tempfile as _tempfile
        export_result = brajen_call("get", f"/api/project/{project_id}/export/html")
        if export_result["ok"]:
            if export_result.get("binary"):
                _fd, export_path = _tempfile.mkstemp(suffix=".html", prefix="brajen_")
                os.close(_fd)
                with open(export_path, "wb") as f:
                    f.write(export_result["content"])
                job["export_html"] = export_path
            else:
                content = export_result["data"] if isinstance(export_result["data"], str) else json.dumps(export_result["data"])
                _fd, export_path = _tempfile.mkstemp(suffix=".html", prefix="brajen_")
                os.close(_fd)
                with open(export_path, "w", encoding="utf-8") as f:
                    f.write(content)
                job["export_html"] = export_path

        # Export DOCX
        export_docx = brajen_call("get", f"/api/project/{project_id}/export/docx")
        if export_docx["ok"] and export_docx.get("binary"):
            _fd, export_path = _tempfile.mkstemp(suffix=".docx", prefix="brajen_")
            os.close(_fd)
            with open(export_path, "wb") as f:
                f.write(export_docx["content"])
            job["export_docx"] = export_path

        step_done(11)
        yield emit("step", {"step": 12, "name": "Export", "status": "done",
                            "detail": "HTML + DOCX gotowe"})

        # ─── DONE ───
        total_elapsed = round(time.time() - workflow_start, 1)
        _circuit_breaker_reset(job_id)  # FIX: reset circuit breaker po zakończeniu joba
        job["status"] = "done"  # FIX: ustaw finalny status
        yield emit("log", {"msg": f"⏱️ Workflow zakończony w {total_elapsed}s"})

        # v67: Readiness Checklist — deterministic, 0 API calls
        try:
            _wc = stats.get("word_count", 0) if full_result["ok"] else 0
            _rec_len = s1.get("recommended_length", 3000) if s1 else 3000
            _word_ok = _wc >= _rec_len * 0.75 and _wc <= _rec_len * 1.5

            try: _final_ok = isinstance(final_score, (int, float)) and final_score >= 60
            except NameError: _final_ok = False; final_score = None
            try: _ed_ok = isinstance(editorial_score, (int, float)) and editorial_score >= 5
            except NameError: _ed_ok = False; editorial_score = None
            try: _sal_ok = is_dominant is True or sal_score is None
            except NameError: _sal_ok = True; sal_score = None; is_dominant = None
            try: _lt_ok = bool(lt_result) and lt_result.get("api_available") and lt_result.get("score", 0) >= 60
            except NameError: _lt_ok = False; lt_result = {}
            try: _style_ok = isinstance(st_score, (int, float)) and st_score >= 50
            except NameError: _style_ok = False; st_score = None
            try: _sem_ok = semantic_dist_result.get("enabled") and semantic_dist_result.get("score", 0) >= 50
            except NameError: _sem_ok = False; semantic_dist_result = {}
            try: _is_ymyl = is_ymyl
            except NameError: _is_ymyl = False
            try: _discl = disclaimer_added
            except NameError: _discl = False
            _ymyl_ok = not _is_ymyl or bool(_discl)

            checks = [
                {"ok": _word_ok, "label": "Długość tekstu", "detail": f"{_wc}/{_rec_len} słów"},
                {"ok": _final_ok, "label": "Final Review ≥ 60", "detail": f"{final_score}/100" if isinstance(final_score, (int, float)) else "brak"},
                {"ok": _ed_ok, "label": "Editorial Review ≥ 5", "detail": f"{editorial_score}/10" if isinstance(editorial_score, (int, float)) else "brak"},
                {"ok": _sal_ok, "label": "Entity Salience", "detail": "dominant" if is_dominant else ("brak API" if sal_score is None else f"{sal_score}/100")},
                {"ok": _lt_ok, "label": "LanguageTool ≥ 60", "detail": f"{lt_result.get('score', '?')}/100" if isinstance(lt_result, dict) and lt_result.get("api_available") else "niedostępne"},
                {"ok": _style_ok, "label": "Style score ≥ 50", "detail": f"{st_score}/100" if isinstance(st_score, (int, float)) else "brak"},
                {"ok": _sem_ok, "label": "Semantic Distance ≥ 50", "detail": f"{semantic_dist_result.get('score', '?')}/100" if isinstance(semantic_dist_result, dict) and semantic_dist_result.get("enabled") else "brak"},
                {"ok": _ymyl_ok, "label": "YMYL disclaimer", "detail": "dodane" if _discl else ("N/A" if not _is_ymyl else "BRAK!")},
            ]
            yield emit("readiness_checklist", {"checks": checks})
        except Exception as rc_err:
            logger.warning(f"Readiness checklist failed: {rc_err}")

        # v67: Cost summary
        _cost_sum = cost_tracker.get_job_summary(job_id)

        yield emit("done", {
            "project_id": project_id,
            "word_count": stats.get("word_count", 0) if full_result["ok"] else 0,
            "exports": {
                "html": bool(job.get("export_html")),
                "docx": bool(job.get("export_docx"))
            },
            "timing": {
                "total_seconds": total_elapsed,
                "steps": {str(k): v.get("elapsed", 0) for k, v in step_times.items()},
            },
            "cost_summary": _cost_sum,
        })

        # v68: Restore global model
        _clear_anthropic_model()

    except Exception as e:
        _clear_anthropic_model()  # v68: Restore on error too
        _circuit_breaker_reset(job_id)  # FIX: reset circuit breaker nawet przy błędzie
        job["status"] = "error"  # FIX: ustaw finalny status
        logger.exception(f"Workflow error: {e}")
        yield emit("workflow_error", {"step": 0, "msg": f"Unexpected error: {str(e)}"})


# ============================================================
# ARTICLE EDITOR: Chat + Inline editing with Claude
# ============================================================
@app.route("/api/edit", methods=["POST"])
@login_required
def edit_article():
    """Edit article via Claude based on user instruction."""
    data = request.json
    instruction = (data.get("instruction") or "").strip()
    article_text = (data.get("article_text") or "").strip()
    selected_text = (data.get("selected_text") or "").strip()
    job_id = data.get("job_id", "")

    if not instruction or not article_text:
        return jsonify({"error": "Brak instrukcji lub tekstu artykułu"}), 400

    if selected_text:
        system_prompt = (
            "Jesteś redaktorem artykułu SEO. Użytkownik zaznaczył fragment tekstu i chce go zmienić. "
            "Zwróć TYLKO poprawiony fragment, nie cały artykuł. "
            "Zachowaj formatowanie (h2:, h3: itd). Nie dodawaj komentarzy."
        )
        user_prompt = (
            f"CAŁY ARTYKUŁ (kontekst):\n{article_text[:6000]}\n\n"
            f"═══ ZAZNACZONY FRAGMENT ═══\n{selected_text}\n\n"
            f"═══ INSTRUKCJA ═══\n{instruction}\n\n"
            f"Zwróć TYLKO poprawiony fragment (zamiennik za zaznaczony tekst):"
        )
    else:
        system_prompt = (
            "Jesteś redaktorem artykułu SEO. Użytkownik prosi o zmianę w artykule. "
            "Zwróć CAŁY poprawiony artykuł z naniesionymi zmianami. "
            "Zachowaj formatowanie (h2:, h3: itd). Nie dodawaj komentarzy ani wyjaśnień. TYLKO tekst artykułu."
        )
        user_prompt = (
            f"ARTYKUŁ:\n{article_text}\n\n"
            f"═══ INSTRUKCJA ═══\n{instruction}\n\n"
            f"Zwróć poprawiony artykuł:"
        )

    try:
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"), max_retries=0)
        model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        
        # v50.7 FIX 48: Auto-retry on 429/529
        def _call():
            return client.messages.create(
                model=model, max_tokens=8000,
                messages=[{"role": "user", "content": user_prompt}],
                system=system_prompt
            )
        response = _llm_call_with_retry(_call)
        result_text = response.content[0].text.strip()
        return jsonify({
            "ok": True, "edited_text": result_text,
            "edit_type": "inline" if selected_text else "full",
            "model": model,
            "tokens_used": response.usage.input_tokens + response.usage.output_tokens
        })
    except Exception as e:
        logger.exception(f"Edit error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/validate", methods=["POST"])
@login_required
def validate_article():
    """Validate edited article via backend API."""
    data = request.json
    article_text = (data.get("article_text") or "").strip()
    job_id = data.get("job_id", "")
    if not article_text:
        return jsonify({"error": "Brak tekstu artykułu"}), 400
    job = active_jobs.get(job_id, {})
    project_id = job.get("project_id")
    if not project_id:
        return jsonify({"error": "Brak project_id, uruchom najpierw workflow"}), 400
    try:
        # v68 H7: validate_full_article endpoint doesn't exist — go straight to final_review
        fr = brajen_call("get", f"/api/project/{project_id}/final_review")
        if fr["ok"]:
            return jsonify({"ok": True, "validation": fr["data"]})
        return jsonify({"error": "Walidacja niedostępna"}), 500
    except Exception as e:
        logger.exception(f"Validate error: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================
# ROUTES
# ============================================================
@app.route("/")
@login_required
def index():
    return render_template("index.html", username=session.get("user", ""))


@app.route("/api/engines")
@login_required
def get_engines():
    """Return available AI engines and their models."""
    return jsonify({
        "engines": {
            "claude": {
                "available": bool(ANTHROPIC_API_KEY),
                "model": _get_anthropic_model(),
            },
            "openai": {
                "available": bool(OPENAI_API_KEY) and OPENAI_AVAILABLE,
                "model": OPENAI_MODEL,
            },
        },
        "default": "claude",
    })


@app.route("/api/start", methods=["POST"])
@login_required
def start_workflow():
    """Start workflow and return job_id."""
    data = request.json

    main_keyword = data.get("main_keyword", "").strip()
    if not main_keyword:
        return jsonify({"error": "Brak hasła głównego"}), 400

    mode = data.get("mode", "standard")
    h2_list = [h.strip() for h in (data.get("h2_structure") or []) if h.strip()]
    basic_terms = [t.strip() for t in (data.get("basic_terms") or []) if t.strip()]
    extended_terms = [t.strip() for t in (data.get("extended_terms") or []) if t.strip()]
    custom_instructions = (data.get("custom_instructions") or "").strip()
    engine = data.get("engine", "claude")  # "claude" or "openai"
    quality_tier = data.get("quality_tier", "ekonomiczny")  # "ekonomiczny" or "premium"
    voice_preset = (data.get("voice_preset") or "auto").strip() or "auto"
    openai_model_override = data.get("openai_model")  # per-session model override
    user_temperature = data.get("temperature")  # 0.0-1.0 or None
    if user_temperature is not None:
        user_temperature = max(0.0, min(1.0, float(user_temperature)))

    # Content type: "article" (default) or "category" (e-commerce category description)
    content_type = data.get("content_type", "article")
    category_data = None
    if content_type == "category":
        category_data = {
            "category_type": data.get("category_type", "subcategory"),
            "store_name": (data.get("store_name") or "").strip(),
            "store_description": (data.get("store_description") or "").strip(),
            "hierarchy": (data.get("category_hierarchy") or "").strip(),
            "products": (data.get("category_products") or "").strip(),
            "bestseller": (data.get("category_bestseller") or "").strip(),
            "price_range": (data.get("category_price_range") or "").strip(),
            "target_audience": (data.get("category_target") or "").strip(),
            "usp": (data.get("category_usp") or "").strip(),
            "brand_voice": (data.get("category_brand_voice") or "").strip(),
        }

    # H2 is now OPTIONAL : if empty, will be auto-generated from S1

    job_id = str(uuid.uuid4())[:8]

    # Cleanup old jobs to prevent memory leaks
    _cleanup_old_jobs()

    active_jobs[job_id] = {
        "main_keyword": main_keyword,
        "mode": mode,
        "engine": engine,
        "quality_tier": quality_tier,
        "voice_preset": voice_preset,
        "openai_model": openai_model_override,
        "temperature": user_temperature,
        "h2_structure": h2_list,
        "basic_terms": basic_terms,
        "extended_terms": extended_terms,
        "custom_instructions": custom_instructions,
        "content_type": content_type,
        "category_data": category_data,
        "status": "running",
        "created": datetime.now().isoformat(),
        "created_at": datetime.utcnow()
    }

    return jsonify({"job_id": job_id})


def stream_with_keepalive(generator_fn, keepalive_interval=15):
    """Run SSE generator in background thread, inject keepalive pings to prevent proxy timeouts."""
    q = queue.Queue()

    def run():
        try:
            for item in generator_fn():
                q.put(item)
        except Exception as e:
            q.put(f"event: error\ndata: {json.dumps({'msg': str(e)})}\n\n")
        finally:
            q.put(None)  # sentinel = stream finished

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    while True:
        try:
            item = q.get(timeout=keepalive_interval)
            if item is None:
                break
            yield item
        except queue.Empty:
            # No event for {keepalive_interval}s : send SSE comment to keep connection alive
            yield ": keepalive\n\n"


@app.route("/api/stream/<job_id>")
@login_required
def stream_workflow(job_id):
    """SSE endpoint for workflow progress with keepalive."""
    job = active_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    data = job

    # v67: basic_terms and extended_terms are stored in active_jobs from /api/start
    # No longer passed via URL query params (was causing 4260 > 4094 gunicorn error)
    def generate_with_terms():
        bt = data.get("basic_terms") or []
        et = data.get("extended_terms") or []
        yield from run_workflow_sse(
            job_id=job_id,
            main_keyword=data["main_keyword"],
            mode=data["mode"],
            h2_structure=data["h2_structure"],
            basic_terms=bt,
            extended_terms=et,
            engine=data.get("engine", "claude"),
            openai_model=data.get("openai_model"),
            temperature=data.get("temperature"),
            content_type=data.get("content_type", "article"),
            category_data=data.get("category_data"),
            voice_preset=data.get("voice_preset","auto"),
            quality_tier=data.get("quality_tier", "ekonomiczny")
        )

    return Response(
        stream_with_context(stream_with_keepalive(generate_with_terms, keepalive_interval=15)),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )


@app.route("/api/export/<job_id>/<fmt>")
@login_required
def download_export(job_id, fmt):
    """Download exported file."""
    job = active_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    # v68 M14: Validate fmt to prevent path injection
    if fmt not in ("html", "docx", "txt"):
        return jsonify({"error": "Invalid format"}), 400

    key = f"export_{fmt}"
    path = job.get(key)
    if not path or not os.path.exists(path):
        return jsonify({"error": f"Export {fmt} not available"}), 404

    mime = {
        "html": "text/html",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "txt": "text/plain"
    }.get(fmt, "application/octet-stream")

    return send_file(path, mimetype=mime, as_attachment=True,
                     download_name=f"article_{job_id}.{fmt}")


@app.route("/api/health")
def health():
    """Health check."""
    return jsonify({"status": "ok", "version": "67.0.0"})


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("DEBUG", "false").lower() == "true")
