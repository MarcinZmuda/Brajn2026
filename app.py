"""
BRAJEN SEO Web App v45.2.3
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
import threading
import queue
import gc
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, jsonify, Response,
    session, redirect, url_for, stream_with_context, send_file
)
import requests as http_requests
import anthropic

# Optional: OpenAI
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# ============================================================
# CONFIG
# ============================================================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "brajen-seo-secret-" + str(uuid.uuid4()))

BRAJEN_API = os.environ.get("BRAJEN_API_URL", "https://master-seo-api.onrender.com")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-6")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "brajen2024")
APP_USERNAME = os.environ.get("APP_USERNAME", "brajen")

REQUEST_TIMEOUT = 120
EDITORIAL_TIMEOUT = 300  # Editorial review needs more time
MAX_RETRIES = 3
RETRY_DELAYS = [5, 15, 30]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Store active jobs in memory (for SSE) — with cleanup
active_jobs = {}
_active_workflow_count = 0
_jobs_lock = threading.Lock()
MAX_CONCURRENT_WORKFLOWS = 1  # Prevent OOM from parallel workflows

# Singleton Anthropic client — reuse connection pool instead of creating new client per call
_claude_client = None
def get_claude_client():
    global _claude_client
    if _claude_client is None:
        _claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _claude_client


def _cleanup_old_jobs():
    """Remove completed/stale jobs older than 10 minutes to prevent memory leak."""
    cutoff = (datetime.now() - timedelta(minutes=10)).isoformat()
    stale = [jid for jid, j in active_jobs.items()
             if j.get("status") in ("done", "error") or j.get("created", "") < cutoff]
    for jid in stale:
        # Clean up /tmp export files
        j = active_jobs[jid]
        for k in ("export_html", "export_docx"):
            path = j.get(k)
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
        del active_jobs[jid]
    if stale:
        gc.collect()
        logger.info(f"🧹 Cleaned {len(stale)} stale jobs, {len(active_jobs)} remaining")


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
        if username == APP_USERNAME and password == APP_PASSWORD:
            session["logged_in"] = True
            session["user"] = username
            return redirect(url_for("index"))
        error = "Nieprawidłowy login lub hasło"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ============================================================
# BRAJEN API CLIENT
# ============================================================
def brajen_call(method, endpoint, json_data=None, timeout=None):
    """Call BRAJEN API with retry logic for cold starts."""
    url = f"{BRAJEN_API}{endpoint}"
    req_timeout = timeout or REQUEST_TIMEOUT

    for attempt in range(MAX_RETRIES):
        try:
            if method == "get":
                resp = http_requests.get(url, timeout=req_timeout)
            else:
                resp = http_requests.post(url, json=json_data, timeout=req_timeout)

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
            return {"ok": False, "status": 0, "error": "Timeout — Render cold start?"}

        except http_requests.exceptions.ConnectionError as e:
            logger.warning(f"BRAJEN connection error: {endpoint}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAYS[attempt])
                continue
            return {"ok": False, "status": 0, "error": str(e)[:200]}

    return {"ok": False, "status": 0, "error": "All retries exhausted"}


# ============================================================
# H2 PLAN GENERATOR (from S1 + user phrases)
# ============================================================
def generate_h2_plan(main_keyword, mode, s1_data, basic_terms, extended_terms, user_h2_hints=None):
    """
    Generate optimal H2 structure from S1 analysis data.
    Number of H2s is determined by analysis AND recommended article length.
    User phrases are context for topic coverage, NOT for stuffing into H2 titles.
    """
    client = get_claude_client()
    competitor_h2 = (s1_data.get("competitor_h2_patterns") or [])
    suggested_h2s = (s1_data.get("content_gaps") or {}).get("suggested_new_h2s", [])
    content_gaps = (s1_data.get("content_gaps") or {})
    causal_triplets = (s1_data.get("causal_triplets") or {})
    paa = (s1_data.get("paa") or s1_data.get("paa_questions") or [])
    
    # FIX: Determine max H2 count based on recommended_length
    recommended_length = s1_data.get("recommended_length", 3000)
    if mode == "fast":
        max_h2 = 4  # fast = max 3 content + FAQ
    else:
        # ~150-200 words per H2 section on average (+ intro ~100, FAQ ~200)
        effective_words = max(recommended_length - 300, 500)  # minus intro+FAQ
        max_h2 = min(12, max(4, effective_words // 180 + 2))  # +2 for intro-like + FAQ
    
    # Parse user phrases (strip ranges) — for topic context only
    all_user_phrases = []
    for term_str in (basic_terms + extended_terms):
        kw = term_str.strip().split(":")[0].strip()
        if kw:
            all_user_phrases.append(kw)
    
    # Count competitor H2s to understand typical depth
    avg_competitor_h2 = len(competitor_h2) if competitor_h2 else 0
    
    prompt = f"""Jesteś ekspertem SEO. Zaprojektuj optymalną strukturę nagłówków H2 dla artykułu po polsku.

HASŁO GŁÓWNE: {main_keyword}
TRYB: {mode} ({'standard = pełny artykuł' if mode == 'standard' else 'fast = krótki artykuł, max 3 sekcje'})

═══ DANE Z ANALIZY KONKURENCJI (S1) ═══

WZORCE H2 KONKURENCJI (najczęstsze tematy sekcji u konkurentów):
{json.dumps(competitor_h2[:20], ensure_ascii=False, indent=2)}

SUGEROWANE NOWE H2 (luki — tego NIKT z konkurencji nie pokrywa):
{json.dumps(suggested_h2s, ensure_ascii=False, indent=2)}

LUKI TREŚCIOWE:
{json.dumps((content_gaps.get("paa_unanswered") or []) + (content_gaps.get("subtopic_missing") or []) + (content_gaps.get("depth_missing") or []) or (content_gaps.get("gaps") or []), ensure_ascii=False, indent=2)[:1000] if (content_gaps.get("paa_unanswered") or content_gaps.get("subtopic_missing") or content_gaps.get("depth_missing") or content_gaps.get("gaps")) else "Brak"}

PYTANIA PAA (People Also Ask z Google):
{json.dumps(paa[:8], ensure_ascii=False, indent=2) if paa else "Brak"}

PRZYCZYNOWE ZALEŻNOŚCI (cause→effect z konkurencji):
{json.dumps((causal_triplets.get("chains") or causal_triplets.get("singles") or causal_triplets.get("triplets") or [])[:5], ensure_ascii=False, indent=2) if (causal_triplets.get("chains") or causal_triplets.get("singles") or causal_triplets.get("triplets")) else "Brak"}

{f"""═══ FRAZY H2 UŻYTKOWNIKA ═══

Użytkownik podał te frazy z myślą o nagłówkach H2.
Wykorzystaj je w nagłówkach tam, gdzie brzmią naturalnie po polsku.
Nie musisz użyć każdej — ale nie ignoruj ich. Dopasuj z wyczuciem.

Przykład: fraza "przeprowadzka – od czego zacząć" → H2: "Przeprowadzka – od czego zacząć"
Przykład: fraza "dzień przeprowadzki" → H2: "Dzień przeprowadzki – o czym pamiętać"
Przykład: fraza "kartony do przeprowadzki" → H2: "Kartony do przeprowadzki i materiały pakowe"

Jeśli fraza brzmi sztucznie jako nagłówek — lepiej ją przeformułuj lub pomiń w H2 (i tak trafi do treści).

FRAZY H2:
{json.dumps(user_h2_hints, ensure_ascii=False)}
""" if user_h2_hints else ""}
═══ KONTEKST TEMATYCZNY (frazy BASIC/EXTENDED) ═══

Poniższe frazy będą użyte W TREŚCI artykułu (nie w nagłówkach).
Podaję je tylko żebyś wiedział jaki zakres tematyczny artykuł musi pokryć,
i zaplanował H2 tak, by każda fraza miała naturalną sekcję do której pasuje:

{json.dumps(all_user_phrases, ensure_ascii=False)}

═══ ZASADY ═══

1. LICZBA H2: MAKSYMALNIE {max_h2} sekcji (włącznie z FAQ). Artykuł ma mieć ok. {recommended_length} słów — nie twórz więcej sekcji niż się zmieści.
   {'Tryb fast: max 3 sekcje + FAQ.' if mode == 'fast' else f'Przy {recommended_length} słów optymalnie {max(3, max_h2-3)}-{max_h2} sekcji. Za dużo H2 = każda sekcja będzie płytka.'}
2. OSTATNI H2 MUSI być: "Najczęściej zadawane pytania"
3. Pokryj najważniejsze wzorce z konkurencji + luki treściowe (przewaga nad konkurencją)
4. {'Uwzględnij frazy H2 użytkownika w nagłówkach, o ile brzmią naturalnie. Resztę dopasuj z S1.' if user_h2_hints else 'Dobierz nagłówki na podstawie S1 i luk treściowych.'}
5. Logiczna narracja — od ogółu do szczegółu, chronologicznie, lub problemowo
6. NIE powtarzaj hasła głównego dosłownie w każdym H2
7. H2 muszą brzmieć naturalnie po polsku — żadnego keyword stuffingu

═══ FORMAT ODPOWIEDZI ═══

Odpowiedz TYLKO JSON array, bez markdown, bez komentarzy:
["H2 pierwszy", "H2 drugi", ..., "Najczęściej zadawane pytania"]
"""

    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5
    )
    
    response_text = response.content[0].text.strip()
    
    # Parse JSON response
    try:
        clean = response_text.replace("```json", "").replace("```", "").strip()
        h2_list = json.loads(clean)
        if isinstance(h2_list, list) and len(h2_list) >= 2:
            # FIX: Cap to max_h2 (keep FAQ as last)
            if len(h2_list) > max_h2:
                has_faq = any("pytania" in h.lower() for h in h2_list[-2:])
                if has_faq:
                    h2_list = h2_list[:max_h2-1] + [h2_list[-1]]
                else:
                    h2_list = h2_list[:max_h2]
            return h2_list
    except (json.JSONDecodeError, ValueError):
        pass
    
    # Fallback: extract lines that look like H2s
    lines = [l.strip().strip('"').strip("'").strip(",").strip('"') 
             for l in response_text.split("\n") if l.strip() and not l.strip().startswith("[") and not l.strip().startswith("]")]
    if lines:
        return lines
    
    # Ultimate fallback
    fallback = suggested_h2s[:7] + ["Najczęściej zadawane pytania"] if suggested_h2s else [main_keyword, "Najczęściej zadawane pytania"]
    return fallback


# ============================================================
# TEXT GENERATION (Claude + OpenAI)
# ============================================================
def generate_batch_text(pre_batch, h2, batch_type, article_memory=None, engine="claude"):
    """Generate batch text using FULL pre_batch data — mirrors what Custom GPT received.
    
    Custom GPT got the entire pre_batch_info response and used gpt_instructions_v39
    plus ALL contextual fields. We must do the same.
    """
    
    # ─── SYSTEM PROMPT = gpt_instructions_v39 + gpt_prompt ───
    # gpt_instructions_v39 = writing techniques (passage-first, burstiness, anti-wall-of-info)
    # gpt_prompt = batch context (coverage, density, semantic plan, keyword lists)
    gpt_instructions = pre_batch.get("gpt_instructions_v39", "")
    gpt_prompt = pre_batch.get("gpt_prompt", "")
    
    if gpt_instructions and gpt_prompt:
        system_prompt = gpt_instructions + "\n\n" + gpt_prompt
    elif gpt_instructions:
        system_prompt = gpt_instructions
    elif gpt_prompt:
        system_prompt = gpt_prompt
    else:
        system_prompt = "Jesteś ekspertem SEO. Pisz naturalnie po polsku, unikaj sztucznego tonu AI."

    # ─── USER PROMPT = FULL batch context (all fields Custom GPT could see) ───
    keywords_info = (pre_batch.get("keywords") or {})
    keyword_limits = (pre_batch.get("keyword_limits") or {})
    batch_length = (pre_batch.get("batch_length") or {})
    enhanced = pre_batch.get("enhanced") or {}
    style = pre_batch.get("style_instructions") or {}
    semantic_plan = pre_batch.get("semantic_batch_plan") or {}
    ngrams = (pre_batch.get("ngrams_for_batch") or [])
    entity_seo = pre_batch.get("entity_seo") or {}
    serp = pre_batch.get("serp_enrichment") or {}
    legal_ctx = pre_batch.get("legal_context") or {}
    medical_ctx = pre_batch.get("medical_context") or {}
    coverage = pre_batch.get("coverage") or {}
    density = pre_batch.get("density") or {}
    main_kw = pre_batch.get("main_keyword") or {}
    soft_caps = pre_batch.get("soft_cap_recommendations") or {}
    dynamic_sections = pre_batch.get("dynamic_sections") or {}
    h2_plan = (pre_batch.get("h2_plan") or [])
    h2_remaining = (pre_batch.get("h2_remaining") or [])
    batch_number = pre_batch.get("batch_number", 1)
    total_batches = pre_batch.get("total_planned_batches", 1)
    intro_guidance = pre_batch.get("intro_guidance", "")
    entities_for_batch = pre_batch.get("entities_for_batch") or {}
    section_length_guidance = pre_batch.get("section_length_guidance") or {}
    ngram_guidance = pre_batch.get("ngram_guidance") or {}

    # Build STOP keywords clearly
    stop_kws = (keyword_limits.get("stop_keywords") or [])
    stop_list = [s.get("keyword", s) if isinstance(s, dict) else s for s in stop_kws]
    
    caution_kws = (keyword_limits.get("caution_keywords") or [])
    caution_list = [c.get("keyword", c) if isinstance(c, dict) else c for c in caution_kws]

    # Build comprehensive user prompt
    sections = []
    
    # Core batch info
    sections.append(f"""═══ BATCH {batch_number}/{total_batches} ═══
Typ: {batch_type}
H2: {h2}
Zaczynaj DOKŁADNIE od: h2: {h2}
Długość: {json.dumps(batch_length, ensure_ascii=False) if batch_length else '350-500 słów'}""")

    # Intro guidance (for first batch)
    if intro_guidance and batch_type == "INTRO":
        sections.append(f"INTRO GUIDANCE:\n{json.dumps(intro_guidance, ensure_ascii=False) if isinstance(intro_guidance, dict) else intro_guidance}")

    # Keywords — MUST use
    must_use = [kw.get('keyword', kw) if isinstance(kw, dict) else kw for kw in keywords_info.get('basic_must_use', [])]
    ext_use = [kw.get('keyword', kw) if isinstance(kw, dict) else kw for kw in keywords_info.get('extended_this_batch', [])]
    
    sections.append(f"""═══ FRAZY ═══
🔴 MUST (użyj w tekście — obowiązkowe):
{json.dumps(must_use, ensure_ascii=False)}

🟡 EXTENDED (użyj naturalnie jeśli pasują):
{json.dumps(ext_use, ensure_ascii=False)}

🛑 STOP — NIE UŻYWAJ (przekroczone limity!):
{json.dumps(stop_list, ensure_ascii=False)}

⚠️ OSTROŻNIE — max 1× jeśli użyjesz:
{json.dumps(caution_list, ensure_ascii=False)}""")

    # Semantic batch plan
    if semantic_plan:
        sections.append(f"═══ SEMANTIC BATCH PLAN ═══\n{json.dumps(semantic_plan, ensure_ascii=False)}")

    # Article memory (anti-Frankenstein)
    if article_memory:
        mem_str = json.dumps(article_memory, ensure_ascii=False)
        sections.append(f"═══ ARTICLE MEMORY (nie powtarzaj!) ═══\n{mem_str[:2000]}")

    # Style instructions
    if style:
        sections.append(f"═══ STYL ═══\n{json.dumps(style, ensure_ascii=False)}")

    # Dynamic sections (anti-Frankenstein token budgeting)
    if dynamic_sections:
        sections.append(f"═══ DYNAMIC SECTIONS ═══\n{json.dumps(dynamic_sections, ensure_ascii=False)[:1500]}")

    # Entity SEO
    if entity_seo and entity_seo.get("enabled"):
        sections.append(f"═══ ENTITY SEO ═══\n{json.dumps(entity_seo, ensure_ascii=False)[:1000]}")
    
    # Entities for this batch
    if entities_for_batch:
        sections.append(f"═══ ENTITIES FOR BATCH ═══\n{json.dumps(entities_for_batch, ensure_ascii=False)[:800]}")

    # N-grams
    if ngrams:
        sections.append(f"═══ N-GRAMY ═══\n{json.dumps(ngrams[:10], ensure_ascii=False)}")

    # N-gram guidance (overused, synonyms, LSI)
    if ngram_guidance:
        sections.append(f"═══ NGRAM GUIDANCE ═══\n{json.dumps(ngram_guidance, ensure_ascii=False)[:800]}")

    # SERP enrichment (PAA, LSI, related)
    if serp:
        paa = (serp.get("paa_for_batch") or [])
        lsi = (serp.get("lsi_keywords") or [])
        if paa or lsi:
            sections.append(f"═══ SERP ENRICHMENT ═══\nPAA: {json.dumps(paa[:5], ensure_ascii=False)}\nLSI: {json.dumps(lsi[:8], ensure_ascii=False)}")

    # Enhanced data (experience markers, continuation, etc.)
    if enhanced:
        enhanced_parts = []
        if enhanced.get("continuation_context"):
            enhanced_parts.append(f"Continuation: {json.dumps(enhanced['continuation_context'], ensure_ascii=False)[:500]}")
        if enhanced.get("experience_markers"):
            enhanced_parts.append(f"Experience markers: {json.dumps(enhanced['experience_markers'], ensure_ascii=False)[:300]}")
        if enhanced.get("paa_from_serp"):
            enhanced_parts.append(f"PAA from SERP: {json.dumps(enhanced['paa_from_serp'][:5], ensure_ascii=False)}")
        if enhanced.get("entities_to_define"):
            enhanced_parts.append(f"Entities to define: {json.dumps(enhanced['entities_to_define'], ensure_ascii=False)[:500]}")
        if enhanced.get("relations_to_establish"):
            enhanced_parts.append(f"Relations: {json.dumps(enhanced['relations_to_establish'], ensure_ascii=False)[:500]}")
        if enhanced.get("phrase_hierarchy"):
            enhanced_parts.append(f"Phrase hierarchy: {json.dumps(enhanced['phrase_hierarchy'], ensure_ascii=False)[:500]}")
        # 🆕 v45.0: Causal context from S1
        if enhanced.get("causal_context"):
            enhanced_parts.append(f"Causal context: {enhanced['causal_context'][:600]}")
        # 🆕 v45.0: Information gain / content gaps from S1
        if enhanced.get("information_gain"):
            enhanced_parts.append(f"Information gain: {enhanced['information_gain'][:600]}")
        # 🆕 v45.0: Smart batch instructions (formatted for GPT)
        if enhanced.get("smart_instructions_formatted"):
            enhanced_parts.append(f"Smart instructions:\n{enhanced['smart_instructions_formatted'][:800]}")
        if enhanced_parts:
            sections.append(f"═══ ENHANCED CONTEXT ═══\n" + "\n".join(enhanced_parts))

    # 🆕 v45.0: Continuation context (top-level from pre_batch)
    continuation_v39 = pre_batch.get("continuation_v39") or {}
    if continuation_v39:
        sections.append(f"═══ CONTINUATION ═══\n{json.dumps(continuation_v39, ensure_ascii=False)[:600]}")

    # 🆕 v45.0: Keyword tracking (top-level from pre_batch)
    keyword_tracking = pre_batch.get("keyword_tracking") or {}
    if keyword_tracking:
        sections.append(f"═══ KEYWORD TRACKING ═══\n{json.dumps(keyword_tracking, ensure_ascii=False)[:600]}")

    # Soft cap recommendations
    if soft_caps:
        sections.append(f"═══ SOFT CAPS ═══\n{json.dumps(soft_caps, ensure_ascii=False)[:500]}")

    # Section length guidance
    if section_length_guidance:
        sections.append(f"═══ SECTION LENGTH ═══\n{json.dumps(section_length_guidance, ensure_ascii=False)}")

    # Coverage and density context
    if coverage:
        sections.append(f"═══ COVERAGE ═══\n{json.dumps(coverage, ensure_ascii=False)}")
    if density:
        sections.append(f"═══ DENSITY ═══\n{json.dumps(density, ensure_ascii=False)}")

    # Main keyword info
    if main_kw:
        sections.append(f"═══ MAIN KEYWORD ═══\n{json.dumps(main_kw, ensure_ascii=False)}")

    # Legal/Medical YMYL context
    if legal_ctx and legal_ctx.get("active"):
        sections.append(f"═══ KONTEKST PRAWNY (YMYL) ═══\n{json.dumps(legal_ctx, ensure_ascii=False)[:1000]}")
    if medical_ctx and medical_ctx.get("active"):
        sections.append(f"═══ KONTEKST MEDYCZNY (YMYL) ═══\n{json.dumps(medical_ctx, ensure_ascii=False)[:1000]}")

    # H2 plan and remaining
    if h2_remaining:
        sections.append(f"═══ H2 REMAINING ═══\n{json.dumps(h2_remaining, ensure_ascii=False)}")

    # Rewrite context (when text was rejected and needs regeneration)
    rewrite_ctx = pre_batch.get("rewrite_context")
    if rewrite_ctx:
        sections.append(f"""═══ ⚠️ REWRITE — POPRAW TE PROBLEMY ═══
Poprzednia wersja została ODRZUCONA. Napisz tekst OD NOWA, unikając tych błędów:
{rewrite_ctx.get('issues_to_fix', 'Brak szczegółów')}
Powód: {rewrite_ctx.get('rewrite_reason', '?')}
Próba: {rewrite_ctx.get('attempt', '?')}""")

    # Format instruction
    sections.append("""═══ FORMAT ═══
Pisz TYLKO treść batcha. Zaczynaj od h2: [tytuł].
Format: h2: Tytuł\\n\\nAkapit 1\\n\\nAkapit 2\\n\\nh3: Podsekcja (opcjonalnie)
NIE dodawaj komentarzy, wyjaśnień ani podsumowań poza treścią batcha.""")

    user_prompt = "\n\n".join(sections)

    if engine == "openai" and OPENAI_API_KEY:
        return _generate_openai(system_prompt, user_prompt)
    else:
        return _generate_claude(system_prompt, user_prompt)


def _generate_claude(system_prompt, user_prompt):
    """Generate text using Anthropic Claude."""
    client = get_claude_client()
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=4000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        temperature=0.7
    )
    return response.content[0].text.strip()


def _generate_openai(system_prompt, user_prompt):
    """Generate text using OpenAI GPT."""
    if not OPENAI_AVAILABLE:
        logger.warning("OpenAI not installed, falling back to Claude")
        return _generate_claude(system_prompt, user_prompt)
    
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.7,
        max_tokens=4000
    )
    return response.choices[0].message.content.strip()


def generate_faq_text(paa_data, pre_batch=None, engine="claude"):
    """Generate FAQ section using PAA data + full pre_batch context."""

    paa_questions = (paa_data.get("serp_paa") or [])
    unused = (paa_data.get("unused_keywords") or {})
    avoid = (paa_data.get("avoid_in_faq") or [])
    instructions = paa_data.get("instructions", "")

    # Get gpt_instructions from pre_batch (same as Custom GPT)
    system_prompt = ""
    if pre_batch:
        system_prompt = pre_batch.get("gpt_instructions_v39", "") or pre_batch.get("gpt_prompt", "")
    if not system_prompt:
        system_prompt = "Jesteś ekspertem SEO piszącym sekcję FAQ po polsku. Pisz naturalnie, bez sztucznego tonu."

    # Enhanced PAA from pre_batch
    enhanced_paa = []
    enhanced = {}
    if pre_batch:
        enhanced = pre_batch.get("enhanced") or {}
        enhanced_paa = (enhanced.get("paa_from_serp") or [])

    # Keywords context
    keywords_info = {}
    keyword_limits = {}
    if pre_batch:
        keywords_info = (pre_batch.get("keywords") or {})
        keyword_limits = (pre_batch.get("keyword_limits") or {})

    stop_kws = (keyword_limits.get("stop_keywords") or [])
    stop_list = [s.get("keyword", s) if isinstance(s, dict) else s for s in stop_kws]
    
    user_prompt = f"""═══ BATCH FAQ ═══
Napisz sekcję FAQ dla artykułu SEO po polsku.
Zaczynaj DOKŁADNIE od: h2: Najczęściej zadawane pytania

Pytania PAA z Google SERP:
{json.dumps(paa_questions, ensure_ascii=False)}

{f'Dodatkowe PAA z enhanced: {json.dumps(enhanced_paa, ensure_ascii=False)}' if enhanced_paa else ''}

Nieużyte frazy (wpleć naturalnie w odpowiedzi):
{json.dumps(unused, ensure_ascii=False)}

NIE powtarzaj tematów już pokrytych w artykule:
{json.dumps(avoid, ensure_ascii=False)}

🛑 STOP — NIE UŻYWAJ tych fraz:
{json.dumps(stop_list, ensure_ascii=False)}

{f'Instrukcje API: {instructions}' if instructions else ''}
{f'Article memory: {json.dumps(pre_batch.get("article_memory"), ensure_ascii=False)[:1000]}' if pre_batch and pre_batch.get("article_memory") else ''}
{f'Style: {json.dumps(pre_batch.get("style_instructions"), ensure_ascii=False)}' if pre_batch and pre_batch.get("style_instructions") else ''}

═══ FORMAT ═══
h2: Najczęściej zadawane pytania

h3: [Pytanie 1]
[Odpowiedź 60-120 słów]

h3: [Pytanie 2]
[Odpowiedź 60-120 słów]

Wybierz 4-6 najlepszych pytań. Pisz TYLKO treść batcha, bez komentarzy."""

    if engine == "openai" and OPENAI_API_KEY:
        return _generate_openai(system_prompt, user_prompt)
    else:
        return _generate_claude(system_prompt, user_prompt)


# ============================================================
# FAQ HELPER
# ============================================================
def _extract_faq_questions(text):
    """Extract FAQ questions and answers from batch text."""
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
    return questions


# ─── HELPER: Summarize article memory for UI ───
def _summarize_article_memory(memory):
    if not memory:
        return None
    if isinstance(memory, str):
        return {"preview": memory[:200], "length": len(memory)}
    if isinstance(memory, dict):
        topics = memory.get("covered_topics") or memory.get("topics") or []
        h2_done = memory.get("h2_completed") or memory.get("completed_h2") or []
        key_phrases = memory.get("key_phrases_used") or []
        return {
            "topics_covered": topics[:8] if isinstance(topics, list) else [],
            "h2_completed": h2_done[:8] if isinstance(h2_done, list) else [],
            "key_phrases_used": key_phrases[:10] if isinstance(key_phrases, list) else [],
            "word_count": memory.get("word_count", 0),
        }
    return None

# ─── HELPER: Summarize style instructions for UI ───
def _summarize_style(style):
    if not style:
        return None
    if isinstance(style, dict):
        return {
            "tone": style.get("tone", style.get("suggested_tone", "")),
            "avg_sentence_length": style.get("avg_sentence_length", ""),
            "cv_target": style.get("cv_target", style.get("burstiness_cv", "")),
            "overused_words": (style.get("overused_words") or [])[:5],
            "forbidden": (style.get("forbidden_phrases") or [])[:5],
        }
    return None

# ─── HELPER: Summarize YMYL context for UI ───
def _summarize_ymyl_context(ctx):
    if not ctx or not isinstance(ctx, dict) or not ctx.get("active"):
        return None
    return {
        "active": True,
        "citations_count": len(ctx.get("top_judgments") or ctx.get("top_publications") or []),
        "must_cite": ctx.get("must_cite", False),
        "citation_hint": ctx.get("citation_hint", ""),
        "instruction_preview": (ctx.get("legal_instruction") or ctx.get("medical_instruction") or "")[:200],
    }

# ─── HELPER: Summarize continuation context for UI ───
def _summarize_continuation(cont):
    if not cont or not isinstance(cont, dict):
        return None
    return {
        "last_topic": cont.get("last_topic", cont.get("previous_h2", "")),
        "transition_hint": cont.get("transition_hint", cont.get("suggested_transition", "")),
        "avoid_repetition": (cont.get("avoid_repetition") or cont.get("already_covered") or [])[:5],
    }

# ─── HELPER: Build S1 compliance report ───
def _build_s1_compliance(s1, article_text, editorial_data):
    """Compare S1 analysis elements against final article to check fulfillment."""
    if not s1 or not article_text:
        return {}
    text_lower = article_text.lower()

    # 1. Entity compliance
    entity_seo = s1.get("entity_seo") or {}
    all_entities = entity_seo.get("top_entities") or entity_seo.get("entities") or []
    must_entities = entity_seo.get("must_mention_entities") or []
    entity_results = []
    for ent in all_entities[:15]:
        name = ent.get("entity") or ent.get("name") or (ent if isinstance(ent, str) else str(ent))
        name_str = str(name).strip()
        found = name_str.lower() in text_lower
        is_must = any(
            (str(m.get("entity", m.get("name", m)) if isinstance(m, dict) else m).lower().strip() == name_str.lower())
            for m in must_entities
        )
        entity_results.append({"entity": name_str, "found": found, "must": is_must})

    # 2. Causal triplets compliance
    causal = s1.get("causal_triplets") or {}
    all_triplets = (causal.get("chains") or []) + (causal.get("singles") or [])
    triplet_results = []
    for t in all_triplets[:12]:
        cause = str(t.get("cause") or t.get("from") or "").strip()
        effect = str(t.get("effect") or t.get("to") or "").strip()
        cause_found = cause.lower() in text_lower if cause else False
        effect_found = effect.lower() in text_lower if effect else False
        triplet_results.append({
            "cause": cause, "effect": effect,
            "cause_found": cause_found, "effect_found": effect_found,
            "fulfilled": cause_found and effect_found
        })

    # 3. Content gaps H2 compliance
    content_gaps = s1.get("content_gaps") or {}
    suggested_h2s = content_gaps.get("suggested_new_h2s") or []
    gap_results = []
    for h2 in suggested_h2s[:10]:
        words = [w for w in h2.lower().split() if len(w) > 3]
        match_count = sum(1 for w in words if w in text_lower)
        cov = (match_count / max(len(words), 1)) * 100
        gap_results.append({"h2": h2, "coverage_pct": round(cov), "covered": cov > 50})

    # 4. PAA unanswered compliance
    paa_unanswered = content_gaps.get("paa_unanswered") or []
    paa_gap_results = []
    for paa in paa_unanswered[:8]:
        q = paa.get("question") or paa.get("topic") or (paa if isinstance(paa, str) else str(paa))
        q_str = str(q).strip()
        words = [w for w in q_str.lower().split() if len(w) > 3]
        match_count = sum(1 for w in words if w in text_lower)
        cov = (match_count / max(len(words), 1)) * 100
        paa_gap_results.append({"question": q_str, "coverage_pct": round(cov), "answered": cov > 40})

    # 5. N-gram usage
    ngrams = s1.get("ngrams") or s1.get("hybrid_ngrams") or []
    ngram_results = []
    for ng in ngrams[:15]:
        phrase = ng.get("ngram") or ng.get("phrase") or (ng[0] if isinstance(ng, (list, tuple)) else str(ng))
        phrase_str = str(phrase).strip()
        found = phrase_str.lower() in text_lower
        weight = ng.get("weight") or ng.get("score") or 0
        ngram_results.append({"ngram": phrase_str, "found": found, "weight": round(float(weight), 2) if weight else 0})

    # 6. PAA questions addressed
    paa_questions = s1.get("paa") or s1.get("paa_questions") or []
    paa_results = []
    for paa in paa_questions[:10]:
        q = paa.get("question") or (paa if isinstance(paa, str) else str(paa))
        q_str = str(q).strip()
        words = [w for w in q_str.lower().split() if len(w) > 3]
        match_count = sum(1 for w in words if w in text_lower)
        cov = (match_count / max(len(words), 1)) * 100
        paa_results.append({"question": q_str, "addressed": cov > 40, "coverage_pct": round(cov)})

    # 7. Semantic keyphrases
    sem_results = []
    for kp in (s1.get("semantic_keyphrases") or [])[:10]:
        phrase = kp.get("phrase") or kp.get("keyphrase") or (kp if isinstance(kp, str) else str(kp))
        phrase_str = str(phrase).strip()
        sem_results.append({"phrase": phrase_str, "found": phrase_str.lower() in text_lower})

    # Summary
    ef = lambda lst, key: (sum(1 for x in lst if x.get(key)), len(lst))
    ent_f, ent_t = ef(entity_results, "found")
    must_f = sum(1 for e in entity_results if e["must"] and e["found"])
    must_t = sum(1 for e in entity_results if e["must"])
    tri_f, tri_t = ef(triplet_results, "fulfilled")
    gap_f, gap_t = ef(gap_results, "covered")
    ng_f, ng_t = ef(ngram_results, "found")
    paa_f, paa_t = ef(paa_results, "addressed")
    sem_f, sem_t = ef(sem_results, "found")

    ed_score = editorial_data.get("overall_score", "?") if editorial_data else "?"
    ed_fb = editorial_data.get("editorial_feedback") or {} if editorial_data else {}

    return {
        "summary": {
            "entities": f"{ent_f}/{ent_t}", "entities_must": f"{must_f}/{must_t}",
            "causal_triplets": f"{tri_f}/{tri_t}", "content_gaps": f"{gap_f}/{gap_t}",
            "ngrams": f"{ng_f}/{ng_t}", "paa": f"{paa_f}/{paa_t}",
            "semantic_keyphrases": f"{sem_f}/{sem_t}", "editorial_score": ed_score,
        },
        "entities": entity_results, "causal_triplets": triplet_results,
        "content_gaps_h2": gap_results, "content_gaps_paa": paa_gap_results,
        "ngrams": ngram_results, "paa_questions": paa_results,
        "semantic_keyphrases": sem_results,
        "editorial_feedback": {
            "recenzja_ogolna": ed_fb.get("recenzja_ogolna", ""),
            "luki_tresciowe": ed_fb.get("luki_tresciowe", {}),
        }
    }


# ============================================================
# WORKFLOW ORCHESTRATOR (SSE)
# ============================================================
def run_workflow_sse(job_id, main_keyword, mode, h2_structure, basic_terms, extended_terms):
    """
    Full BRAJEN workflow as a generator yielding SSE events.
    Follows PROMPT_v45_2.md EXACTLY:
    KROK 1: S1 → 2: YMYL → 3: (H2 already provided) → 4: Create → 5: Hierarchy →
    6: Batch Loop → 7: PAA → 8: Final Review → 9: Editorial → 10: Export
    """
    def emit(event_type, data):
        """Yield SSE event."""
        return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    job = active_jobs.get(job_id, {})

    try:
        # ─── KROK 0: Wybór trybu ───
        yield emit("step", {"step": 0, "name": "Wybór trybu", "status": "done",
                            "detail": f"Tryb: {mode.upper()} | Keyword: {main_keyword}"})

        # ─── KROK 1: S1 Analysis ───
        yield emit("step", {"step": 1, "name": "S1 Analysis", "status": "running"})
        yield emit("log", {"msg": f"POST /api/s1_analysis → {main_keyword}"})

        s1_result = brajen_call("post", "/api/s1_analysis", {"main_keyword": main_keyword})
        if not s1_result["ok"]:
            yield emit("workflow_error", {"step": 1, "msg": f"S1 Analysis failed: {s1_result.get('error', 'unknown')}"})
            return

        s1 = s1_result["data"]
        h2_patterns = len((s1.get("competitor_h2_patterns") or []))
        causal_count = (s1.get("causal_triplets") or {}).get("count", 0)
        gaps_count = (s1.get("content_gaps") or {}).get("total_gaps", 0)
        suggested_h2s = (s1.get("content_gaps") or {}).get("suggested_new_h2s", [])

        yield emit("step", {"step": 1, "name": "S1 Analysis", "status": "done",
                            "detail": f"{h2_patterns} H2 patterns | {causal_count} causal triplets | {gaps_count} content gaps"})
        
        # Send FULL S1 data for UI display — all 10 analysis sections
        entity_seo_full = s1.get("entity_seo") or {}
        causal_full = s1.get("causal_triplets") or {}
        content_gaps_full = s1.get("content_gaps") or {}
        length_analysis = s1.get("length_analysis") or {}
        serp_analysis = s1.get("serp_analysis") or {}
        sem_hints = s1.get("semantic_enhancement_hints") or {}

        yield emit("s1_data", {
            # ─── 1️⃣ SERP & Competitor Structure ───
            "search_intent": s1.get("search_intent", ""),
            "recommended_length": s1.get("recommended_length", 0),
            "median_length": length_analysis.get("median", s1.get("median_length", 0)),
            "average_length": length_analysis.get("average", 0),
            "analyzed_urls": length_analysis.get("analyzed_urls", 0),
            "word_counts": length_analysis.get("word_counts", []),
            "h2_patterns_count": h2_patterns,
            "competitor_h2_patterns": (s1.get("competitor_h2_patterns") or [])[:25],
            "serp_sources": (serp_analysis.get("sources") or serp_analysis.get("competitors") or s1.get("serp_sources") or [])[:10],
            "featured_snippet": s1.get("featured_snippet") or serp_analysis.get("featured_snippet") or None,
            "ai_overview": s1.get("ai_overview") or serp_analysis.get("ai_overview") or None,
            "related_searches": (s1.get("related_searches") or serp_analysis.get("related_searches") or [])[:10],

            # ─── 2️⃣ Causal Triplets ───
            "causal_triplets_count": causal_count,
            "causal_chains": causal_full.get("chains", [])[:15],
            "causal_singles": causal_full.get("singles", [])[:15],
            "causal_instruction": causal_full.get("agent_instruction", ""),
            "causal_count_chains": len(causal_full.get("chains", [])),
            "causal_count_singles": len(causal_full.get("singles", [])),

            # ─── 3️⃣ Gap Analysis ───
            "content_gaps_count": gaps_count,
            "content_gaps": content_gaps_full,
            "suggested_h2s": suggested_h2s,
            "paa_unanswered": content_gaps_full.get("paa_unanswered", []),
            "subtopic_missing": content_gaps_full.get("subtopic_missing", []),
            "depth_missing": content_gaps_full.get("depth_missing", []),
            "gaps_instruction": content_gaps_full.get("agent_instruction", ""),
            "information_gain": content_gaps_full.get("information_gain", []),

            # ─── 4️⃣ Entity SEO ───
            "entity_seo": {
                "top_entities": (entity_seo_full.get("top_entities") or entity_seo_full.get("entities") or [])[:20],
                "must_mention": (entity_seo_full.get("must_mention_entities") or [])[:10],
                "relations": (entity_seo_full.get("relations") or entity_seo_full.get("entity_relationships") or [])[:15],
                "entity_count": len(entity_seo_full.get("top_entities") or entity_seo_full.get("entities") or []),
                "categories": entity_seo_full.get("categories", []),
                "topical_coverage": (entity_seo_full.get("topical_coverage") or s1.get("topical_coverage") or [])[:15],
            },

            # ─── 5️⃣ N-grams & Collocations ───
            "ngrams": (s1.get("ngrams") or s1.get("hybrid_ngrams") or [])[:20],
            "semantic_keyphrases": (s1.get("semantic_keyphrases") or [])[:15],

            # ─── 6️⃣ Phrase Hierarchy (will be enriched after KROK 5) ───
            "phrase_hierarchy_preview": s1.get("phrase_hierarchy") or {},

            # ─── 7️⃣ Depth Analysis (extracted from S1 competitor data) ───
            "depth_signals": {
                "numbers_used": bool(s1.get("depth_numbers") or any("liczb" in str(d).lower() for d in content_gaps_full.get("depth_missing", []))),
                "dates_used": bool(s1.get("depth_dates")),
                "institutions_cited": bool(s1.get("depth_institutions")),
                "research_cited": bool(s1.get("depth_research")),
                "laws_referenced": bool(s1.get("depth_laws")),
                "exceptions_noted": bool(s1.get("depth_exceptions")),
                "comparisons_made": bool(s1.get("depth_comparisons")),
                "step_by_step": bool(s1.get("depth_step_by_step")),
            },
            "depth_missing_items": content_gaps_full.get("depth_missing", []),

            # ─── 8️⃣ YMYL Signals (preliminary from S1) ───
            "ymyl_hints": {
                "legal_signals": bool(s1.get("ymyl_legal") or s1.get("legal_signals")),
                "medical_signals": bool(s1.get("ymyl_medical") or s1.get("medical_signals")),
                "needs_citations": bool(s1.get("needs_citations")),
                "needs_disclaimer": bool(s1.get("needs_disclaimer")),
            },

            # ─── 9️⃣ PAA / FAQ Potential ───
            "paa_questions": (s1.get("paa") or s1.get("paa_questions") or [])[:15],
            "paa_unanswered_count": len(content_gaps_full.get("paa_unanswered", [])),

            # ─── 🔟 Agent Instructions ───
            "agent_instructions": {
                "gaps": content_gaps_full.get("agent_instruction", ""),
                "causal": causal_full.get("agent_instruction", ""),
                "semantic": (sem_hints.get("checkpoints") or {}),
            },

            # ─── Semantic Enhancement Hints ───
            "semantic_hints": {
                "critical_entities": sem_hints.get("critical_entities", []),
                "high_entities": sem_hints.get("high_entities", []),
                "must_topics": sem_hints.get("must_topics", []),
            },
        })

        # ─── KROK 2: YMYL Detection ───
        yield emit("step", {"step": 2, "name": "YMYL Detection", "status": "running"})

        legal_result = brajen_call("post", "/api/legal/detect", {"main_keyword": main_keyword})
        medical_result = brajen_call("post", "/api/medical/detect", {"main_keyword": main_keyword})

        is_legal = (legal_result.get("data") or {}).get("is_ymyl", False) if legal_result["ok"] else False
        is_medical = (medical_result.get("data") or {}).get("is_ymyl", False) if medical_result["ok"] else False

        legal_context = None
        medical_context = None

        if is_legal:
            yield emit("log", {"msg": "⚖️ Temat prawny YMYL — pobieram kontekst..."})
            lc = brajen_call("post", "/api/legal/get_context", {"main_keyword": main_keyword})
            if lc["ok"]:
                legal_context = lc["data"]

        if is_medical:
            yield emit("log", {"msg": "🏥 Temat medyczny YMYL — pobieram kontekst..."})
            mc = brajen_call("post", "/api/medical/get_context", {"main_keyword": main_keyword})
            if mc["ok"]:
                medical_context = mc["data"]

        ymyl_detail = f"Legal: {'TAK' if is_legal else 'NIE'} | Medical: {'TAK' if is_medical else 'NIE'}"
        yield emit("step", {"step": 2, "name": "YMYL Detection", "status": "done", "detail": ymyl_detail})

        # ─── KROK 3: H2 Planning (auto from S1 + phrase optimization) ───
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
            # User provided hints — use them as hints, optimize with S1
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
        yield emit("step", {"step": 3, "name": "H2 Planning", "status": "done",
                            "detail": f"{len(h2_structure)} nagłówków H2"})

        # ─── KROK 4: Create Project ───
        yield emit("step", {"step": 4, "name": "Create Project", "status": "running"})

        # Build keywords array
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

        yield emit("log", {"msg": f"Keywords: {len(keywords)} ({sum(1 for k in keywords if k['type']=='BASIC')} BASIC, {sum(1 for k in keywords if k['type']=='EXTENDED')} EXTENDED)"})

        # FIX: Przekazuj PEŁNE dane S1 (nie filtrowane) — API potrzebuje ich
        # do batch_planner.py, enhanced_pre_batch.py, concept_map, E-E-A-T itd.
        # FIX: Użyj recommended_length z S1 (mediana konkurencji × 1.1)
        # zamiast hardcoded wartości
        recommended_length = s1.get("recommended_length", 3500 if mode == "standard" else 2000)
        yield emit("log", {"msg": f"Recommended length z S1: {recommended_length} słów"})

        project_payload = {
            "main_keyword": main_keyword,
            "mode": mode,
            "h2_structure": h2_structure,
            "keywords": keywords,
            "s1_data": s1,
            "target_length": recommended_length,
            "source": "brajen-webapp",
            "compact": False,  # Webapp nie ma limitu tokenów jak GPT — chcemy pełne dane
            # YMYL data from KROK 2
            "is_legal": is_legal,
            "is_medical": is_medical,
            "is_ymyl": is_legal or is_medical,
            "legal_instruction": (legal_context or {}).get("instruction", "") if legal_context else "",
            "medical_instruction": (medical_context or {}).get("instruction", "") if medical_context else "",
        }

        create_result = brajen_call("post", "/api/project/create", project_payload)
        if not create_result["ok"]:
            yield emit("workflow_error", {"step": 4, "msg": f"Create Project failed: {create_result.get('error', 'unknown')}"})
            return

        project = create_result["data"]
        project_id = project.get("project_id")
        total_batches = project.get("total_planned_batches", len(h2_structure))

        yield emit("step", {"step": 4, "name": "Create Project", "status": "done",
                            "detail": f"ID: {project_id} | Mode: {mode} | Batche: {total_batches}"})
        yield emit("project", {"project_id": project_id, "total_batches": total_batches})

        # Store project_id in job
        job["project_id"] = project_id
        
        # 🧹 Free S1 data — keep ONLY what _build_s1_compliance needs
        # BUG FIX: s1=None broke S1 compliance panel (always empty)
        s1_for_compliance = {
            "entity_seo": s1.get("entity_seo") or {},
            "causal_triplets": s1.get("causal_triplets") or {},
            "content_gaps": s1.get("content_gaps") or {},
            "ngrams": (s1.get("ngrams") or s1.get("hybrid_ngrams") or [])[:20],
            "paa": (s1.get("paa") or s1.get("paa_questions") or [])[:15],
            "semantic_keyphrases": (s1.get("semantic_keyphrases") or [])[:15],
        }
        del s1_result, entity_seo_full, causal_full, content_gaps_full, length_analysis, serp_analysis, sem_hints
        project_payload = None
        s1 = None
        gc.collect()
        logger.info(f"🧹 S1 data freed (compliance snapshot kept) after project {project_id} creation")

        # ─── KROK 5: Phrase Hierarchy ───
        yield emit("step", {"step": 5, "name": "Phrase Hierarchy", "status": "running"})
        hier_result = brajen_call("get", f"/api/project/{project_id}/phrase_hierarchy")
        if hier_result["ok"]:
            hier = hier_result["data"]
            strategy = (hier.get("strategies") or {})
            yield emit("step", {"step": 5, "name": "Phrase Hierarchy", "status": "done",
                                "detail": json.dumps(strategy, ensure_ascii=False)[:200]})
        else:
            yield emit("step", {"step": 5, "name": "Phrase Hierarchy", "status": "warning",
                                "detail": "Nie udało się pobrać — kontynuuję"})

        # ─── KROK 6: Batch Loop ───
        yield emit("step", {"step": 6, "name": "Batch Loop", "status": "running",
                            "detail": f"0/{total_batches} batchy"})

        for batch_num in range(1, total_batches + 1):
            # Użyj API batch_number (po pre_batch_info) zamiast loop counter
            # bo API auto-inkrementuje na podstawie zapisanych batchy
            yield emit("batch_start", {"batch": batch_num, "total": total_batches})
            yield emit("log", {"msg": f"── BATCH {batch_num}/{total_batches} ──"})

            # 6a: Get pre_batch_info (with retry)
            yield emit("log", {"msg": f"GET /pre_batch_info"})
            pre_result = None
            for _pb_attempt in range(3):
                pre_result = brajen_call("get", f"/api/project/{project_id}/pre_batch_info")
                if pre_result["ok"]:
                    break
                yield emit("log", {"msg": f"⚠️ pre_batch_info attempt {_pb_attempt+1}/3 failed: {pre_result.get('error', '')[:80]}"})
                time.sleep(3 + _pb_attempt * 3)
            if not pre_result or not pre_result["ok"]:
                yield emit("log", {"msg": f"❌ pre_batch_info failed po 3 próbach — skip batch {batch_num}"})
                continue

            pre_batch = pre_result["data"]
            # CRITICAL FIX: API zwraca batch_type "FINAL" dla ostatniego batcha,
            # ale enhanced_pre_batch.py remapuje go na "FAQ" wewnętrznie.
            # Custom GPT czytał enhanced.batch_type ("FAQ") + Knowledge Base.
            # Musimy użyć enhanced.batch_type (który jest poprawny) lub remapować "FINAL"→"FAQ".
            enhanced_data_raw = pre_batch.get("enhanced") or {}
            batch_type = enhanced_data_raw.get("batch_type") or pre_batch.get("batch_type", "CONTENT")
            # Fallback: jeśli enhanced nie ma batch_type, a top-level = "FINAL" → to FAQ
            if batch_type == "FINAL":
                batch_type = "FAQ"

            # Użyj batch_number z API (auto-incremented) dla dokładności
            api_batch_num = pre_batch.get("batch_number", batch_num)

            # Get current H2 — enhanced.current_h2 is most reliable (remapped for FAQ)
            h2_remaining = (pre_batch.get("h2_remaining") or [])
            semantic_plan = pre_batch.get("semantic_batch_plan") or {}
            enhanced_h2 = enhanced_data_raw.get("current_h2")
            
            if enhanced_h2:
                current_h2 = enhanced_h2
            elif h2_remaining:
                current_h2 = h2_remaining[0]
            elif semantic_plan.get("h2"):
                current_h2 = semantic_plan["h2"]
            else:
                current_h2 = h2_structure[min(batch_num-1, len(h2_structure)-1)]

            must_kw = (pre_batch.get("keywords") or {}).get("basic_must_use", [])
            ext_kw = (pre_batch.get("keywords") or {}).get("extended_this_batch", [])
            stop_kw = (pre_batch.get("keyword_limits") or {}).get("stop_keywords", [])

            yield emit("log", {"msg": f"Typ: {batch_type} | H2: {current_h2}"})
            yield emit("log", {"msg": f"MUST: {len(must_kw)} | EXTENDED: {len(ext_kw)} | STOP: {len(stop_kw)}"})

            # Emit batch instructions for UI display
            caution_kw = (pre_batch.get("keyword_limits") or {}).get("caution_keywords", [])
            batch_length_info = pre_batch.get("batch_length") or {}
            enhanced_data = enhanced_data_raw  # Already fetched above
            
            # FIX: Normalize coverage — extract percent values from nested objects
            raw_coverage = pre_batch.get("coverage") or {}
            def _norm_cov(v):
                """Extract numeric percent from coverage value (could be dict or number)."""
                if isinstance(v, (int, float)):
                    return round(v, 1)
                if isinstance(v, dict):
                    return round(v.get("percent", v.get("pct", v.get("value", 0))), 1)
                return 0
            
            normalized_coverage = {}
            for ck, cv in raw_coverage.items():
                normalized_coverage[ck] = _norm_cov(cv)

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
                    "coverage": normalized_coverage,
                "density": pre_batch.get("density") or {},
                # ─── Boolean flags ───
                "has_gpt_instructions": bool(pre_batch.get("gpt_instructions_v39")),
                "has_gpt_prompt": bool(pre_batch.get("gpt_prompt")),
                "has_article_memory": bool(pre_batch.get("article_memory")),
                "has_enhanced": bool(enhanced_data),
                "has_style": bool(pre_batch.get("style_instructions")),
                "has_legal": bool((pre_batch.get("legal_context") or {}).get("active")),
                "has_medical": bool((pre_batch.get("medical_context") or {}).get("active")),
                "experience_markers": bool(enhanced_data.get("experience_markers")),
                "continuation_context": bool(enhanced_data.get("continuation_context")),
                "has_causal_context": bool(enhanced_data.get("causal_context")),
                "has_information_gain": bool(enhanced_data.get("information_gain")),
                "has_smart_instructions": bool(enhanced_data.get("smart_instructions")),
                "has_phrase_hierarchy": bool(enhanced_data.get("phrase_hierarchy")),
                "has_continuation_v39": bool(pre_batch.get("continuation_v39")),
                # ─── Semantic plan ───
                "semantic_plan": {
                    "h2": (pre_batch.get("semantic_batch_plan") or {}).get("h2"),
                    "profile": (pre_batch.get("semantic_batch_plan") or {}).get("profile"),
                    "score": (pre_batch.get("semantic_batch_plan") or {}).get("score")
                },
                # ─── Entities & Relations ───
                "entities_to_define": (enhanced_data.get("entities_to_define") or [])[:8],
                "relations_to_establish": (enhanced_data.get("relations_to_establish") or [])[:8],
                # ─── PAA for batch ───
                "paa_from_serp": (enhanced_data.get("paa_from_serp") or [])[:5],
                # ─── Keyword ratio ───
                "main_keyword_ratio": (pre_batch.get("main_keyword") or {}).get("ratio"),
                # ─── Intro guidance ───
                "intro_guidance": pre_batch.get("intro_guidance", "") if batch_type == "INTRO" else "",
                # ─── Batch length detail ───
                "batch_length_detail": {
                    "suggested_min": batch_length_info.get("suggested_min"),
                    "suggested_max": batch_length_info.get("suggested_max"),
                    "complexity_score": batch_length_info.get("complexity_score"),
                    "length_profile": batch_length_info.get("length_profile"),
                    "snippet_required": batch_length_info.get("snippet_required", False),
                },
                # ─── Article Memory summary ───
                "article_memory_summary": _summarize_article_memory(pre_batch.get("article_memory")),
                # ─── Style instructions ───
                "style_summary": _summarize_style(pre_batch.get("style_instructions")),
                # ─── Enhanced sub-fields ───
                "causal_context_preview": (enhanced_data.get("causal_context") or "")[:300],
                "information_gain_preview": (enhanced_data.get("information_gain") or "")[:300],
                "smart_instructions_preview": (enhanced_data.get("smart_instructions_formatted") or enhanced_data.get("smart_instructions") or "")[:300],
                # ─── Phrase hierarchy ───
                "phrase_hierarchy_data": {
                    "roots_covered": (enhanced_data.get("phrase_hierarchy") or {}).get("roots_covered", []),
                    "strategy": (enhanced_data.get("phrase_hierarchy") or {}).get("strategy", ""),
                } if enhanced_data.get("phrase_hierarchy") else None,
                # ─── Legal/Medical context preview ───
                "legal_context_preview": _summarize_ymyl_context(pre_batch.get("legal_context")),
                "medical_context_preview": _summarize_ymyl_context(pre_batch.get("medical_context")),
                # ─── Continuation context ───
                "continuation_preview": _summarize_continuation(pre_batch.get("continuation_v39")),
                # ─── gpt_instructions_v39 preview ───
                "gpt_instructions_preview": (pre_batch.get("gpt_instructions_v39") or "")[:400],
            })

            # 6c: Generate text
            has_instructions = bool(pre_batch.get("gpt_instructions_v39"))
            has_enhanced = bool(pre_batch.get("enhanced"))
            has_memory = bool(pre_batch.get("article_memory"))
            has_causal = bool(enhanced_data.get("causal_context"))
            has_smart = bool(enhanced_data.get("smart_instructions"))
            yield emit("log", {"msg": f"Generuję tekst przez {ANTHROPIC_MODEL}... [instr={'✅' if has_instructions else '❌'} enhanced={'✅' if has_enhanced else '❌'} memory={'✅' if has_memory else '❌'} causal={'✅' if has_causal else '—'} smart={'✅' if has_smart else '—'}]"})

            if batch_type == "FAQ":
                # FAQ batch: first analyze PAA
                paa_result = brajen_call("get", f"/api/project/{project_id}/paa/analyze")
                paa_data = paa_result["data"] if paa_result["ok"] else {}
                text = generate_faq_text(paa_data, pre_batch)
            else:
                text = generate_batch_text(
                    pre_batch, current_h2, batch_type,
                    pre_batch.get("article_memory")
                )

            word_count = len(text.split())
            yield emit("log", {"msg": f"Wygenerowano {word_count} słów"})

            # 6d-6g: Submit with retry logic per documentation:
            # FIX_AND_RETRY — napraw issues[] / exceeded keywords, wyślij ponownie
            # REWRITE — poważne problemy, wygeneruj tekst od nowa
            # Po 2× FIX_AND_RETRY → forced=true akceptuje mimo przekroczeń
            batch_accepted = False
            fix_retry_count = 0
            rewrite_count = 0
            MAX_FIX_RETRIES = 2
            MAX_REWRITES = 1

            while not batch_accepted:
                forced = (fix_retry_count >= MAX_FIX_RETRIES)
                submit_data = {"text": text}
                if forced:
                    submit_data["forced"] = True
                    yield emit("log", {"msg": "⚡ Forced mode ON — wymuszam zapis (po 2× FIX_AND_RETRY)"})

                yield emit("log", {"msg": f"POST /batch_simple (fix={fix_retry_count}, rewrite={rewrite_count}, forced={forced})"})
                submit_result = brajen_call("post", f"/api/project/{project_id}/batch_simple", submit_data)

                if not submit_result["ok"]:
                    # Retry submit up to 2 times on failure
                    _submit_ok = False
                    for _sub_retry in range(2):
                        yield emit("log", {"msg": f"⚠️ Submit retry {_sub_retry+1}/2 (error: {submit_result.get('error', '')[:80]})"})
                        time.sleep(5 + _sub_retry * 5)
                        submit_result = brajen_call("post", f"/api/project/{project_id}/batch_simple", submit_data)
                        if submit_result["ok"]:
                            _submit_ok = True
                            break
                    if not _submit_ok:
                        yield emit("log", {"msg": f"❌ Submit failed po retries — skip batch {batch_num}"})
                        break

                result = submit_result["data"]
                accepted = result.get("accepted", False)
                action = result.get("action", "CONTINUE")
                quality = (result.get("quality") or {})
                depth = result.get("depth_score")
                exceeded = (result.get("exceeded_keywords") or [])
                issues = (result.get("issues") or [])

                yield emit("batch_result", {
                    "batch": batch_num,
                    "accepted": accepted,
                    "action": action,
                    "quality_score": quality.get("score"),
                    "quality_grade": quality.get("grade"),
                    "depth_score": depth,
                    "exceeded": [e.get("keyword", "") for e in exceeded] if exceeded else [],
                    "issues": [i.get("description", str(i)) if isinstance(i, dict) else str(i) for i in issues[:5]]
                })

                if accepted:
                    batch_accepted = True
                    yield emit("log", {"msg": f"✅ Batch {batch_num} accepted! Score: {quality.get('score')}/100"})
                    break

                # Forced mode — akceptujemy wynik
                if forced:
                    batch_accepted = True
                    yield emit("log", {"msg": f"⚠️ Batch {batch_num} wymuszony (forced) — kontynuuję"})
                    break

                # === Obsługa akcji z MoE ===
                if action == "REWRITE" and rewrite_count < MAX_REWRITES:
                    # REWRITE: pełna regeneracja tekstu z uwzględnieniem issues
                    rewrite_count += 1
                    issues_desc = "; ".join(
                        i.get("description", str(i)) if isinstance(i, dict) else str(i)
                        for i in issues[:5]
                    )
                    yield emit("log", {"msg": f"🔄 REWRITE #{rewrite_count} — regeneruję tekst (issues: {issues_desc[:200]})"})

                    # Regeneracja: dodaj issues jako kontekst do generatora
                    rewrite_context = pre_batch.copy() if isinstance(pre_batch, dict) else {}
                    rewrite_issues = {
                        "rewrite_reason": action,
                        "issues_to_fix": issues_desc,
                        "attempt": rewrite_count
                    }
                    rewrite_context["rewrite_context"] = rewrite_issues

                    if batch_type == "FAQ":
                        paa_result_rw = brajen_call("get", f"/api/project/{project_id}/paa/analyze")
                        paa_data_rw = paa_result_rw["data"] if paa_result_rw["ok"] else {}
                        text = generate_faq_text(paa_data_rw, rewrite_context)
                    else:
                        text = generate_batch_text(
                            rewrite_context, current_h2, batch_type,
                            rewrite_context.get("article_memory")
                        )
                    word_count = len(text.split())
                    yield emit("log", {"msg": f"Rewrite: wygenerowano {word_count} słów"})
                    continue

                elif action in ("FIX_AND_RETRY", "REWRITE"):
                    # FIX_AND_RETRY: napraw exceeded keywords za pomocą synonimów
                    # (REWRITE po wyczerpaniu limitu rewrites też trafia tutaj)
                    fix_retry_count += 1
                    fixes_applied = 0

                    # 1. Napraw exceeded keywords (zamiana na synonimy)
                    # FIX: Filtruj absurdalne synonimy
                    _BAD_SYNONYMS = {
                        'dzierżawić', 'przysposobić', 'zakład przeprowadzeniowy',
                        'pozyskiwać', 'niegdyś', 'iżby', 'albowiem', 'atoli',
                        'aczkolwiek', 'wszelako', 'mianowicie', 'jednakowoż',
                    }
                    if exceeded:
                        for exc in exceeded:
                            kw = exc.get("keyword", "")
                            synonyms = (exc.get("use_instead") or exc.get("synonyms") or [])
                            # Filter to reasonable synonyms only
                            good_syns = [
                                s for s in synonyms 
                                if isinstance(s, str) and s.lower() not in _BAD_SYNONYMS
                                and len(s) < len(kw) * 3  # not absurdly long
                                and not any(c in s for c in '{}[]();')  # no code
                            ]
                            if good_syns and kw and kw in text:
                                syn = good_syns[0]
                                text = text.replace(kw, syn, 1)
                                fixes_applied += 1
                                yield emit("log", {"msg": f"🔧 Zamiana: '{kw}' → '{syn}'"})
                            elif kw and kw in text and synonyms:
                                yield emit("log", {"msg": f"⚠️ Pominięto złą zamianę: '{kw}' → '{synonyms[0]}'"})
                                fixes_applied += 1  # Count as handled to avoid infinite loop

                    # 2. Loguj issues[] z MoE (nawet jeśli nie exceeded)
                    if issues and not exceeded:
                        for iss in issues[:3]:
                            desc = iss.get("description", str(iss)) if isinstance(iss, dict) else str(iss)
                            yield emit("log", {"msg": f"📋 Issue: {desc[:150]}"})

                    yield emit("log", {"msg": f"🔄 FIX_AND_RETRY #{fix_retry_count} — naprawiono {fixes_applied} fraz"})
                    continue

                else:
                    # Nieznana akcja — break
                    yield emit("log", {"msg": f"⚠️ Nieznana akcja: {action} — kontynuuję"})
                    break

            # Save FAQ if applicable
            if batch_type == "FAQ" and batch_accepted:
                yield emit("log", {"msg": "Zapisuję FAQ/PAA (Schema.org)..."})
                questions = _extract_faq_questions(text)
                if questions:
                    brajen_call("post", f"/api/project/{project_id}/paa/save", {"questions": questions})
                    job["faq_saved"] = True

            yield emit("step", {"step": 6, "name": "Batch Loop", "status": "running",
                                "detail": f"{batch_num}/{total_batches} batchy"})
            # 🧹 Free batch memory after each iteration
            gc.collect()

        yield emit("step", {"step": 6, "name": "Batch Loop", "status": "done",
                            "detail": f"{total_batches}/{total_batches} batchy"})

        # ─── KROK 7: PAA Check ───
        # FIX: Sprawdź czy FAQ nie zostało już zapisane w KROK 6 (batch loop)
        yield emit("step", {"step": 7, "name": "PAA Analyze & Save", "status": "running"})

        if job.get("faq_saved"):
            yield emit("log", {"msg": "FAQ zapisane w batch loop — pomijam duplikację"})
            yield emit("step", {"step": 7, "name": "PAA Analyze & Save", "status": "done",
                                "detail": "FAQ zapisane w KROK 6"})
        else:
            paa_check = brajen_call("get", f"/api/project/{project_id}/paa")
            if not paa_check["ok"] or not (paa_check.get("data") or {}).get("paa_section"):
                yield emit("log", {"msg": "Brak FAQ — analizuję PAA i generuję..."})
                paa_analyze = brajen_call("get", f"/api/project/{project_id}/paa/analyze")
                if paa_analyze["ok"]:
                    faq_text = generate_faq_text(paa_analyze["data"])
                    brajen_call("post", f"/api/project/{project_id}/batch_simple", {"text": faq_text})
                    questions = _extract_faq_questions(faq_text)
                    if questions:
                        brajen_call("post", f"/api/project/{project_id}/paa/save", {"questions": questions})
                yield emit("step", {"step": 7, "name": "PAA Analyze & Save", "status": "done"})
            else:
                yield emit("step", {"step": 7, "name": "PAA Analyze & Save", "status": "done",
                                    "detail": "FAQ już zapisane"})

        # ─── KROK 8: Final Review ───
        yield emit("step", {"step": 8, "name": "Final Review", "status": "running"})
        yield emit("log", {"msg": "GET /final_review..."})
        final_result = brajen_call("get", f"/api/project/{project_id}/final_review")
        if final_result["ok"]:
            final = final_result["data"]
            final_score = final.get("quality_score", final.get("score", "?"))
            final_status = final.get("status", "?")
            missing_kw = (final.get("missing_keywords") or [])
            issues = (final.get("issues") or [])

            yield emit("final_review", {
                "score": final_score,
                "status": final_status,
                "missing_keywords_count": len(missing_kw) if isinstance(missing_kw, list) else 0,
                "missing_keywords": missing_kw[:10] if isinstance(missing_kw, list) else [],
                "issues_count": len(issues) if isinstance(issues, list) else 0,
                "issues": issues[:5] if isinstance(issues, list) else []
            })

            yield emit("step", {"step": 8, "name": "Final Review", "status": "done",
                                "detail": f"Score: {final_score}/100 | Status: {final_status}"})

            # YMYL validation
            if is_legal:
                yield emit("log", {"msg": "Walidacja prawna..."})
                full_art = brajen_call("get", f"/api/project/{project_id}/full_article")
                if full_art["ok"] and full_art["data"].get("full_article"):
                    brajen_call("post", "/api/legal/validate",
                               {"full_text": full_art["data"]["full_article"]})
            if is_medical:
                yield emit("log", {"msg": "Walidacja medyczna..."})
                full_art = brajen_call("get", f"/api/project/{project_id}/full_article")
                if full_art["ok"] and full_art["data"].get("full_article"):
                    brajen_call("post", "/api/medical/validate",
                               {"full_text": full_art["data"]["full_article"]})
        else:
            yield emit("step", {"step": 8, "name": "Final Review", "status": "warning",
                                "detail": "Nie udało się — kontynuuję"})

        # ─── KROK 9: Editorial Review ───
        yield emit("step", {"step": 9, "name": "Editorial Review", "status": "running"})
        yield emit("log", {"msg": "POST /editorial_review — to może chwilę potrwać..."})

        editorial_result = brajen_call("post", f"/api/project/{project_id}/editorial_review")
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
                "feedback": (ed.get("editorial_feedback") or {})
            })

            if rollback.get("triggered"):
                yield emit("log", {"msg": f"⚠️ ROLLBACK: {rollback.get('reason', 'unknown')}"})

            yield emit("step", {"step": 9, "name": "Editorial Review", "status": "done", "detail": detail})
        else:
            yield emit("step", {"step": 9, "name": "Editorial Review", "status": "warning",
                                "detail": "Nie udało się — artykuł bez recenzji"})

        # ─── S1 COMPLIANCE CHECK (after editorial, before export) ───
        yield emit("log", {"msg": "📊 Sprawdzam spełnienie elementów S1 w artykule..."})
        try:
            full_art_check = brajen_call("get", f"/api/project/{project_id}/full_article")
            article_text_for_compliance = ""
            if full_art_check["ok"]:
                article_text_for_compliance = full_art_check["data"].get("full_article", "")

            ed_data_for_compliance = editorial_result["data"] if editorial_result.get("ok") else {}
            compliance = _build_s1_compliance(s1_for_compliance, article_text_for_compliance, ed_data_for_compliance)
            if compliance:
                yield emit("s1_compliance", compliance)
                summ = compliance.get("summary", {})
                yield emit("log", {"msg": f"S1 Compliance: Encje {summ.get('entities','?')} | Must {summ.get('entities_must','?')} | Triplets {summ.get('causal_triplets','?')} | Gaps {summ.get('content_gaps','?')} | N-gramy {summ.get('ngrams','?')} | PAA {summ.get('paa','?')} | Semantic {summ.get('semantic_keyphrases','?')}"})
        except Exception as e:
            yield emit("log", {"msg": f"⚠️ S1 compliance check error: {str(e)[:200]}"})

        # ─── KROK 10: Export ───
        yield emit("step", {"step": 10, "name": "Export", "status": "running"})

        # FIX: Sprawdź gotowość przed eksportem (dokumentacja: GET /export_status)
        export_status = brajen_call("get", f"/api/project/{project_id}/export_status")
        if export_status["ok"]:
            es_data = export_status["data"]
            # API zwraca: has_content, word_count, editorial_review.done — NIE "ready"
            has_content = es_data.get("has_content", False)
            editorial_done = (es_data.get("editorial_review") or {}).get("done", False)
            word_count_export = es_data.get("word_count", 0)

            yield emit("log", {"msg": f"Export status: content={has_content}, editorial={editorial_done}, words={word_count_export}"})

            if not has_content:
                yield emit("log", {"msg": "⚠️ Export: brak treści — czekam 5s i ponawiam..."})
                time.sleep(5)
                export_status = brajen_call("get", f"/api/project/{project_id}/export_status")
        else:
            yield emit("log", {"msg": "Export status endpoint niedostępny — kontynuuję eksport"})

        # Get full article
        full_result = brajen_call("get", f"/api/project/{project_id}/full_article")
        if full_result["ok"]:
            full = full_result["data"]
            stats = (full.get("stats") or {})
            coverage = (full.get("coverage") or {})

            yield emit("article", {
                "text": full.get("full_article", ""),
                "word_count": stats.get("word_count", 0),
                "h2_count": stats.get("h2_count", 0),
                "h3_count": stats.get("h3_count", 0),
                "coverage": coverage,
                "density": (full.get("density") or {})
            })

        # Export HTML
        export_result = brajen_call("get", f"/api/project/{project_id}/export/html")
        if export_result["ok"]:
            if export_result.get("binary"):
                export_path = f"/tmp/brajen_export_{project_id}.html"
                with open(export_path, "wb") as f:
                    f.write(export_result["content"])
                job["export_html"] = export_path
            else:
                content = export_result["data"] if isinstance(export_result["data"], str) else json.dumps(export_result["data"])
                export_path = f"/tmp/brajen_export_{project_id}.html"
                with open(export_path, "w", encoding="utf-8") as f:
                    f.write(content)
                job["export_html"] = export_path
        del export_result  # Free binary content from memory

        # Export DOCX
        export_docx = brajen_call("get", f"/api/project/{project_id}/export/docx")
        if export_docx["ok"] and export_docx.get("binary"):
            export_path = f"/tmp/brajen_export_{project_id}.docx"
            with open(export_path, "wb") as f:
                f.write(export_docx["content"])
            job["export_docx"] = export_path
        del export_docx  # Free binary content from memory

        yield emit("step", {"step": 10, "name": "Export", "status": "done",
                            "detail": "HTML + DOCX gotowe"})

        # ─── DONE ───
        job["status"] = "done"
        yield emit("done", {
            "project_id": project_id,
            "word_count": stats.get("word_count", 0) if full_result["ok"] else 0,
            "exports": {
                "html": bool(job.get("export_html")),
                "docx": bool(job.get("export_docx"))
            }
        })
        # Free large data from memory — keep only export paths
        for k in ("basic_terms", "extended_terms", "h2_structure"):
            job.pop(k, None)
        gc.collect()

    except Exception as e:
        logger.exception(f"Workflow error: {e}")
        job["status"] = "error"
        yield emit("workflow_error", {"step": 0, "msg": f"Unexpected error: {str(e)}"})
        gc.collect()

# ============================================================
# ROUTES
# ============================================================
@app.route("/")
@login_required
def index():
    return render_template("index.html", username=session.get("user", ""))


@app.route("/api/start", methods=["POST"])
@login_required
def start_workflow():
    """Start workflow and return job_id."""
    global _active_workflow_count
    
    # Cleanup old jobs to free memory
    _cleanup_old_jobs()
    
    # Concurrency limit — prevent OOM from parallel workflows
    with _jobs_lock:
        running = sum(1 for j in active_jobs.values() if j.get("status") == "running")
        if running >= MAX_CONCURRENT_WORKFLOWS:
            return jsonify({"error": f"⚠️ Już działa {running} workflow — poczekaj na zakończenie"}), 429
    
    data = request.json

    main_keyword = data.get("main_keyword", "").strip()
    if not main_keyword:
        return jsonify({"error": "Brak hasła głównego"}), 400

    mode = data.get("mode", "standard")
    h2_list = [h.strip() for h in (data.get("h2_structure") or []) if h.strip()]
    basic_terms = [t.strip() for t in (data.get("basic_terms") or []) if t.strip()]
    extended_terms = [t.strip() for t in (data.get("extended_terms") or []) if t.strip()]

    # H2 is now OPTIONAL — if empty, will be auto-generated from S1

    job_id = str(uuid.uuid4())[:8]
    active_jobs[job_id] = {
        "main_keyword": main_keyword,
        "mode": mode,
        "h2_structure": h2_list,
        "basic_terms": basic_terms,
        "extended_terms": extended_terms,
        "status": "running",
        "created": datetime.now().isoformat()
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
            # No event for {keepalive_interval}s — send SSE comment to keep connection alive
            yield ": keepalive\n\n"


@app.route("/api/stream/<job_id>")
@login_required
def stream_workflow(job_id):
    """SSE endpoint for workflow progress with keepalive."""
    job = active_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    data = job

    # Pass basic/extended through query params from frontend
    basic_terms = request.args.get("basic_terms", "")
    extended_terms = request.args.get("extended_terms", "")

    def generate_with_terms():
        bt = json.loads(basic_terms) if basic_terms else (data.get("basic_terms") or [])
        et = json.loads(extended_terms) if extended_terms else (data.get("extended_terms") or [])
        
        # FIX: Prevent workflow restart on SSE reconnect
        if data.get("_workflow_started"):
            yield f"event: log\ndata: {json.dumps({'msg': '⚠️ SSE reconnect — workflow już działa, zamykam duplikat'}, ensure_ascii=False)}\n\n"
            yield f"event: workflow_error\ndata: {json.dumps({'step': 0, 'msg': 'SSE reconnected but workflow already running. Check logs for progress.'})}\n\n"
            return
        data["_workflow_started"] = True
        
        try:
            yield from run_workflow_sse(
                job_id=job_id,
                main_keyword=data["main_keyword"],
                mode=data["mode"],
                h2_structure=data["h2_structure"],
                basic_terms=bt,
                extended_terms=et
            )
        finally:
            # Memory cleanup after workflow ends (success or error)
            data["_workflow_started"] = False
            data["status"] = "done"
            # Remove large data from job dict to free memory
            for key in ["basic_terms", "extended_terms", "h2_structure"]:
                data.pop(key, None)
            gc.collect()
            logger.info(f"🧹 Workflow {job_id} finished — memory released")

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
    """Health check with memory info."""
    import resource
    mem_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # KB→MB on Linux
    running = sum(1 for j in active_jobs.values() if j.get("status") == "running")
    return jsonify({
        "status": "ok",
        "version": "45.2.3",
        "memory_mb": round(mem_mb, 1),
        "active_jobs": len(active_jobs),
        "running_workflows": running
    })


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("DEBUG", "false").lower() == "true")
