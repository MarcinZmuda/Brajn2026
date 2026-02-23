"""
Shared sentence length constants for Brajn2026.
Fix #9 v4.2: Ujednolicenie targetow dlugosci zdan.
Fix #53 v4.3: Nowe limity — naturalna polszczyzna publicystyczna.
Fix #45.3 v4.4: Ujednolicenie z prompt_builder.py (prompt mowil 10-15, validator 22 — sprzeczne!)
                 Teraz: prompt 12-18, validator 20, hard_max 25.

Uzywany przez: prompt_builder.py, ai_middleware.py
"""

# Srednia dlugosc zdania (target)
# v4.4: Ujednolicono z promptem — prompt mowi 12-18, validator akceptuje do 20.
# Poprzednio: prompt "10-15", validator "22" — ogromna luka.
SENTENCE_AVG_TARGET = 15       # optymalny publicystyczny styl (bylo: 16)
SENTENCE_AVG_TARGET_MIN = 12   # dolna granica — sync z promptem (bylo: 14)
SENTENCE_AVG_TARGET_MAX = 18   # gorna granica (bez zmian)

# Maksymalna dlugosc pojedynczego zdania
SENTENCE_SOFT_MAX = 22         # warning jesli przekroczone (bylo: 25)
SENTENCE_HARD_MAX = 25         # odrzucenie/retry jesli przekroczone (bylo: 28)

# Progi dla walidatora
# v4.4: Obnizono z 22 do 20 — blizej targetu promptu (12-18)
SENTENCE_AVG_MAX_ALLOWED = 20  # max srednia zanim retry (bylo: 22)
SENTENCE_RETRY_THRESHOLD = 25  # hard retry jesli srednia > 25 (bylo: 27)

# Max przecinkow w jednym zdaniu (naturalny rytm)
SENTENCE_MAX_COMMAS = 2        # Fix #53: bylo 1, to zbyt restrykcyjne dla polskich zdan

# Fix #44: Keyword anti-stuffing
KEYWORD_MAIN_MAX_PER_BATCH = 2   # max uzyc glownej frazy w jednym batchu
KEYWORD_MIN_SPACING_WORDS = 80   # min odleglosc miedzy powtorzeniami
