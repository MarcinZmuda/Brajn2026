"""
Shared sentence length constants for Brajn2026.
Fix #9 v4.2: Ujednolicenie targetow dlugosci zdan.

Uzywany przez: prompt_builder.py, ai_middleware.py
"""

# Srednia dlugosc zdania (target)
SENTENCE_AVG_TARGET = 15       # optymalny publicystyczny styl
SENTENCE_AVG_TARGET_MIN = 12   # dolna granica
SENTENCE_AVG_TARGET_MAX = 18   # gorna granica

# Maksymalna dlugosc pojedynczego zdania
SENTENCE_SOFT_MAX = 30         # warning jesli przekroczone
SENTENCE_HARD_MAX = 35         # odrzucenie/retry jesli przekroczone

# Progi dla walidatora
SENTENCE_AVG_MAX_ALLOWED = 20  # max srednia zanim retry
SENTENCE_RETRY_THRESHOLD = 25  # hard retry jesli srednia > 25
