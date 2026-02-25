# Prompt V2 — Moduł Optymalizacji Promptów Brajna

## Struktura

```
prompt_v2/
├── __init__.py          # Eksporty modułu
├── config.py            # Feature flags, env vars, przełącznik v1/v2
├── constants.py         # Bloki tekstowe: konstytucja, polszczyzna, zakazane
├── style_samples.py     # Few-shot examples per kategoria (GAME CHANGER)
├── builders.py          # Główna logika budowania promptów (drop-in replacement)
├── integration.py       # Helper — auto-switch v1/v2
├── app_v2_patch.py      # Automatyczny patcher dla app.py
└── README.md            # Ten plik
```

## Instalacja — 2 ścieżki

### Ścieżka A: Automatyczny patcher (ZALECANA)

```bash
# 1. Skopiuj folder prompt_v2/ do Brajn2026-main/
cp -r prompt_v2/ /path/to/Brajn2026-main/

# 2. Dry run — zobacz co się zmieni:
cd /path/to/Brajn2026-main
python3 prompt_v2/app_v2_patch.py

# 3. Zaaplikuj zmiany:
python3 prompt_v2/app_v2_patch.py --apply

# 4. Ustaw env var:
export PROMPT_VERSION=v2
```

Patcher robi backup (`app.py.v1.bak`) i aplikuje 7 zmian:

| # | Zmiana | Co robi |
|---|--------|---------|
| 1 | Import | `prompt_builder` → `prompt_v2.integration` |
| 2 | Response parsing | Strip `<thinking>` i `<article_section>` z output |
| 3 | Temperature | Automatyczna temp per batch type (INTRO=0.7, CONTENT=0.6, FAQ=0.4) |
| 4 | Entity tracker | Running JSON — które encje w którym batchu |
| 5 | Max tokens | (skip — 4000 działa OK) |
| 6 | Style anchor | Ulepszona ekstrakcja z INTRO (preferuje zdania z liczbami) |
| 7 | Prompt caching | `cache_control: ephemeral` na system prompt (~40% oszczędności) |

### Ścieżka B: Ręczna (minimalna)

Zmień tylko import w `app.py` linia ~29:

```python
# BYŁO:
from prompt_builder import (...)

# JEST:
from prompt_v2.integration import (
    build_system_prompt, build_user_prompt,
    build_faq_system_prompt, build_faq_user_prompt,
    build_h2_plan_system_prompt, build_h2_plan_user_prompt,
    build_category_system_prompt, build_category_user_prompt,
    get_api_params,
)
```

I dodaj `PROMPT_VERSION=v2` w env.

## Przełączanie v1 ↔ v2

```bash
export PROMPT_VERSION=v1   # Stare prompty
export PROMPT_VERSION=v2   # Nowe prompty
```

Na Render.com → Dashboard → Environment → `PROMPT_VERSION=v2`

## Granularne Feature Flags

```bash
export PROMPT_VERSION=v2

# Wyłącz konkretne features (domyślnie wszystkie ON):
export V2_FEW_SHOT=0
export V2_THINKING=0
export V2_POLISH=0
export V2_VOICE_ANCHOR=0
export V2_OUTLINE=0
export V2_ENTITY_TRACKER=0
export V2_FILTERED_S1=0
export V2_NATURAL_KW=0
```

### Zalecana kolejność wdrażania

1. **Tydzień 1:** `V2_FEW_SHOT=1` (~2.4× lepszą jakość)
2. **Tydzień 2:** + `V2_THINKING=1` + `V2_POLISH=1`
3. **Tydzień 3:** + `V2_VOICE_ANCHOR=1` + `V2_OUTLINE=1`
4. **Tydzień 4:** + `V2_NATURAL_KW=1` + `V2_FILTERED_S1=1`

## Co się zmieniło vs v1

### System Prompt
| Element | v1 | v2 |
|---|---|---|
| Persona | ~10 linii z CV | 3-4 zdania, cel + styl |
| Zasady | ~70% zakazów | ~70% pozytywnych zasad (konstytucja) |
| Polszczyzna | Brak | Dedykowany blok po polsku |
| Zakazane frazy | ~30+ | ~15-20 |
| Few-shot examples | 3-4 linii TAK/NIE | 2 pełne akapity ~100-150 słów |

### User Prompt
| Element | v1 | v2 |
|---|---|---|
| Kolejność | Instrukcje → dane | **Dane → instrukcje** |
| Article outline | Brak | Pełna struktura ✅/→/⬜ |
| Voice anchor | 3 zdania | Style anchor + kontynuacja |
| Entity context | 9 bloków | **Max 3 bloki** (filtrowane) |
| Keywords | Bullet list | Natural language |
| Planning | Brak | `<thinking>` block |

### API (app.py patch)
| Element | v1 | v2 |
|---|---|---|
| Temp INTRO | 0.7 (default) | **0.7** (auto) |
| Temp CONTENT | 0.7 (default) | **0.6** (auto) |
| Temp FAQ | 0.7 (default) | **0.4** (auto) |
| Prompt caching | Brak | `cache_control: ephemeral` |
| Entity tracker | Brak | Running JSON per batch |
| Style anchor | Losowe 3 zdania | Preferuje zdania z liczbami |

## Rollback

```bash
export PROMPT_VERSION=v1              # Prompty → v1
cp app.py.v1.bak app.py              # Cofnij patch app.py
```

## Pokrycie Playbooka: 39/39 ✅

- Część I: Architektura (4/4)
- Część II: System Prompt (10/10)
- Część III: User Prompt (7/7)
- Część IV: Anti-generyczność (4/4)
- Część V: Kontekst między batchami (3/3)
- Część VI: Parametry API (3/3)
- Część VII: Implementacja kodu (6/6)
- Część VIII: Metryki i testing (2/2)
