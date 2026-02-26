"""
═══════════════════════════════════════════════════════════
PROMPT V2 — BUILDERS
═══════════════════════════════════════════════════════════
FIX: build_system_prompt teraz przyjmuje zarówno:
  - stary interfejs v1:  build_system_prompt(pre_batch, batch_type)
  - nowy interfejs v2:   build_system_prompt(topic="", main_entity="", ...)

Wszystkie pozostałe funkcje (build_user_prompt, build_faq_*, itd.)
delegują do PRAWDZIWYCH implementacji z prompt_builder (v1),
zamiast błędnie redirectować do build_system_prompt.
═══════════════════════════════════════════════════════════
"""

from prompt_v2.constants import (
    PERSONAS,
    CONSTITUTION,
    WRITING_RULES,
    LEAD_RULES,
    REAL_WORLD_ANCHORS,
    ANTI_REPETITION_RULES,
    COHERENCE_RULES,
)


def _extract_topic_entity(pre_batch):
    """Wyciąga topic i main_entity z pre_batch dict (interfejs v1)."""
    raw_main = pre_batch.get("main_keyword") or {}
    if isinstance(raw_main, dict):
        topic = raw_main.get("keyword", "") or raw_main.get("name", "")
    else:
        topic = str(raw_main)

    main_entity = (
        pre_batch.get("main_entity")
        or pre_batch.get("_main_entity")
        or topic
    )
    persona = pre_batch.get("detected_category", "inne")
    return topic, main_entity, persona


def build_system_prompt(pre_batch_or_topic=None, batch_type=None,
                        topic="", main_entity="", persona="inne", **kwargs):
    """
    Buduje v2 system prompt.

    Obsługuje dwa interfejsy:
      v1-style: build_system_prompt(pre_batch_dict, batch_type_str)
      v2-style: build_system_prompt(topic="...", main_entity="...", persona="...")

    Defaults zapobiegają crashowi przy wywołaniu bez argumentów.
    """

    # ── Wykrywanie interfejsu ──
    if isinstance(pre_batch_or_topic, dict):
        # v1-style call: build_system_prompt(pre_batch, batch_type)
        _topic, _entity, _persona = _extract_topic_entity(pre_batch_or_topic)
        topic = topic or _topic
        main_entity = main_entity or _entity
        if persona == "inne":
            persona = _persona
    elif isinstance(pre_batch_or_topic, str) and pre_batch_or_topic:
        # v2-style call z pozycyjnymi: build_system_prompt("temat", "encja")
        topic = pre_batch_or_topic
        if batch_type and not main_entity:
            main_entity = batch_type

    parts = []

    parts.append(CONSTITUTION)
    parts.append(WRITING_RULES)
    parts.append(LEAD_RULES)
    parts.append(REAL_WORLD_ANCHORS)
    parts.append(ANTI_REPETITION_RULES)
    parts.append(COHERENCE_RULES)

    persona_text = PERSONAS.get(persona, PERSONAS.get("inne", ""))
    parts.append(f"<persona>{persona_text}</persona>")

    if topic or main_entity:
        parts.append(
            f"\n<kontekst>\nTemat: {topic}\nEncja główna: {main_entity}\n</kontekst>\n"
        )

    return "\n\n".join(parts)


# ─────────────────────────────────────────
# POZOSTAŁE FUNKCJE — delegacja do v1
# ─────────────────────────────────────────
# Zamiast błędnie redirectować wszystko do build_system_prompt,
# delegujemy do prawdziwych implementacji v1.
# System prompt jest podmieniony na v2 (powyżej),
# natomiast user prompt i reszta logiki pochodzi z v1.

def build_user_prompt(pre_batch, h2, batch_type, article_memory=None):
    from prompt_builder import build_user_prompt as _v1
    return _v1(pre_batch, h2, batch_type, article_memory)


def build_faq_system_prompt(pre_batch=None):
    from prompt_builder import build_faq_system_prompt as _v1
    return _v1(pre_batch)


def build_faq_user_prompt(paa_data, pre_batch=None):
    from prompt_builder import build_faq_user_prompt as _v1
    return _v1(paa_data, pre_batch)


def build_h2_plan_system_prompt():
    from prompt_builder import build_h2_plan_system_prompt as _v1
    return _v1()


def build_h2_plan_user_prompt(main_keyword, mode, s1_data, all_user_phrases, user_h2_hints=None):
    from prompt_builder import build_h2_plan_user_prompt as _v1
    return _v1(main_keyword, mode, s1_data, all_user_phrases, user_h2_hints)


def build_category_system_prompt(pre_batch, batch_type, category_data=None):
    from prompt_builder import build_category_system_prompt as _v1
    return _v1(pre_batch, batch_type, category_data)


def build_category_user_prompt(pre_batch, h2, batch_type, article_memory=None, category_data=None):
    from prompt_builder import build_category_user_prompt as _v1
    return _v1(pre_batch, h2, batch_type, article_memory, category_data)


__all__ = [
    'build_system_prompt',
    'build_user_prompt',
    'build_faq_system_prompt',
    'build_faq_user_prompt',
    'build_h2_plan_system_prompt',
    'build_h2_plan_user_prompt',
    'build_category_system_prompt',
    'build_category_user_prompt',
]
