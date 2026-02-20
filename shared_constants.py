"""
Shared sentence length constants for Brajn2026.
Fix #9 v4.2: Ujednolicenie targetow dlugosci zdan.
Fix #34: Zaostrzenie — krotsze, prostsze zdania (max 1 przecinek).
Fix #44: Dalsze zaostrzenie — HARD_MAX 25→20, retry threshold 20→16.

Uzywany przez: prompt_builder.py, ai_middleware.py
"""

# Srednia dlugosc zdania (target)
SENTENCE_AVG_TARGET = 12       # krotkie, czytelne zdania
SENTENCE_AVG_TARGET_MIN = 8    # dolna granica (fakty, definicje)
SENTENCE_AVG_TARGET_MAX = 14   # gorna granica sredniej (bylo 15)

# Maksymalna dlugosc pojedynczego zdania
SENTENCE_SOFT_MAX = 18         # warning jesli przekroczone (bylo 20)
SENTENCE_HARD_MAX = 22         # odrzucenie/retry jesli przekroczone (bylo 25)

# Progi dla walidatora
SENTENCE_AVG_MAX_ALLOWED = 15  # max srednia zanim retry (bylo 16)
SENTENCE_RETRY_THRESHOLD = 16  # hard retry jesli srednia > 16 (bylo 20)

# Struktura zdania
SENTENCE_MAX_COMMAS = 1        # max 1 przecinek w zdaniu (nie wielokrotnie zlozone)

# Fix #44: Keyword anti-stuffing
KEYWORD_MAIN_MAX_PER_BATCH = 2   # max uzyc glownej frazy w jednym batchu
KEYWORD_MIN_SPACING_WORDS = 80   # min odleglosc miedzy powtorzeniami (bylo 60)
