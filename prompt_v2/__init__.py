"""
═══════════════════════════════════════════════════════════
PROMPT V2 — MODULE INIT
═══════════════════════════════════════════════════════════
Drop-in replacement for prompt_builder.py.

PRZEŁĄCZANIE:
  Sposób 1 (env var):
    export PROMPT_VERSION=v2  → nowe prompty
    export PROMPT_VERSION=v1  → stare prompty (default)

  Sposób 2 (w kodzie):
    from prompt_v2 import get_prompt_builder
    pb = get_prompt_builder()
    system = pb.build_system_prompt(pre_batch, batch_type)

  Sposób 3 (bezpośredni import):
    from prompt_v2.builders import build_system_prompt, build_user_prompt

GRANULARNE WŁĄCZANIE/WYŁĄCZANIE FEATURES:
    export V2_FEW_SHOT=0         # wyłącz few-shot examples
    export V2_THINKING=0         # wyłącz thinking block
    export V2_POLISH=0           # wyłącz blok polszczyzny
    export V2_VOICE_ANCHOR=0     # wyłącz kotwicę głosu
    export V2_OUTLINE=0          # wyłącz article outline
    export V2_NATURAL_KW=0       # wyłącz natural keyword format

INTEGRACJA Z ai_middleware.py:
    Zmień import z:
        from prompt_builder import build_system_prompt, build_user_prompt
    Na:
        from prompt_v2 import build_system_prompt, build_user_prompt
    
    Lub z automatycznym switchem:
        from prompt_v2.config import get_prompt_builder
        pb = get_prompt_builder()
═══════════════════════════════════════════════════════════
"""

# ── Config & feature flags ──
from prompt_v2.config import (
    is_v2,
    feature_enabled,
    get_temperature,
    get_prompt_builder,
    PROMPT_VERSION,
    V2_FEATURES,
    V2_TEMPERATURE,
)

# ── Direct builder imports (always v2 when imported from here) ──
from prompt_v2.builders import (
    build_system_prompt,
    build_user_prompt,
    build_faq_system_prompt,
    build_faq_user_prompt,
    build_h2_plan_system_prompt,
    build_h2_plan_user_prompt,
    build_category_system_prompt,
    build_category_user_prompt,
)

# ── Style samples ──
from prompt_v2.style_samples import (
    get_samples,
    format_samples_block,
)

__all__ = [
    # Config
    "is_v2", "feature_enabled", "get_temperature", "get_prompt_builder",
    "PROMPT_VERSION", "V2_FEATURES", "V2_TEMPERATURE",
    # Builders (same interface as prompt_builder.py)
    "build_system_prompt", "build_user_prompt",
    "build_faq_system_prompt", "build_faq_user_prompt",
    "build_h2_plan_system_prompt", "build_h2_plan_user_prompt",
    "build_category_system_prompt", "build_category_user_prompt",
    # Style samples
    "get_samples", "format_samples_block",
]

__version__ = "2.0.0"
