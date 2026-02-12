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
import threading
import queue
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, jsonify, Response,
    session, redirect, url_for, stream_with_context, send_file
)
import requests as http_requests
import anthropic
from prompt_builder import (
    build_system_prompt, build_user_prompt,
    build_faq_system_prompt, build_faq_user_prompt,
    build_h2_plan_system_prompt, build_h2_plan_user_prompt
)

# Optional: OpenAI
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

import re as _re

# AI Middleware — inteligentne czyszczenie danych i smart retry
from ai_middleware import (
    process_s1_for_pipeline,
    smart_retry_batch,
    should_use_smart_retry,
    synthesize_article_memory,
    ai_synthesize_memory
)

# ================================================================
# 🗑️ CSS/JS GARBAGE FILTER — czyści śmieci z S1 danych
# ================================================================
_CSS_GARBAGE_PATTERNS = _re.compile(
    r'(?:'
    r'webkit|moz-|ms-flex|align-items|display\s*:|flex-pack|'
    r'font-family|background-color|border-bottom|text-shadow|'
    r'position\s*:|padding\s*:|margin\s*:|transform\s*:|'
    r'transition|scrollbar|\.uk-|\.et_pb_|\.rp-|'
    r'min-width|max-width|overflow|z-index|opacity|'
    r'hover\{|active\{|:after|:before|calc\(|'
    r'woocommerce|gutters|inline-flex|box-pack|'
    r'data-[a-z]|aria-|role=|tabindex|'
    r'^\w+\.\w+$|'
    r'[{};]'
    r')',
    _re.IGNORECASE
)

_CSS_NGRAM_EXACT = {
    "min width", "width min", "ms flex", "align items", "flex pack",
    "box pack", "table table", "decoration decoration", "inline flex",
    "webkit box", "webkit text", "moz box", "moz flex",
    "box align", "flex align", "flex direction", "flex wrap",
    "justify content", "text decoration", "font weight", "font size",
    "line height", "border radius", "box shadow", "text align",
    "text transform", "letter spacing", "word spacing", "white space",
    "min height", "max height", "list style", "vertical align",
    "before before", "data widgets", "widgets footer", "footer widget",
    "focus focus", "root root", "not not",
}

_CSS_ENTITY_WORDS = {
    "inline", "button", "active", "hover", "flex", "grid", "block",
    "none", "inherit", "auto", "hidden", "visible", "relative",
    "absolute", "fixed", "static", "center", "wrap", "nowrap",
    "bold", "normal", "italic", "transparent", "solid", "dotted",
    "pointer", "default", "disabled", "checked", "focus",
    "where", "not", "root", "before", "after",
}

def _is_css_garbage(text):
    if not text or not isinstance(text, str):
        return True
    text = text.strip()
    if len(text) < 2:
        return True
    special = sum(1 for c in text if c in '{}:;()[]<>=#.@')
    if len(text) > 0 and special / len(text) > 0.15:
        return True
    if text.lower() in _CSS_NGRAM_EXACT:
        return True
    if text.lower() in _CSS_ENTITY_WORDS:
        return True
    return bool(_CSS_GARBAGE_PATTERNS.search(text))

def _filter_entities(entities):
    if not entities:
        return []
    clean = []
    for ent in entities:
        if isinstance(ent, dict):
            text = ent.get("text", "") or ent.get("entity", "") or ent.get("name", "")
            if not _is_css_garbage(text):
                clean.append(ent)
        elif isinstance(ent, str):
            if not _is_css_garbage(ent):
                clean.append(ent)
    return clean

def _filter_ngrams(ngrams):
    if not ngrams:
        return []
    clean = []
    for ng in ngrams:
        text = ng.get("ngram", ng) if isinstance(ng, dict) else str(ng)
        if not _is_css_garbage(text):
            clean.append(ng)
    return clean

def _filter_h2_patterns(patterns):
    if not patterns:
        return []
    clean = []
    for p in patterns:
        text = p if isinstance(p, str) else (p.get("pattern", "") if isinstance(p, dict) else str(p))
        if not _is_css_garbage(text) and len(text) > 3:
            clean.append(p)
    return clean


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

# Store active jobs in memory (for SSE)
active_jobs = {}


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
    v45.3: Uses prompt_builder for readable prompts instead of json.dumps().
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    
    # Extract S1 insights for fallback
    suggested_h2s = (s1_data.get("content_gaps") or {}).get("suggested_new_h2s", [])
    
    # Parse user phrases (strip ranges) — for topic context only
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

    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        temperature=0.5
    )
    
    response_text = response.content[0].text.strip()
    
    # Parse JSON response
    try:
        clean = response_text.replace("```json", "").replace("```", "").strip()
        h2_list = json.loads(clean)
        if isinstance(h2_list, list) and len(h2_list) >= 2:
            return h2_list
    except (json.JSONDecodeError, ValueError):
        pass
    
    # Fallback: extract lines that look like H2s
    h2_lines = [l.strip().strip('"').strip("'").strip(",").strip('"') 
             for l in response_text.split("\n") if l.strip() and not l.strip().startswith("[") and not l.strip().startswith("]")]
    if h2_lines:
        return h2_lines
    
    # Ultimate fallback
    fallback = suggested_h2s[:7] + ["Najczęściej zadawane pytania"] if suggested_h2s else [main_keyword, "Najczęściej zadawane pytania"]
    return fallback



# ============================================================
# TEXT GENERATION (Claude + OpenAI)
# ============================================================
def generate_batch_text(pre_batch, h2, batch_type, article_memory=None, engine="claude"):
    """Generate batch text using optimized prompts built from pre_batch data.
    
    v45.3: Replaces raw json.dumps() with structured natural language prompts
    that Claude can follow effectively. Uses prompt_builder module.
    """
    system_prompt = build_system_prompt(pre_batch, batch_type)
    user_prompt = build_user_prompt(pre_batch, h2, batch_type, article_memory)

    if engine == "openai" and OPENAI_API_KEY:
        return _generate_openai(system_prompt, user_prompt)
    else:
        return _generate_claude(system_prompt, user_prompt)


def _generate_claude(system_prompt, user_prompt):
    """Generate text using Anthropic Claude."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
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
    """Generate FAQ section using optimized prompts.
    
    v45.3: Uses prompt_builder for structured instructions instead of json.dumps().
    """
    system_prompt = build_faq_system_prompt(pre_batch)
    user_prompt = build_faq_user_prompt(paa_data, pre_batch)

    if engine == "openai" and OPENAI_API_KEY:
        return _generate_openai(system_prompt, user_prompt)
    else:
        return _generate_claude(system_prompt, user_prompt)


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
        # ─── KROK 1: S1 Analysis ───
        yield emit("step", {"step": 1, "name": "S1 Analysis", "status": "running"})
        yield emit("log", {"msg": f"POST /api/s1_analysis → {main_keyword}"})

        s1_result = brajen_call("post", "/api/s1_analysis", {"main_keyword": main_keyword})
        if not s1_result["ok"]:
            yield emit("workflow_error", {"step": 1, "msg": f"S1 Analysis failed: {s1_result.get('error', 'unknown')}"})
            return

        s1_raw = s1_result["data"]
        
        # ═══ AI MIDDLEWARE: Clean S1 data ═══
        s1 = process_s1_for_pipeline(s1_raw, main_keyword)
        cleanup_stats = s1.get("_cleanup_stats", {})
        if cleanup_stats.get("entities_removed", 0) > 0 or cleanup_stats.get("ngrams_removed", 0) > 0:
            yield emit("log", {"msg": f"🧹 AI Middleware: usunięto {cleanup_stats.get('entities_removed', 0)} śmieciowych encji, {cleanup_stats.get('ngrams_removed', 0)} n-gramów (garbage ratio: {cleanup_stats.get('garbage_ratio', 0):.0%})"})
            if cleanup_stats.get("ai_enriched"):
                yield emit("log", {"msg": "🤖 AI Middleware: wygenerowano uzupełniające insights z Haiku"})
        
        h2_patterns = len((s1.get("competitor_h2_patterns") or []))
        causal_count = (s1.get("causal_triplets") or {}).get("count", 0)
        gaps_count = (s1.get("content_gaps") or {}).get("total_gaps", 0)
        suggested_h2s = (s1.get("content_gaps") or {}).get("suggested_new_h2s", [])

        yield emit("step", {"step": 1, "name": "S1 Analysis", "status": "done",
                            "detail": f"{h2_patterns} H2 patterns | {causal_count} causal triplets | {gaps_count} content gaps"})
        
        # S1 data for UI — already cleaned by middleware, apply final filter for display
        raw_entities = (s1.get("entity_seo") or {}).get("top_entities", (s1.get("entity_seo") or {}).get("entities", []))[:20]
        raw_must_mention = (s1.get("entity_seo") or {}).get("must_mention_entities", [])[:10]
        raw_ngrams = (s1.get("ngrams") or [])[:30]
        raw_h2_patterns = (s1.get("competitor_h2_patterns") or [])[:30]

        # Lightweight display filter (middleware already did heavy lifting)
        clean_entities = _filter_entities(raw_entities)[:10]
        clean_must_mention = _filter_entities(raw_must_mention)[:5]
        clean_ngrams = _filter_ngrams(raw_ngrams)[:15]
        clean_h2_patterns = _filter_h2_patterns(raw_h2_patterns)[:20]

        # Add AI-extracted entities if available
        ai_entities = (s1.get("entity_seo") or {}).get("ai_extracted_entities", [])
        if ai_entities and len(clean_entities) < 5:
            yield emit("log", {"msg": f"🤖 Uzupełniam encje z AI: {', '.join(str(e) for e in ai_entities[:5])}"})

        yield emit("s1_data", {
            "h2_patterns_count": len(clean_h2_patterns),
            "causal_triplets_count": causal_count,
            "content_gaps_count": gaps_count,
            "suggested_h2s": suggested_h2s,
            "search_intent": s1.get("search_intent", ""),
            "competitor_h2_patterns": clean_h2_patterns,
            "content_gaps": (s1.get("content_gaps") or {}),
            "causal_triplets": (s1.get("causal_triplets") or {}).get("chains", (s1.get("causal_triplets") or {}).get("singles", []))[:10],
            "causal_instruction": (s1.get("causal_triplets") or {}).get("agent_instruction", ""),
            "paa_questions": (s1.get("paa") or s1.get("paa_questions") or [])[:10],
            "entity_seo": {
                "top_entities": clean_entities,
                "must_mention": clean_must_mention,
                "ai_extracted": ai_entities[:5] if ai_entities else []
            },
            "ngrams": clean_ngrams,
            "median_length": s1.get("median_length", 0),
            "competitive_summary": s1.get("_competitive_summary", "")
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

        # Filter entity_seo before sending to project (remove CSS garbage)
        filtered_entity_seo = (s1.get("entity_seo") or {}).copy()
        if "top_entities" in filtered_entity_seo:
            filtered_entity_seo["top_entities"] = _filter_entities(filtered_entity_seo["top_entities"])
        if "entities" in filtered_entity_seo:
            filtered_entity_seo["entities"] = _filter_entities(filtered_entity_seo["entities"])
        if "must_mention_entities" in filtered_entity_seo:
            filtered_entity_seo["must_mention_entities"] = _filter_entities(filtered_entity_seo["must_mention_entities"])

        project_payload = {
            "main_keyword": main_keyword,
            "mode": mode,
            "h2_structure": h2_structure,
            "keywords": keywords,
            "s1_data": {
                "causal_triplets": (s1.get("causal_triplets") or {}),
                "content_gaps": (s1.get("content_gaps") or {}),
                "entity_seo": filtered_entity_seo,
                "paa": (s1.get("paa") or []),
                "ngrams": _filter_ngrams((s1.get("ngrams") or [])[:30]),
                "competitor_h2_patterns": _filter_h2_patterns((s1.get("competitor_h2_patterns") or [])[:30])
            },
            "target_length": 3500 if mode == "standard" else 2000,
            "is_legal": is_legal,
            "is_medical": is_medical,
            "is_ymyl": is_legal or is_medical,
            "legal_context": legal_context,
            "medical_context": medical_context
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

        # ═══ AI MIDDLEWARE: Track accepted batches for memory ═══
        accepted_batches_log = []

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
            batch_type = pre_batch.get("batch_type", "CONTENT")

            # Get current H2 from API (most reliable) or fallback to our plan
            h2_remaining = (pre_batch.get("h2_remaining") or [])
            semantic_plan = pre_batch.get("semantic_batch_plan") or {}
            if h2_remaining:
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
                "intro_guidance": pre_batch.get("intro_guidance", "") if batch_type == "INTRO" else "",
                # v45 flags
                "has_causal_context": bool(enhanced_data.get("causal_context")),
                "has_information_gain": bool(enhanced_data.get("information_gain")),
                "has_smart_instructions": bool(enhanced_data.get("smart_instructions")),
                "has_phrase_hierarchy": bool(enhanced_data.get("phrase_hierarchy")),
                "has_continuation_v39": bool(pre_batch.get("continuation_v39"))
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
                # ═══ AI MIDDLEWARE: Article memory fallback ═══
                article_memory = pre_batch.get("article_memory")
                if not article_memory and accepted_batches_log:
                    # Backend didn't provide memory — synthesize locally
                    if len(accepted_batches_log) >= 3:
                        article_memory = ai_synthesize_memory(accepted_batches_log, main_keyword)
                        yield emit("log", {"msg": f"🧠 AI Middleware: synteza pamięci artykułu ({len(accepted_batches_log)} batchy)"})
                    else:
                        article_memory = synthesize_article_memory(accepted_batches_log)
                        if article_memory.get("topics_covered"):
                            yield emit("log", {"msg": f"🧠 Lokalna pamięć: {len(article_memory.get('topics_covered', []))} tematów"})
                
                text = generate_batch_text(
                    pre_batch, current_h2, batch_type,
                    article_memory
                )

            word_count = len(text.split())
            yield emit("log", {"msg": f"Wygenerowano {word_count} słów"})

            # 6d-6g: Submit with retry logic
            # Max 4 attempts: original + 2 AI smart retries + 1 forced
            max_attempts = 4
            batch_accepted = False

            for attempt in range(max_attempts):
                forced = (attempt == max_attempts - 1)  # Last attempt is always forced
                submit_data = {"text": text}
                if forced:
                    submit_data["forced"] = True
                    yield emit("log", {"msg": "⚡ Forced mode ON — wymuszam zapis"})

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
                    "exceeded": [e.get("keyword", "") for e in exceeded] if exceeded else []
                })

                if accepted:
                    batch_accepted = True
                    yield emit("log", {"msg": f"✅ Batch {batch_num} accepted! Score: {quality.get('score')}/100"})
                    # Track for memory
                    accepted_batches_log.append({
                        "text": text, "h2": current_h2, "batch_num": batch_num
                    })
                    break

                # Not accepted — decide retry strategy
                if forced:
                    yield emit("log", {"msg": f"⚠️ Batch {batch_num} w forced mode — kontynuuję"})
                    accepted_batches_log.append({
                        "text": text, "h2": current_h2, "batch_num": batch_num
                    })
                    break

                # ═══ AI MIDDLEWARE: Smart retry ═══
                if exceeded and should_use_smart_retry(result, attempt + 1):
                    yield emit("log", {"msg": f"🤖 AI Smart Retry — Haiku przepisuje tekst (zamiana {len(exceeded)} fraz)..."})
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
                else:
                    # Fallback: mechanical fix for non-exceeded issues
                    fixes_applied = 0
                    if exceeded:
                        for exc in exceeded:
                            kw = exc.get("keyword", "")
                            synonyms = (exc.get("use_instead") or exc.get("synonyms") or [])
                            if synonyms and kw and kw in text:
                                syn = synonyms[0] if isinstance(synonyms[0], str) else str(synonyms[0])
                                text = text.replace(kw, syn, 1)
                                fixes_applied += 1
                                yield emit("log", {"msg": f"🔧 Zamiana: '{kw}' → '{syn}'"})
                    yield emit("log", {"msg": f"🔄 Retry — naprawiono {fixes_applied} fraz, próba {attempt + 2}/{max_attempts}"})

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

        yield emit("step", {"step": 6, "name": "Batch Loop", "status": "done",
                            "detail": f"{total_batches}/{total_batches} batchy"})

        # ─── KROK 7: PAA Check ───
        yield emit("step", {"step": 7, "name": "PAA Analyze & Save", "status": "running"})
        paa_check = brajen_call("get", f"/api/project/{project_id}/paa")
        if not paa_check["ok"] or not (paa_check.get("data") or {}).get("paa_section"):
            yield emit("log", {"msg": "Brak FAQ — analizuję PAA i generuję..."})
            paa_analyze = brajen_call("get", f"/api/project/{project_id}/paa/analyze")
            if paa_analyze["ok"]:
                # Fetch pre_batch for FAQ context (stop keywords, style, memory)
                faq_pre = brajen_call("get", f"/api/project/{project_id}/pre_batch_info")
                faq_pre_batch = faq_pre["data"] if faq_pre.get("ok") else None
                faq_text = generate_faq_text(paa_analyze["data"], faq_pre_batch)
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

        # ─── KROK 10: Export ───
        yield emit("step", {"step": 10, "name": "Export", "status": "running"})

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
                # Save binary export
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

        # Export DOCX
        export_docx = brajen_call("get", f"/api/project/{project_id}/export/docx")
        if export_docx["ok"] and export_docx.get("binary"):
            export_path = f"/tmp/brajen_export_{project_id}.docx"
            with open(export_path, "wb") as f:
                f.write(export_docx["content"])
            job["export_docx"] = export_path

        yield emit("step", {"step": 10, "name": "Export", "status": "done",
                            "detail": "HTML + DOCX gotowe"})

        # ─── DONE ───
        yield emit("done", {
            "project_id": project_id,
            "word_count": stats.get("word_count", 0) if full_result["ok"] else 0,
            "exports": {
                "html": bool(job.get("export_html")),
                "docx": bool(job.get("export_docx"))
            }
        })

    except Exception as e:
        logger.exception(f"Workflow error: {e}")
        yield emit("workflow_error", {"step": 0, "msg": f"Unexpected error: {str(e)}"})


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
        yield from run_workflow_sse(
            job_id=job_id,
            main_keyword=data["main_keyword"],
            mode=data["mode"],
            h2_structure=data["h2_structure"],
            basic_terms=bt,
            extended_terms=et
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
    return jsonify({"status": "ok", "version": "45.2.2"})


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("DEBUG", "false").lower() == "true")
