# BRAJEN SEO Web App v45.2.2

Standalone web app that replaces GPT Custom Actions.  
Full workflow: S1 → YMYL → Create → Hierarchy → Batch Loop (Claude Opus 4.6) → PAA → Editorial → Export.

## Quick Deploy on Render

### 1. Utwórz repo na GitHub
```bash
git init
git add .
git commit -m "BRAJEN SEO Web App v45.2.2"
git remote add origin https://github.com/TWOJ_USER/brajen-seo-app.git
git push -u origin main
```

### 2. Deploy na Render
1. Idź do [dashboard.render.com](https://dashboard.render.com)
2. **New → Web Service**
3. Połącz repo z GitHub
4. Render automatycznie wykryje `render.yaml`
5. Ustaw **Environment Variables** w dashboardzie:
   - `ANTHROPIC_API_KEY` = Twój klucz Anthropic (sk-ant-...)
   - `APP_PASSWORD` = hasło do logowania (np. TwojeHaslo123)
6. Kliknij **Deploy**

### 3. Gotowe
Po deploymencie dostaniesz URL:
```
https://brajen-seo-XXXX.onrender.com
```

## Environment Variables

| Zmienna | Wymagana | Opis |
|---------|----------|------|
| `ANTHROPIC_API_KEY` | ✅ | Klucz Anthropic API (sk-ant-...) |
| `APP_PASSWORD` | ✅ | Hasło do logowania |
| `APP_USERNAME` | ❌ | Login (domyślnie: brajen) |
| `ANTHROPIC_MODEL` | ❌ | Model (domyślnie: claude-opus-4-6) |
| `BRAJEN_API_URL` | ❌ | URL BRAJEN API (domyślnie: https://master-seo-api.onrender.com) |
| `SECRET_KEY` | ❌ | Flask secret (auto-generowany przez Render) |

## Jak to działa

```
[Browser] → [brajen-seo.onrender.com (Flask)]
                    ↓ wywołuje
            [master-seo-api.onrender.com (BRAJEN API)]
                    ↓ i
            [api.anthropic.com (Claude Opus 4.6 generuje tekst)]
```

1. User wpisuje keyword + H2 + frazy → klika Start
2. Flask backend **deterministycznie** wykonuje workflow krok po kroku
3. Każdy batch: pobiera instrukcje z BRAJEN API → generuje tekst przez Claude → wysyła do walidacji
4. Progress wyświetlany na żywo przez SSE (Server-Sent Events)
5. Na końcu: editorial review + export HTML/DOCX

**Zero symulacji. Zero "zapominania". Kod wymusza realne API calls.**

## Local Development

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
export APP_PASSWORD=test
python app.py
# → http://localhost:5000
```

## Troubleshooting

### Render cold start
BRAJEN API na Render usypia po 15min. Pierwszy request może trwać 30-60s.  
Apka ma wbudowany retry z backoff (3 próby: 5s, 15s, 30s).

### Timeout na batchu
Gunicorn timeout ustawiony na 300s. Jeśli batch trwa dłużej (np. Claude API wolne), zwiększ `--timeout` w render.yaml.

### SSE się rozłącza
Render ma limit 100s na response. Jeśli SSE się rozłączy, odśwież stronę.  
Możesz zwiększyć przez Render Pro plan lub dodać reconnect logic.
