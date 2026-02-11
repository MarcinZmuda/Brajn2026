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
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, jsonify, Response,
    session, redirect, url_for, stream_with_context, send_file
)
import requests as http_requests
import anthropic

# ============================================================
# CONFIG
# ============================================================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "brajen-seo-secret-" + str(uuid.uuid4()))

BRAJEN_API = os.environ.get("BRAJEN_API_URL", "https://master-seo-api.onrender.com")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-6")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "brajen2024")
APP_USERNAME = os.environ.get("APP_USERNAME", "brajen")

REQUEST_TIMEOUT = 120  # Render cold start can be slow
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
def brajen_call(method, endpoint, json_data=None):
    """Call BRAJEN API with retry logic for cold starts."""
    url = f"{BRAJEN_API}{endpoint}"

    for attempt in range(MAX_RETRIES):
        try:
            if method == "get":
                resp = http_requests.get(url, timeout=REQUEST_TIMEOUT)
            else:
                resp = http_requests.post(url, json=json_data, timeout=REQUEST_TIMEOUT)

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
# ANTHROPIC CLAUDE TEXT GENERATION
# ============================================================
def generate_batch_text(pre_batch, h2, batch_type, article_memory=None):
    """Generate batch text using Anthropic Claude API."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    gpt_instructions = pre_batch.get("gpt_instructions_v39", "")
    keywords_info = pre_batch.get("keywords", {})
    keyword_limits = pre_batch.get("keyword_limits", {})
    batch_length = pre_batch.get("batch_length", {})
    style = pre_batch.get("style_instructions", {})
    enhanced = pre_batch.get("enhanced", {})
    entity_seo = pre_batch.get("entity_seo", {})
    legal_ctx = pre_batch.get("legal_context")
    medical_ctx = pre_batch.get("medical_context")

    system_prompt = f"""Jesteś ekspertem SEO piszącym artykuł po polsku. Twoim zadaniem jest napisanie JEDNEJ sekcji artykułu.

INSTRUKCJE Z API (gpt_instructions_v39):
{gpt_instructions}

STYL:
{json.dumps(style, ensure_ascii=False, indent=2) if style else 'Naturalny, ekspercki ton.'}

ZASADY:
- Pisz TYLKO sekcję dla podanego H2
- Zaczynaj od: h2: {h2}
- Długość: {json.dumps(batch_length, ensure_ascii=False) if batch_length else '350-500 słów'}
- Passage-first writing: pod H2 pierwszy akapit = samodzielna odpowiedź (zdanie 1: odpowiedź/definicja, zdanie 2: konkret, zdanie 3: doprecyzowanie)
- NIE używaj fraz z listy STOP
- Używaj fraz MUST i EXTENDED naturalnie — nie upychaj
- CV (humanizacja): 0.35-0.45, zdania: 20% krótkie, 55% średnie, 25% długie
- Unikaj: "warto podkreślić", "należy pamiętać", "kluczowym aspektem", "w kontekście"
- Format: h2: Tytuł\\n\\nAkapit 1\\n\\nAkapit 2\\n\\nh3: Podsekcja (opcjonalnie)\\n\\nTreść

{f'ENTITY SEO: {json.dumps(entity_seo, ensure_ascii=False)[:500]}' if entity_seo else ''}
{f'KONTEKST PRAWNY (YMYL): {json.dumps(legal_ctx, ensure_ascii=False)[:500]}' if legal_ctx else ''}
{f'KONTEKST MEDYCZNY (YMYL): {json.dumps(medical_ctx, ensure_ascii=False)[:500]}' if medical_ctx else ''}"""

    user_prompt = f"""Napisz sekcję artykułu SEO.

H2: {h2}
Typ batcha: {batch_type}

FRAZY MUST (MUSISZ użyć w tym batchu):
{json.dumps(keywords_info.get('basic_must_use', []), ensure_ascii=False)}

FRAZY EXTENDED (użyj jeśli naturalnie pasują):
{json.dumps(keywords_info.get('extended_this_batch', []), ensure_ascii=False)}

FRAZY STOP (NIE UŻYWAJ — przekroczone!):
{json.dumps(keyword_limits.get('stop_keywords', []), ensure_ascii=False)}

FRAZY CAUTION (max 1× jeśli użyjesz):
{json.dumps(keyword_limits.get('caution_keywords', []), ensure_ascii=False)}

KONTEKST Z POPRZEDNICH BATCHY:
{json.dumps(article_memory, ensure_ascii=False)[:1000] if article_memory else 'Brak (pierwszy batch)'}

Zacznij tekst DOKŁADNIE od: h2: {h2}
Nie dodawaj niczego przed h2."""

    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=2000,
        system=system_prompt,
        messages=[
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.7
    )
    return response.content[0].text.strip()


def generate_faq_text(paa_data, pre_batch=None):
    """Generate FAQ section using PAA data via Anthropic Claude."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    paa_questions = paa_data.get("serp_paa", [])
    unused = paa_data.get("unused_keywords", {})
    avoid = paa_data.get("avoid_in_faq", [])
    instructions = paa_data.get("instructions", "")

    # Also get enhanced PAA from pre_batch if available
    enhanced_paa = []
    if pre_batch:
        enhanced = pre_batch.get("enhanced", {})
        enhanced_paa = enhanced.get("paa_from_serp", [])

    prompt = f"""Napisz sekcję FAQ dla artykułu SEO po polsku.

Pytania PAA z Google SERP:
{json.dumps(paa_questions, ensure_ascii=False)}

{f'Dodatkowe PAA: {json.dumps(enhanced_paa, ensure_ascii=False)}' if enhanced_paa else ''}

Nieużyte frazy (wpleć w odpowiedzi):
{json.dumps(unused, ensure_ascii=False)}

NIE powtarzaj tematów już pokrytych w artykule:
{json.dumps(avoid, ensure_ascii=False)}

{f'Instrukcje API: {instructions}' if instructions else ''}

FORMAT:
h2: Najczęściej zadawane pytania

h3: [Pytanie 1]
[Odpowiedź 60-120 słów]

h3: [Pytanie 2]
[Odpowiedź 60-120 słów]

...

Wybierz 4-6 najlepszych pytań. Zacznij DOKŁADNIE od: h2: Najczęściej zadawane pytania"""

    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.6
    )
    return response.content[0].text.strip()


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

        s1 = s1_result["data"]
        h2_patterns = len(s1.get("competitor_h2_patterns", []))
        causal_count = s1.get("causal_triplets", {}).get("count", 0)
        gaps_count = s1.get("content_gaps", {}).get("total_gaps", 0)
        suggested_h2s = s1.get("content_gaps", {}).get("suggested_new_h2s", [])

        yield emit("step", {"step": 1, "name": "S1 Analysis", "status": "done",
                            "detail": f"{h2_patterns} H2 patterns | {causal_count} causal triplets | {gaps_count} content gaps"})
        yield emit("s1_data", {
            "h2_patterns": h2_patterns,
            "causal_triplets": causal_count,
            "content_gaps": gaps_count,
            "suggested_h2s": suggested_h2s
        })

        # ─── KROK 2: YMYL Detection ───
        yield emit("step", {"step": 2, "name": "YMYL Detection", "status": "running"})

        legal_result = brajen_call("post", "/api/legal/detect", {"main_keyword": main_keyword})
        medical_result = brajen_call("post", "/api/medical/detect", {"main_keyword": main_keyword})

        is_legal = legal_result.get("data", {}).get("is_ymyl", False) if legal_result["ok"] else False
        is_medical = medical_result.get("data", {}).get("is_ymyl", False) if medical_result["ok"] else False

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

        project_payload = {
            "main_keyword": main_keyword,
            "mode": mode,
            "h2_structure": h2_structure,
            "keywords": keywords,
            "s1_data": {
                "causal_triplets": s1.get("causal_triplets", {}),
                "content_gaps": s1.get("content_gaps", {}),
                "entity_seo": s1.get("entity_seo", {}),
                "paa": s1.get("paa", [])
            },
            "target_length": 3500 if mode == "standard" else 2000
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
            strategy = hier.get("strategies", {})
            yield emit("step", {"step": 5, "name": "Phrase Hierarchy", "status": "done",
                                "detail": json.dumps(strategy, ensure_ascii=False)[:200]})
        else:
            yield emit("step", {"step": 5, "name": "Phrase Hierarchy", "status": "warning",
                                "detail": "Nie udało się pobrać — kontynuuję"})

        # ─── KROK 6: Batch Loop ───
        yield emit("step", {"step": 6, "name": "Batch Loop", "status": "running",
                            "detail": f"0/{total_batches} batchy"})

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
            current_h2 = h2_structure[min(batch_num-1, len(h2_structure)-1)]

            must_kw = pre_batch.get("keywords", {}).get("basic_must_use", [])
            ext_kw = pre_batch.get("keywords", {}).get("extended_this_batch", [])
            stop_kw = pre_batch.get("keyword_limits", {}).get("stop_keywords", [])

            yield emit("log", {"msg": f"Typ: {batch_type} | H2: {current_h2}"})
            yield emit("log", {"msg": f"MUST: {len(must_kw)} | EXTENDED: {len(ext_kw)} | STOP: {len(stop_kw)}"})

            # 6c: Generate text
            yield emit("log", {"msg": f"Generuję tekst przez {ANTHROPIC_MODEL}..."})

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

            # 6d-6g: Submit with retry logic
            retry_count = 0
            max_fix_retries = 2
            forced = False
            batch_accepted = False

            while retry_count <= max_fix_retries:
                submit_data = {"text": text}
                if forced:
                    submit_data["forced"] = True
                    yield emit("log", {"msg": "⚡ Forced mode ON"})

                yield emit("log", {"msg": f"POST /batch_simple (próba {retry_count + 1})"})
                submit_result = brajen_call("post", f"/api/project/{project_id}/batch_simple", submit_data)

                if not submit_result["ok"]:
                    yield emit("log", {"msg": f"❌ Submit error: {submit_result.get('error', '')[:100]}"})
                    break

                result = submit_result["data"]
                accepted = result.get("accepted", False)
                action = result.get("action", "CONTINUE")
                quality = result.get("quality", {})
                depth = result.get("depth_score")
                exceeded = result.get("exceeded_keywords", [])

                yield emit("batch_result", {
                    "batch": batch_num,
                    "accepted": accepted,
                    "action": action,
                    "quality_score": quality.get("score"),
                    "quality_grade": quality.get("grade"),
                    "depth_score": depth,
                    "exceeded": [e.get("keyword", "") for e in exceeded] if exceeded else []
                })

                if accepted and action == "CONTINUE":
                    batch_accepted = True
                    yield emit("log", {"msg": f"✅ Batch {batch_num} accepted! Score: {quality.get('score')}/100"})
                    break
                elif action == "FIX_AND_RETRY" and retry_count < max_fix_retries:
                    retry_count += 1
                    fixes = result.get("fixes_needed", [])
                    yield emit("log", {"msg": f"🔧 FIX_AND_RETRY — {fixes}"})

                    # Handle exceeded keywords
                    if exceeded:
                        for exc in exceeded:
                            kw = exc.get("keyword", "")
                            synonyms = exc.get("synonyms", [])
                            if synonyms and kw:
                                syn = synonyms[0] if isinstance(synonyms[0], str) else str(synonyms[0])
                                text = text.replace(kw, syn, 1)
                                yield emit("log", {"msg": f"Zamiana: '{kw}' → '{syn}'"})

                    if retry_count == max_fix_retries:
                        forced = True
                else:
                    yield emit("log", {"msg": f"Action: {action} — kontynuuję"})
                    batch_accepted = accepted
                    break

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
        if not paa_check["ok"] or not paa_check.get("data", {}).get("paa_section"):
            yield emit("log", {"msg": "Brak FAQ — analizuję PAA i generuję..."})
            paa_analyze = brajen_call("get", f"/api/project/{project_id}/paa/analyze")
            if paa_analyze["ok"]:
                faq_text = generate_faq_text(paa_analyze["data"])
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
        final_result = brajen_call("get", f"/api/project/{project_id}/final_review")
        if final_result["ok"]:
            final = final_result["data"]
            yield emit("step", {"step": 8, "name": "Final Review", "status": "done",
                                "detail": f"Quality: {final.get('quality_score', '?')}/100"})

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
            diff = ed.get("diff_result", {})
            rollback = ed.get("rollback", {})
            word_guard = ed.get("word_count_guard", {})

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
                "feedback": ed.get("editorial_feedback", {})
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
            stats = full.get("stats", {})
            coverage = full.get("coverage", {})

            yield emit("article", {
                "text": full.get("full_article", ""),
                "word_count": stats.get("word_count", 0),
                "h2_count": stats.get("h2_count", 0),
                "h3_count": stats.get("h3_count", 0),
                "coverage": coverage,
                "density": full.get("density", {})
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
    h2_list = [h.strip() for h in data.get("h2_structure", []) if h.strip()]
    basic_terms = [t.strip() for t in data.get("basic_terms", []) if t.strip()]
    extended_terms = [t.strip() for t in data.get("extended_terms", []) if t.strip()]

    if not h2_list:
        return jsonify({"error": "Brak nagłówków H2"}), 400

    job_id = str(uuid.uuid4())[:8]
    active_jobs[job_id] = {
        "main_keyword": main_keyword,
        "mode": mode,
        "h2_structure": h2_list,
        "status": "running",
        "created": datetime.now().isoformat()
    }

    return jsonify({"job_id": job_id})


@app.route("/api/stream/<job_id>")
@login_required
def stream_workflow(job_id):
    """SSE endpoint for workflow progress."""
    job = active_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    data = job

    def generate():
        yield from run_workflow_sse(
            job_id=job_id,
            main_keyword=data["main_keyword"],
            mode=data["mode"],
            h2_structure=data["h2_structure"],
            basic_terms=request.args.getlist("basic") or [],
            extended_terms=request.args.getlist("extended") or []
        )

    # Pass basic/extended through query params from frontend
    basic_terms = request.args.get("basic_terms", "")
    extended_terms = request.args.get("extended_terms", "")

    def generate_with_terms():
        bt = json.loads(basic_terms) if basic_terms else []
        et = json.loads(extended_terms) if extended_terms else []
        yield from run_workflow_sse(
            job_id=job_id,
            main_keyword=data["main_keyword"],
            mode=data["mode"],
            h2_structure=data["h2_structure"],
            basic_terms=bt,
            extended_terms=et
        )

    return Response(
        stream_with_context(generate_with_terms()),
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
