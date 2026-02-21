"""
Shared sentence length constants for Brajn2026.
Fix #9 v4.2: Ujednolicenie targetow dlugosci zdan.
Fix #53 v4.3: Nowe limity — naturalna polszczyzna publicystyczna.

Uzywany przez: prompt_builder.py, ai_middleware.py
"""

# Srednia dlugosc zdania (target)
# Fix #53: Poprzednie wartosci (target=12, max=22) powodowaly styl "telegraficzny".
# Nowe wartosci odpowiadaja naturalnej polszczyznie publicystycznej.
SENTENCE_AVG_TARGET = 16       # optymalny publicystyczny styl (bylo: 15)
SENTENCE_AVG_TARGET_MIN = 14   # dolna granica (bylo: 12)
SENTENCE_AVG_TARGET_MAX = 18   # gorna granica (bez zmian)

# Maksymalna dlugosc pojedynczego zdania
SENTENCE_SOFT_MAX = 25         # warning jesli przekroczone (bylo: 30)
SENTENCE_HARD_MAX = 28         # odrzucenie/retry jesli przekroczone (bylo: 35)

# Progi dla walidatora
SENTENCE_AVG_MAX_ALLOWED = 22  # max srednia zanim retry (bylo: 20 — podwyzszone dla polszczyzny)
SENTENCE_RETRY_THRESHOLD = 27  # hard retry jesli srednia > 27 (bylo: 25)

# Max przecinkow w jednym zdaniu (naturalny rytm)
SENTENCE_MAX_COMMAS = 2        # Fix #53: bylo 1, to zbyt restrykcyjne dla polskich zdan
