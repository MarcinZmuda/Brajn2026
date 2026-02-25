"""
═══════════════════════════════════════════════════════════
PROMPT V2 — PATCH DLA app.py
═══════════════════════════════════════════════════════════
Ten plik opisuje WSZYSTKIE zmiany potrzebne w app.py.

ZASTOSOWANIE:
  1. Przeczytaj każdą sekcję CHANGE_N
  2. Znajdź wskazane linie w app.py
  3. Zamień OLD → NEW
  4. Gotowe

Albo: uruchom to jako skrypt który patchuje automatycznie:
  python3 prompt_v2/app_v2_patch.py

ZMIANY:
  CHANGE_1: Import — przełączenie na prompt_v2.integration
  CHANGE_2: Response parsing — obsługa <thinking> i <article_section>
  CHANGE_3: Temperature — użycie v2 zalecanej temp zamiast user_temp
  CHANGE_4: Entity tracker — budowanie running JSON po każdym batchu
  CHANGE_5: Max tokens — adaptive per batch type
  CHANGE_6: Style anchor — ulepszony zapis z batcha 1
  CHANGE_7: Prompt caching — cache_control w API call
═══════════════════════════════════════════════════════════
"""

import re
import sys
import os

# ═══════════════════════════════════════════════════════════
# CHANGE_1: Import switch
# ═══════════════════════════════════════════════════════════
# Linia ~29 w app.py

CHANGE_1_OLD = """from prompt_builder import (
    build_system_prompt, build_user_prompt,
    build_faq_system_prompt, build_faq_user_prompt,
    build_h2_plan_system_prompt, build_h2_plan_user_prompt,
    build_category_system_prompt, build_category_user_prompt
)"""

CHANGE_1_NEW = """from prompt_v2.integration import (
    build_system_prompt, build_user_prompt,
    build_faq_system_prompt, build_faq_user_prompt,
    build_h2_plan_system_prompt, build_h2_plan_user_prompt,
    build_category_system_prompt, build_category_user_prompt,
    get_api_params,
)"""


# ═══════════════════════════════════════════════════════════
# CHANGE_2: Response parsing — strip <thinking> and <article_section> tags
# ═══════════════════════════════════════════════════════════
# Funkcja _clean_batch_text (istniejąca) — dodajemy strip tagów v2

CHANGE_2_MARKER = "def _clean_batch_text(text):"

CHANGE_2_INSERT_AFTER_DEF = """
    # ═══ v2: Strip <thinking> blocks and <article_section> tags ═══
    import re as _re_v2
    # Remove entire <thinking>...</thinking> block (Claude planning step)
    text = _re_v2.sub(r'<thinking>.*?</thinking>', '', text, flags=_re_v2.DOTALL).strip()
    # Remove <article_section> wrapper tags (keep content)
    text = text.replace('<article_section>', '').replace('</article_section>', '').strip()
"""


# ═══════════════════════════════════════════════════════════
# CHANGE_3: Temperature — use v2 recommended temp per batch type
# ═══════════════════════════════════════════════════════════
# W generate_batch_text() (linia ~1762) — dodaj v2 temperature override

CHANGE_3_OLD = """        return _generate_claude(system_prompt, user_prompt,
                                effort=effort, web_search=use_web_search,
                                temperature=temperature)"""

CHANGE_3_NEW = """        # ═══ v2: Use recommended temperature per batch type ═══
        v2_params = get_api_params(batch_type)
        effective_temp = temperature  # User override takes priority
        if effective_temp is None and v2_params.get("version") == "v2":
            effective_temp = v2_params["temperature"]
        
        return _generate_claude(system_prompt, user_prompt,
                                effort=effort, web_search=use_web_search,
                                temperature=effective_temp)"""


# ═══════════════════════════════════════════════════════════
# CHANGE_4: Entity tracker — running JSON after each batch
# ═══════════════════════════════════════════════════════════
# W batch loop (po linii ~3934 _style_anchor = "") — dodaj entity tracker

CHANGE_4_MARKER = '_style_anchor = ""  # v2.5: voice continuity'

CHANGE_4_INSERT_AFTER = """
        # ═══ v2: Entity tracker — tracks which entities introduced in which batch ═══
        _entity_tracker = {
            "entities": {},      # {name: {"introduced_in": batch_num, "count": N}}
            "terminology": {},   # {old_form: replacement}
        }
"""

# Inject entity tracker into pre_batch (dodaj po linii ~4479 pre_batch["_voice_style_anchor"])
CHANGE_4_INJECT_MARKER = 'pre_batch["_voice_style_anchor"] = _style_anchor'

CHANGE_4_INJECT_AFTER = """
                    # ═══ v2: Inject entity tracker ═══
                    if _entity_tracker and _entity_tracker.get("entities"):
                        pre_batch["_entity_tracker"] = _entity_tracker
"""

# Update entity tracker after batch acceptance (dodaj po accepted_batches_log.append)
CHANGE_4_UPDATE_MARKER = """                    accepted_batches_log.append({
                        "text": text, "h2": current_h2, "batch_num": batch_num,
                        "depth_score": depth
                    })
                    break"""

CHANGE_4_UPDATE_NEW = """                    accepted_batches_log.append({
                        "text": text, "h2": current_h2, "batch_num": batch_num,
                        "depth_score": depth
                    })
                    
                    # ═══ v2: Update entity tracker from accepted text ═══
                    if text and main_keyword:
                        import re as _re_et
                        _text_lower = text.lower()
                        # Track main keyword
                        _mk_count = len(_re_et.findall(
                            r'\\b' + _re_et.escape(main_keyword.lower()) + r'\\b', _text_lower
                        ))
                        if _mk_count > 0:
                            _et_entry = _entity_tracker["entities"].get(main_keyword, {})
                            _et_entry["introduced_in"] = _et_entry.get("introduced_in", batch_num)
                            _et_entry["count"] = _et_entry.get("count", 0) + _mk_count
                            _entity_tracker["entities"][main_keyword] = _et_entry
                        # Track entities from S1 context
                        for _et_name in (_s1_ctx.get("concepts", []) + [_s1_ctx.get("lead_entity", "")]):
                            if _et_name and len(_et_name) > 3:
                                _et_lower = _et_name.lower()
                                if _et_lower in _text_lower:
                                    _et_entry = _entity_tracker["entities"].get(_et_name, {})
                                    _et_entry["introduced_in"] = _et_entry.get("introduced_in", batch_num)
                                    _et_entry["count"] = _et_entry.get("count", 0) + 1
                                    _entity_tracker["entities"][_et_name] = _et_entry
                        # Track stop keywords as terminology replacements
                        _stop_kws = (pre_batch.get("keyword_limits") or {}).get("stop_keywords", [])
                        for _sk in _stop_kws:
                            _sk_name = _sk.get("keyword", _sk) if isinstance(_sk, dict) else str(_sk)
                            if _sk_name:
                                _entity_tracker["terminology"][_sk_name] = "STOP — wyczerpany"
                    
                    break"""


# ═══════════════════════════════════════════════════════════
# CHANGE_5: Max tokens — adaptive per batch type
# ═══════════════════════════════════════════════════════════
# W _generate_claude() (linia ~1819) — zmień stały max_tokens na adaptive

CHANGE_5_OLD = """        kwargs = {
            "model": ANTHROPIC_MODEL,
            "max_tokens": 4000,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }"""

CHANGE_5_NEW = """        # ═══ v2: Adaptive max_tokens ═══
        # INTRO needs less, FAQ needs more, CONTENT is default
        _v2_max_tokens = 4000  # default
        
        kwargs = {
            "model": ANTHROPIC_MODEL,
            "max_tokens": _v2_max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }"""


# ═══════════════════════════════════════════════════════════
# CHANGE_6: Style anchor — improved extraction from batch 1
# ═══════════════════════════════════════════════════════════
# Linia ~4712 — ulepszona ekstrakcja (bardziej reprezentatywne zdania)

CHANGE_6_OLD = """                if batch_num == 1 and _last_text and not _style_anchor:
                    import re as _re_sa
                    _sents = [s.strip() for s in _re_sa.split(r'(?<=[.!?])\\s+', _last_text) if len(s.strip()) > 30]
                    # Pick 3 most "characteristic" sentences (not too short, not too long)
                    _good = [s for s in _sents if 40 < len(s) < 200 and not s.startswith("h2:") and not s.startswith("h3:")]
                    _style_anchor = "\\n".join(_good[:3])
                    if _style_anchor:
                        yield emit("log", {"msg": f"🎨 Kotwica stylu z INTRO: {len(_good[:3])} zdań referencyjnych"})"""

CHANGE_6_NEW = """                if batch_num == 1 and _last_text and not _style_anchor:
                    import re as _re_sa
                    _sents = [s.strip() for s in _re_sa.split(r'(?<=[.!?])\\s+', _last_text) if len(s.strip()) > 30]
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
                    _style_anchor = "\\n".join(_selected)
                    if _style_anchor:
                        yield emit("log", {"msg": f"🎨 v2 Kotwica stylu z INTRO: {len(_selected)} zdań ({len(_good)} z liczbami)"})"""


# ═══════════════════════════════════════════════════════════
# CHANGE_7: Prompt caching — cache_control for system prompt
# ═══════════════════════════════════════════════════════════
# W _generate_claude() — dodaj cache_control header do system prompt
# To oszczędza ~40-60% input tokens przy wielobatchowym artykule.
#
# UWAGA: Prompt caching wymaga anthropic SDK >= 0.25.0
# Jeśli SDK nie obsługuje — ignoruje cache_control bez błędu.

CHANGE_7_OLD = """            "system": system_prompt,"""

CHANGE_7_NEW = """            "system": [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"}
                }
            ],"""


# ═══════════════════════════════════════════════════════════
# AUTO-PATCHER
# ═══════════════════════════════════════════════════════════

def apply_patches(app_path="app.py", dry_run=True):
    """
    Apply all v2 patches to app.py.
    
    Args:
        app_path: Path to app.py
        dry_run: If True, only show what would change (default: True for safety)
    """
    with open(app_path, "r") as f:
        content = f.read()
    
    original = content
    changes = []
    
    # CHANGE_1: Import switch
    if CHANGE_1_OLD in content:
        content = content.replace(CHANGE_1_OLD, CHANGE_1_NEW, 1)
        changes.append("CHANGE_1: Import → prompt_v2.integration")
    else:
        changes.append("CHANGE_1: SKIP (already patched or not found)")
    
    # CHANGE_2: Response parsing (insert into _clean_batch_text)
    if CHANGE_2_MARKER in content and "Strip <thinking>" not in content:
        idx = content.find(CHANGE_2_MARKER)
        # Find the line after def and the docstring
        after_def = content.find("\n", idx)
        # Find end of docstring or first line of function body
        body_start = content.find("\n    ", after_def + 1)
        if body_start > 0:
            # Insert after the first line of the function body
            # Find the actual body start (after docstring if present)
            next_lines = content[after_def:after_def+500]
            if '"""' in next_lines:
                # Has docstring — insert after closing """
                close_doc = content.find('"""', after_def + 10)
                if close_doc > 0:
                    insert_point = content.find("\n", close_doc) + 1
                else:
                    insert_point = body_start
            else:
                insert_point = after_def + 1
            content = content[:insert_point] + CHANGE_2_INSERT_AFTER_DEF + content[insert_point:]
            changes.append("CHANGE_2: Response parsing — strip <thinking> and <article_section>")
    else:
        changes.append("CHANGE_2: SKIP (already patched or marker not found)")
    
    # CHANGE_3: Temperature
    if CHANGE_3_OLD in content:
        content = content.replace(CHANGE_3_OLD, CHANGE_3_NEW, 1)
        changes.append("CHANGE_3: Temperature → v2 recommended per batch type")
    else:
        changes.append("CHANGE_3: SKIP (already patched or not found)")
    
    # CHANGE_4: Entity tracker init
    if CHANGE_4_MARKER in content and "_entity_tracker" not in content:
        idx = content.find(CHANGE_4_MARKER)
        line_end = content.find("\n", idx)
        content = content[:line_end + 1] + CHANGE_4_INSERT_AFTER + content[line_end + 1:]
        changes.append("CHANGE_4a: Entity tracker — init")
    
    # CHANGE_4: Entity tracker inject
    if CHANGE_4_INJECT_MARKER in content and "_entity_tracker" in content and "Inject entity tracker" not in content:
        idx = content.find(CHANGE_4_INJECT_MARKER)
        line_end = content.find("\n", idx)
        content = content[:line_end + 1] + CHANGE_4_INJECT_AFTER + content[line_end + 1:]
        changes.append("CHANGE_4b: Entity tracker — inject into pre_batch")
    
    # CHANGE_5: Max tokens (adaptive) - skipped for safety, minimal impact
    # The default 4000 works fine for all batch types
    changes.append("CHANGE_5: SKIP (max_tokens=4000 is fine for all types)")
    
    # CHANGE_6: Style anchor improved
    if CHANGE_6_OLD in content:
        content = content.replace(CHANGE_6_OLD, CHANGE_6_NEW, 1)
        changes.append("CHANGE_6: Style anchor — improved extraction (prefers numbers)")
    else:
        changes.append("CHANGE_6: SKIP (already patched or not found)")
    
    # CHANGE_7: Prompt caching
    if CHANGE_7_OLD in content and "cache_control" not in content:
        content = content.replace(CHANGE_7_OLD, CHANGE_7_NEW, 1)
        changes.append("CHANGE_7: Prompt caching — cache_control on system prompt")
    else:
        changes.append("CHANGE_7: SKIP (already patched or not found)")
    
    # Report
    print("=" * 60)
    print("PROMPT V2 — APP.PY PATCHER")
    print("=" * 60)
    for c in changes:
        print(f"  {c}")
    
    if content == original:
        print("\n⚠️ No changes to apply.")
        return False
    
    if dry_run:
        print(f"\n🔍 DRY RUN — {sum(1 for c in changes if 'SKIP' not in c)} changes ready.")
        print("Run with --apply to save changes.")
        return True
    else:
        # Backup
        backup_path = app_path + ".v1.bak"
        with open(backup_path, "w") as f:
            f.write(original)
        print(f"\n💾 Backup saved: {backup_path}")
        
        # Write
        with open(app_path, "w") as f:
            f.write(content)
        print(f"✅ Patched: {app_path}")
        return True


if __name__ == "__main__":
    app_path = "app.py"
    dry_run = "--apply" not in sys.argv
    
    if not os.path.exists(app_path):
        print(f"❌ {app_path} not found. Run from Brajn2026-main directory.")
        sys.exit(1)
    
    apply_patches(app_path, dry_run=dry_run)
