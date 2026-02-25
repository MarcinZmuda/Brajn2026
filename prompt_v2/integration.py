"""
═══════════════════════════════════════════════════════════
PROMPT V2 — INTEGRATION HELPER
═══════════════════════════════════════════════════════════
Minimalny plik integracyjny — wklej do ai_middleware.py
zamiast ręcznego importu prompt_builder.

PRZED (ai_middleware.py):
    from prompt_builder import (
        build_system_prompt, build_user_prompt,
        build_faq_system_prompt, build_faq_user_prompt,
        build_h2_plan_system_prompt, build_h2_plan_user_prompt,
        build_category_system_prompt, build_category_user_prompt,
    )

PO (ai_middleware.py):
    from prompt_v2.integration import (
        build_system_prompt, build_user_prompt,
        build_faq_system_prompt, build_faq_user_prompt,
        build_h2_plan_system_prompt, build_h2_plan_user_prompt,
        build_category_system_prompt, build_category_user_prompt,
        get_temperature,
    )

To jest jedyna zmiana potrzebna w ai_middleware.py!
Potem przełączanie = zmiana env var PROMPT_VERSION=v1|v2
═══════════════════════════════════════════════════════════
"""

import logging
from prompt_v2.config import is_v2, get_temperature, PROMPT_VERSION

_logger = logging.getLogger(__name__)
_logger.info(f"[prompt_v2.integration] Active version: {PROMPT_VERSION}")


if is_v2():
    _logger.info("[prompt_v2.integration] Loading v2 builders")
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
else:
    _logger.info("[prompt_v2.integration] Loading v1 builders (original prompt_builder)")
    from prompt_builder import (
        build_system_prompt,
        build_user_prompt,
        build_faq_system_prompt,
        build_faq_user_prompt,
        build_h2_plan_system_prompt,
        build_h2_plan_user_prompt,
        build_category_system_prompt,
        build_category_user_prompt,
    )


def get_api_params(batch_type: str = "CONTENT") -> dict:
    """
    Return recommended API parameters for the active version.

    Usage in ai_middleware.py:
        from prompt_v2.integration import get_api_params
        params = get_api_params(batch_type)
        response = anthropic.messages.create(
            temperature=params["temperature"],
            ...
        )
    """
    if is_v2():
        return {
            "temperature": get_temperature(batch_type),
            "version": "v2",
        }
    return {
        "temperature": 1.0,  # v1 default
        "version": "v1",
    }


__all__ = [
    "build_system_prompt",
    "build_user_prompt",
    "build_faq_system_prompt",
    "build_faq_user_prompt",
    "build_h2_plan_system_prompt",
    "build_h2_plan_user_prompt",
    "build_category_system_prompt",
    "build_category_user_prompt",
    "get_temperature",
    "get_api_params",
]
