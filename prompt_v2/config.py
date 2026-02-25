"""
═══════════════════════════════════════════════════════════
PROMPT V2 — CONFIG & FEATURE FLAGS
═══════════════════════════════════════════════════════════
Zarządza przełączaniem między starym (v1) a nowym (v2) pipeline.
Jedno miejsce do zmiany = cały system się przełącza.

Użycie w ai_middleware.py (lub tam gdzie importujesz prompt_builder):
    from prompt_v2 import get_prompt_builder
    pb = get_prompt_builder()       # respects PROMPT_VERSION env/config
    system = pb.build_system_prompt(pre_batch, batch_type)
    user   = pb.build_user_prompt(pre_batch, h2, batch_type, article_memory)

Albo bezpośrednio:
    from prompt_v2 import build_system_prompt, build_user_prompt
═══════════════════════════════════════════════════════════
"""

import os
import logging

_logger = logging.getLogger(__name__)

# ── Feature flag ──
# Set via env var PROMPT_VERSION=v2  (or v1 to stay on old)
# Default: "v1" — safe, nothing changes until you flip it
PROMPT_VERSION = os.environ.get("PROMPT_VERSION", "v1").lower().strip()

# ── Per-feature granular toggles (only when PROMPT_VERSION=v2) ──
# These allow gradual rollout — enable features one by one
V2_FEATURES = {
    # Core changes
    "few_shot_examples":    os.environ.get("V2_FEW_SHOT", "1") == "1",
    "thinking_block":       os.environ.get("V2_THINKING", "1") == "1",
    "polish_language_block": os.environ.get("V2_POLISH", "1") == "1",
    "positive_constitution": os.environ.get("V2_CONSTITUTION", "1") == "1",
    "short_forbidden_list":  os.environ.get("V2_SHORT_FORBIDDEN", "1") == "1",

    # Context management
    "voice_anchor":         os.environ.get("V2_VOICE_ANCHOR", "1") == "1",
    "article_outline":      os.environ.get("V2_OUTLINE", "1") == "1",
    "entity_tracker":       os.environ.get("V2_ENTITY_TRACKER", "1") == "1",
    "filtered_s1":          os.environ.get("V2_FILTERED_S1", "1") == "1",

    # Prompt ordering
    "data_before_instructions": os.environ.get("V2_DATA_FIRST", "1") == "1",
    "natural_keyword_format":   os.environ.get("V2_NATURAL_KW", "1") == "1",
}

# ── API parameters per batch type ──
V2_TEMPERATURE = {
    "INTRO":    float(os.environ.get("V2_TEMP_INTRO", "0.7")),
    "CONTENT":  float(os.environ.get("V2_TEMP_CONTENT", "0.6")),
    "FAQ":      float(os.environ.get("V2_TEMP_FAQ", "0.4")),
    "EDITORIAL": float(os.environ.get("V2_TEMP_EDITORIAL", "0.3")),
    "RETRY":    float(os.environ.get("V2_TEMP_RETRY", "0.3")),
    "DEFAULT":  float(os.environ.get("V2_TEMP_DEFAULT", "0.6")),
}


def is_v2() -> bool:
    """Check if v2 prompts are active."""
    return PROMPT_VERSION == "v2"


def feature_enabled(feature_name: str) -> bool:
    """Check if a specific v2 feature is enabled."""
    if not is_v2():
        return False
    return V2_FEATURES.get(feature_name, False)


def get_temperature(batch_type: str) -> float:
    """Get recommended temperature for batch type."""
    if not is_v2():
        return 1.0  # let v1 handle its own temperature
    bt = batch_type.upper() if batch_type else "DEFAULT"
    return V2_TEMPERATURE.get(bt, V2_TEMPERATURE["DEFAULT"])


def get_prompt_builder():
    """
    Return the active prompt builder module.
    Usage:
        pb = get_prompt_builder()
        system = pb.build_system_prompt(pre_batch, batch_type)
    """
    if is_v2():
        _logger.info("Using prompt_v2 pipeline")
        from prompt_v2 import builders as v2_builders
        return v2_builders
    else:
        _logger.info("Using prompt_v1 (original prompt_builder)")
        import prompt_builder as v1_builders
        return v1_builders
