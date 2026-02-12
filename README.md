# BRAJEN SEO Frontend v45.3

## Architektura

```
Frontend (ten folder)              → Render deploy #2
   app.py                          — SSE orchestrator
   prompt_builder.py               — buduje prompty dla Claude  
   ai_middleware.py                — S1 cleanup + smart retry (Haiku)
   keyword_dedup.py                — word-boundary dedup (NOWY)
        ↓ HTTP
master-seo-api (osobne repo)       → Render deploy #1 — BEZ ZMIAN
        ↓ proxy S1
gpt-ngram-api (osobne repo)        → Render deploy #3 — BEZ ZMIAN
```

## Co nowego (v45.3)

### keyword_dedup.py (NOWY)
Word-boundary safe deduplication — zapobiega podwójnemu liczeniu zagnieżdżonych fraz.

**Zapobiega false positives:**
- `"rok"` ≠ `"wyrok"` (inne słowa)
- `"dom"` ≠ `"domowy"` (brak word boundary)
- `"raz"` ≠ `"wyraz"` (substring, nie słowo)

**Poprawne redukcje:**
- `"bagaż"` ∈ `"bagaż podręczny"` → target_max obniżony
- `"prawo karne"` ∈ `"prawo karne kary"` → target_max obniżony

### prompt_builder.py (v1.1)
- `_fmt_keywords()` oblicza `remaining = target_max - actual` z pól backendu
- Pokazuje "zostało X× ogółem, max Y× w tym batchu"
- Lepsze formatowanie STOP/CAUTION keywords

### ai_middleware.py
- S1 data cleanup (pattern-based + AI Haiku fallback)
- Smart retry — Haiku przepisuje tekst zamieniając nadużywane frazy
- Article memory synthesis gdy backend nie dostarcza

## Instalacja

### 1. Skopiuj nowe pliki obok app.py:
```
keyword_dedup.py    → nowy plik
prompt_builder.py   → zastąp istniejący
ai_middleware.py    → zastąp istniejący (jeśli masz)
```

### 2. Zpatchuj app.py:
```bash
python patch_app.py app.py
```

To doda 2 zmiany:
1. `from keyword_dedup import deduplicate_keywords` (import)
2. `keywords = deduplicate_keywords(keywords, main_keyword)` (wywołanie przed create_project)

### 3. Env vars (Render):
```
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-opus-4-6
BRAJEN_API_URL=https://master-seo-api.onrender.com
APP_USERNAME=...
APP_PASSWORD=...
SECRET_KEY=...
# Opcjonalne:
MIDDLEWARE_MODEL=claude-haiku-4-5-20251001
OPENAI_API_KEY=...
```

### 4. Deploy na Render:
```bash
pip install -r requirements.txt
python app.py
```

## Pliki

| Plik | Rozmiar | Status |
|------|---------|--------|
| keyword_dedup.py | 6 KB | **NOWY** — word-boundary dedup |
| prompt_builder.py | 40 KB | **UPGRADE** — remaining_max z actual+target |
| ai_middleware.py | 16 KB | bez zmian |
| patch_app.py | 3 KB | narzędzie — patchuje app.py |
| requirements.txt | - | zależności pip |
