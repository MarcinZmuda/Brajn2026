<p align="center">
  <img src="static/logo_brajen.png" alt="BRAJEN" width="120">
</p>

<h1 align="center">BRAJEN SEO Engine</h1>

<p align="center">
  Automatyczny system generowania artykułów SEO<br>zoptymalizowanych pod polskojęzyczny Google
</p>

---

Pełny pipeline od analizy SERP po gotowy artykuł z walidacją YMYL, entity salience i gramatyką korpusową.

## Jak to działa

Użytkownik podaje **główne hasło** (np. *"jazda po alkoholu"*), opcjonalnie frazy, tryb i silnik AI. System przeprowadza 12-krokowy workflow emitowany w czasie rzeczywistym przez SSE:

```
Hasło → S1 Analysis (SERP + scraping) → YMYL Detection (prawo/medycyna/finanse)
      → H2 Planning → Brajen Project → Phrase Hierarchy
      → Batch Loop (generowanie sekcji z retry) → PAA/FAQ
      → Content Editorial (merytoryczny) → Editorial Review (gramatyczny)
      → Final Review + YMYL Validation → Redaktor Naczelny → Export HTML/DOCX
```

Łączny czas: **3–12 minut** zależnie od długości artykułu i YMYL enrichment.

## Architektura

```
┌──────────────────────────────────────────────────────────────┐
│  Frontend (ten repo)                          Render deploy  │
│  app.py ─── SSE orchestrator (6700 LOC)                      │
│  prompt_builder.py ─── ~15 formatterów promptów              │
│  ai_middleware.py ─── structured memory, retry, anaphora     │
│  polish_nlp_validator.py ─── NKJP corpus norms (12 params)  │
│  languagetool_checker.py ─── LanguageTool REST grammar       │
│  grammar_checker.py ─── auto-fix AI phrases + interpunkcja   │
│  entity_salience.py ─── Google NLP + schema.org + topical    │
│  llm_cost_tracker.py ─── token cost per workflow             │
│  keyword_dedup.py ─── word-boundary safe dedup               │
│  css_filter.py ─── S1 garbage entity cleanup                 │
│  shared_constants.py ─── NKJP targets (SENTENCE_AVG=13)     │
│  ymyl_disclaimer.py ─── automatyczne disclaimery prawne      │
│  prompt_v2/ ─── v2 prompt constants + style samples          │
│  templates/index.html ─── full SPA frontend (~3000 LOC)      │
└───────────────────────┬──────────────────────────────────────┘
                        │ HTTP
┌───────────────────────▼──────────────────────────────────────┐
│  master-seo-api (osobne repo)                 Render deploy  │
│  Brajen API — S1 analysis, project CRUD, batch validation,   │
│  editorial review, final review, phrase hierarchy, export     │
│  + Firebase persistence                                      │
└───────────────────────┬──────────────────────────────────────┘
                        │
              ┌─────────▼─────────┐
              │  Zewnętrzne API   │
              │  • Google SERP    │
              │  • SAOS (prawo)   │
              │  • PubMed (med.)  │
              │  • Wikipedia      │
              │  • Google NLP     │
              │  • LanguageTool   │
              └───────────────────┘
```

**Silniki AI:** Claude Sonnet/Opus (Anthropic) lub GPT-5.x (OpenAI) — wybór per workflow. Haiku jako helper (YMYL detection, memory, retry).

## Pipeline — krok po kroku

### KROK 1 · S1 Analysis
Brajen API odpytuje Google SERP, scrapi top-10 konkurencji. CompScraper dociąga pełne treści (do 5 stron). LLM generuje topical entities z typami (LAW/PROCESS/CONCEPT), co-occurrence pairs, SVO triples, warianty fleksyjne. Cleanup przez Claude Haiku (CSS garbage z nawigacji stron). Wynik: pełna mapa tematu.

### KROK 2 · YMYL Detection
Haiku klasyfikuje czy temat to prawo/medycyna/finanse. Jeśli tak: pobiera orzeczenia SAOS, publikacje PubMed, artykuły Wikipedia. Dane trafiają do promptów jako kontekst merytoryczny.

### KROK 3 · H2 Planning
LLM generuje plan sekcji z danych S1 — suggested H2s, content gaps, competitor patterns, PAA. Entity content plan przypisuje lead entity do każdej sekcji.

### KROK 4–5 · Project + Phrase Hierarchy
Brajen zakłada projekt z keyword targets i sem hints. Phrase hierarchy klasyfikuje rdzenie fraz — które pokryte przez dłuższe warianty, które wymagają standalone wplecenia.

### KROK 6 · Batch Loop
Serce systemu. Dla każdego H2: pobranie pre_batch (aktualny stan fraz, memory), dopasowanie kontekstu S1 per sekcja, budowanie promptu z ~15 formatterów, LLM call, walidacja Brajen (quality 0-100), adaptive retry (relaxed → adaptive, bez forced save). Voice continuity między batchami.

### KROK 7 · PAA / FAQ
Generowanie odpowiedzi na pytania PAA z SERP. Zapisywane jako ostatni batch.

### KROK 8 · Content Editorial
Brajen (Claude Opus) sprawdza artykuł merytorycznie — błędy, sprzeczności, brakujące informacje. Może zablokować artykuł jeśli krytyczne wady.

### KROK 9 · Editorial Review
Brajen poprawia gramatykę i styl. Rollback jeśli wynik < 75% oryginału. Lokalne `grammar_checker` usuwa frazy charakterystyczne dla AI.

### KROK 10 · Final Review + YMYL Validation
Finalny score artykułu. Walidacja prawna/medyczna pełnego tekstu. Citation pass — dopasowanie orzeczeń do konkretnych zdań.

### KROK 11 · Redaktor Naczelny
Claude Sonnet jako ekspert domenowy recenzuje artykuł. Auto-fix błędów krytycznych, artefaktów AI, problemów logicznych.

### KROK 12 · Export
HTML + DOCX. Done.

## Quality pipeline (post-generation)

Po generowaniu artykuł przechodzi przez zestaw analiz — wszystkie bezkosztowe (0 dodatkowych LLM calls):

| Analiza | Źródło | Co mierzy |
|---------|--------|-----------|
| **Polish NLP** | NKJP corpus | FOG-PL, TTR, hapax ratio, diakrytyki %, CV zdań, kolokacje — 12 parametrów vs normy publicystyczne |
| **LanguageTool** | Morfologik 3.5M | Gramatyka, kolokacje, interpunkcja, styl — walidacja korpusowa |
| **Entity Salience** | Google NLP API | Salience głównego hasła, dominacja, subject position |
| **Style Analysis** | Lokalny | CV zdań, passive ratio, avg sentence length — Anti-Frankenstein |
| **Semantic Distance** | CompScraper + S1 | Pokrycie fraz kluczowych vs konkurencja |
| **Readiness Checklist** | Agregacja | 8 kryteriów: word count, final score, editorial, salience, LT, style, semantic, YMYL |
| **Cost Tracker** | Token counting | Koszt workflow ($) z breakdown per step |

## Frontend

Single-page app w czystym JS (bez frameworków). Ciemny motyw, SSE real-time.

**Workflow tab** — 12-krokowy stepper, live article preview z formatowaniem (H2/H3/tabele/listy), batch chips z quality scores, pulsujący banner "W budowie" podczas generowania.

**Quality tab** — Final Review, Redaktor Naczelny, Entity Salience, Anti-Frankenstein Style, Polish NLP, LanguageTool, Content Editorial, Consistency Warnings, YMYL, Schema.org, Publication Readiness, Cost Summary.

**S1 tab** — pełna mapa tematu, entity coverage, content gaps.

**CI tab** — Competitive Intelligence dashboard, topical map, internal links.

**Edytor** — inline editing z Claude, zaznaczanie fragmentów tekstu, walidacja on-demand.

## Deploy

### Env vars (Render)

```
ANTHROPIC_API_KEY=sk-ant-...        # wymagane
ANTHROPIC_MODEL=claude-sonnet-4-6   # lub claude-opus-4-6
BRAJEN_API_URL=https://...          # URL master-seo-api
APP_USERNAME=...                    # basic auth
APP_PASSWORD=...
SECRET_KEY=...                      # session secret

# Opcjonalne — rozszerzają funkcjonalność:
OPENAI_API_KEY=sk-...               # dual-engine support
OPENAI_MODEL=gpt-5.2                # default OpenAI model
MIDDLEWARE_MODEL=claude-haiku-4-5-20251001  # helper model
GOOGLE_NLP_API_KEY=...              # entity salience
LANGUAGETOOL_URL=http://...         # self-hosted LT server
```

### Start

```bash
pip install -r requirements.txt
gunicorn app:app --bind 0.0.0.0:$PORT --timeout 300 --workers 1 --threads 2
```

Health check: `GET /api/health` → `{"status": "ok", "version": "67.0.0"}`

## Pliki

| Plik | LOC | Opis |
|------|-----|------|
| `app.py` | 6730 | SSE orchestrator — cały workflow pipeline |
| `prompt_builder.py` | ~2200 | 15+ prompt formatterów, system/user prompts |
| `entity_salience.py` | ~1400 | Google NLP, Schema.org, topical map, style analysis |
| `ai_middleware.py` | ~1700 | Structured memory, smart retry, anaphora check, domain validation |
| `polish_nlp_validator.py` | ~450 | 12 NKJP parameters vs corpus norms |
| `grammar_checker.py` | ~350 | Auto-fix AI phrases, interpunkcja |
| `languagetool_checker.py` | ~280 | LanguageTool REST API integration |
| `css_filter.py` | ~500 | S1 entity/ngram garbage filtering |
| `keyword_dedup.py` | ~200 | Word-boundary deduplication |
| `llm_cost_tracker.py` | 179 | Token cost tracking per workflow |
| `ymyl_disclaimer.py` | ~180 | Automatyczne disclaimery prawne/medyczne |
| `shared_constants.py` | 40 | NKJP targets, sentence/keyword limits |
| `prompt_v2/` | ~600 | V2 prompt constants, style samples, builders |
| `templates/index.html` | 2984 | Full SPA frontend |
| `templates/login.html` | ~170 | Login page |
