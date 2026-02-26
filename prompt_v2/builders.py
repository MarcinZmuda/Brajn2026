from prompt_v2.constants import (
    PERSONAS,
    CONSTITUTION,
    WRITING_RULES,
    LEAD_RULES,
    REAL_WORLD_ANCHORS,
)


def build_system_prompt(topic="", main_entity="", persona="inne", **kwargs):
    """
    Buduje pełny system prompt.
    Lead rules są zawsze dołączane.
    Defaults i **kwargs dla kompatybilności z pustymi wywołaniami.
    """

    parts = []

    # ─────────────────────────
    # Konstytucja
    # ─────────────────────────
    parts.append(CONSTITUTION)

    # ─────────────────────────
    # Zasady pisania
    # ─────────────────────────
    parts.append(WRITING_RULES)

    # ─────────────────────────
    # Zasady leada (zawsze aktywne)
    # ─────────────────────────
    parts.append(LEAD_RULES)

    # ─────────────────────────
    # Element praktyczny
    # ─────────────────────────
    parts.append(REAL_WORLD_ANCHORS)

    # ─────────────────────────
    # Persona
    # ─────────────────────────
    persona_text = PERSONAS.get(persona, PERSONAS.get("inne", ""))
    parts.append(f"<persona>{persona_text}</persona>")

    # ─────────────────────────
    # Kontekst artykułu
    # ─────────────────────────
    parts.append(
        f"""
<kontekst>
Temat: {topic}
Encja główna: {main_entity}
</kontekst>
"""
    )

    return "\n\n".join(parts)


# ─────────────────────────────────────────
# BACKWARD COMPATIBILITY FIXES
# ─────────────────────────────────────────
# Starsze moduły importują build_user_prompt
# oraz build_faq_system_prompt.
# Alias zapobiega crashowi Render.

def build_user_prompt(*args, **kwargs):
    return build_system_prompt(*args, **kwargs)


def build_faq_system_prompt(*args, **kwargs):
    return build_system_prompt(*args, **kwargs)

# Dodane aliasy dla brakujących funkcji importowanych w __init__.py
# Aby uniknąć ImportError i zapewnić pełną kompatybilność

def build_faq_user_prompt(*args, **kwargs):
    return build_system_prompt(*args, **kwargs)

def build_h2_plan_system_prompt(*args, **kwargs):
    return build_system_prompt(*args, **kwargs)

def build_h2_plan_user_prompt(*args, **kwargs):
    return build_system_prompt(*args, **kwargs)

def build_category_system_prompt(*args, **kwargs):
    return build_system_prompt(*args, **kwargs)

def build_category_user_prompt(*args, **kwargs):
    return build_system_prompt(*args, **kwargs)

# Eksplicitny eksport nazw dla lepszej kompatybilności i zapobiegania błędom importów
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
