"""
Shared sentence length constants for Brajn2026 + master-seo-api.
v6.0: SYNCHRONIZED — musi być identyczny w obu repozytoriach.
      prompt_builder <zasady>: "max 2 przecinki, zdanie > 22 słów → rozbij, FOG-PL 8-9"
      Validator tolerancje szersze (naturalna wariancja).

Używany przez: prompt_builder.py, ai_middleware.py
"""

# Średnia długość zdania (target)
SENTENCE_AVG_TARGET = 14       # kompromis prompt(FOG8-9) + NKJP publicystyczny
SENTENCE_AVG_TARGET_MIN = 8    # dolna granica — krótkie zdania OK
SENTENCE_AVG_TARGET_MAX = 20   # górna granica

# Maksymalna długość pojedynczego zdania
SENTENCE_SOFT_MAX = 25         # warning (prompt mówi >22 → rozbij)
SENTENCE_HARD_MAX = 30         # odrzucenie (twarda granica)

# Progi dla walidatora
SENTENCE_AVG_MAX_ALLOWED = 22  # max średnia zanim retry
SENTENCE_RETRY_THRESHOLD = 28  # hard retry

# Max przecinków w jednym zdaniu
SENTENCE_MAX_COMMAS = 2        # prompt <zasady>: "max 2 przecinki"

# Keyword anti-stuffing
KEYWORD_MAIN_MAX_PER_BATCH = 2
KEYWORD_MIN_SPACING_WORDS = 80
