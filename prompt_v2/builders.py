from prompt_v2.constants import (
    PERSONAS,
    CONSTITUTION,
    WRITING_RULES,
    LEAD_RULES,
    REAL_WORLD_ANCHORS,
)


def build_system_prompt(topic, main_entity, persona="inne"):
    """
    Buduje pełny system prompt.
    Lead rules są zawsze dołączane.
    """

    parts = []

    # Konstytucja
    parts.append(CONSTITUTION)

    # Zasady pisania
    parts.append(WRITING_RULES)

    # Zasady leada (zawsze aktywne)
    parts.append(LEAD_RULES)

    # Element praktyczny
    parts.append(REAL_WORLD_ANCHORS)

    # Persona
    persona_text = PERSONAS.get(persona, PERSONAS.get("inne", ""))
    parts.append(f"<persona>{persona_text}</persona>")

    # Kontekst artykułu
    parts.append(f"""
<kontekst>
Temat: {topic}
Encja główna: {main_entity}
</kontekst>
""")

    return "\n\n".join(parts)


# ─────────────────────────────────────────
# 🔧 BACKWARD COMPATIBILITY FIX
# ─────────────────────────────────────────
# Starsze moduły importują build_user_prompt.
# Alias zapobiega crashowi Render.

def build_user_prompt(*args, **kwargs):
    return build_system_prompt(*args, **kwargs)
