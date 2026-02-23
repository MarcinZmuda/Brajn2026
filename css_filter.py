import re as _re

# ================================================================
# CSS/JS GARBAGE FILTER: czyści śmieci z S1 danych
# ================================================================
_CSS_GARBAGE_PATTERNS = _re.compile(
    r'(?:'
    # CSS properties & values
    r'webkit|moz-|ms-flex|align-items|display\s*:|flex-pack|'
    r'font-family|background-color|border-bottom|text-shadow|'
    r'position\s*:|padding\s*:|margin\s*:|transform\s*:|'
    r'transition|scrollbar|\.uk-|\.et_pb_|\.rp-|'
    r'min-width|max-width|overflow|z-index|opacity|'
    r'hover\{|active\{|:after|:before|calc\(|'
    r'woocommerce|gutters|inline-flex|box-pack|'
    r'data-[a-z]|aria-|role=|tabindex|'
    # BEM class notation (block__element, block--modifier)
    r'\w+__\w+|'
    r'\w+--\w+|'
    # CSS selectors & combinators
    r'focus-visible|#close|,#|\.css|'
    # WordPress / CMS artifacts
    r'\bvar\s+wp\b|wp-block|wp-embed|'
    r'block\s*embed|content\s*block|text\s*block|'
    r'input\s*type|'
    # HTML/UI element names
    r'^(header|footer|sidebar|nav|mega)\s*-?\s*menu$|'
    r'^sub-?\s*menu$|'
    r'^mega\s+menu$|'
    # Generic CSS patterns
    r'^\w+\.\w+$|'
    r'[{};]'
    r')',
    _re.IGNORECASE
)

_CSS_NGRAM_EXACT = {
    "min width", "width min", "ms flex", "align items", "flex pack",
    "box pack", "table table", "decoration decoration", "inline flex",
    "webkit box", "webkit text", "moz box", "moz flex",
    "box align", "flex align", "flex direction", "flex wrap",
    "justify content", "text decoration", "font weight", "font size",
    "line height", "border radius", "box shadow", "text align",
    "text transform", "letter spacing", "word spacing", "white space",
    "min height", "max height", "list style", "vertical align",
    "before before", "data widgets", "widgets footer", "footer widget",
    "focus focus", "root root", "not not",
    # WordPress / CMS
    "var wp", "block embed", "content block", "text block", "input type",
    "wp block", "wp embed", "post type", "nav menu", "menu item",
    "header menu", "sub menu", "mega menu", "footer menu",
    "widget area", "sidebar widget", "page template",
    # v45.4.1: Extended: catches observed CSS garbage from dashboard
    "list list", "heading heading", "container expand", "expand container",
    "container item", "container container", "table responsive",
    "heading heading heading", "list list list", "list list list list",
    "container expand container", "form form", "button button",
    "image utf", "image image", "form input", "input input",
    "expand expand", "item item", "block block", "section section",
    "row row", "column column", "grid grid", "card card",
    "wrapper wrapper", "inner inner", "outer outer",
    "responsive table", "responsive responsive",
    # v49: CSS variable patterns from SERP scraping
    "ast global", "global color", "ast global color", "var ast",
    "var ast global", "var ast global color", "var global",
    "global ast", "color inherit", "inherit color",
    # v50.4: WordPress social sharing widgets / footer artifacts
    "block social", "social link", "social block", "link block",
    "style logos", "logos only", "only social", "social link block",
    "link block social", "logos only social", "style logos only",
    "only social link", "logos only social link",
    "style logos only social", "social link block social",
    "only social link block", "wp preset", "preset gradient",
    # v50.7 FIX 39: CSS @font-face declaration fragments
    "font family", "face font", "font style", "font weight",
    "weight font", "display swap", "swap src", "src url",
    "url blog", "blog wp", "content fonts", "unicode range",
    "face font family", "weight font display", "font display swap",
    "display swap src", "swap src url", "src url blog",
    "font face", "woff2 format", "woff format", "ttf format",
    "font awesome", "awesome regular", "awesome solid", "awesome brands",
    # v50.7: WordPress content/blog patterns
    "wp content", "content uploads", "content themes", "content plugins",
    "wp includes", "wp json", "wp admin",
}

_CSS_ENTITY_WORDS = {
    "inline", "button", "active", "hover", "flex", "grid", "block",
    "none", "inherit", "auto", "hidden", "visible", "relative",
    "absolute", "fixed", "static", "center", "wrap", "nowrap",
    "bold", "normal", "italic", "transparent", "solid", "dotted",
    "pointer", "default", "disabled", "checked", "focus",
    "where", "not", "root", "before", "after",
    # HTML/UI elements
    "menu", "submenu", "sidebar", "footer", "header", "widget",
    "navbar", "dropdown", "modal", "tooltip", "carousel",
    "accordion", "breadcrumb", "pagination", "thumbnail",
    # v49: CSS variable tokens & font names
    "ast", "var", "global", "color", "sich", "un", "uw",
    "xl", "ac", "arrow", "dim",
    "menlo", "monaco", "consolas", "courier", "arial", "helvetica",
    "verdana", "georgia", "roboto", "poppins", "raleway",
    # v50.4: Scraper artifacts: English words spaCy misclassifies as entities
    # These are CSS class names, color names, or HTML content words that
    # appear in competitor pages and get extracted as Polish entities.
    "vivid", "bluish", "muted", "faded", "bright", "subtle", "crisp",
    "reviews", "review", "rating", "ratings", "share", "shares",
    "click", "submit", "cancel", "close", "open", "toggle", "expand",
    "czyste", "clean", "dark", "light", "primary", "secondary",
    "success", "warning", "danger", "info", "muted",
    # v50.4: Social media / platform names (scraper picks up footer links)
    "facebook", "twitter", "instagram", "linkedin", "youtube",
    "pinterest", "tiktok", "snapchat", "whatsapp", "telegram",
    "bandcamp", "bluesky", "deviantart", "fivehundredpx", "mastodon",
    "reddit", "tumblr", "flickr", "vimeo", "soundcloud", "spotify",
    # v50.4: WordPress/CMS artifact words
    "preset", "logos", "embed", "widget", "template", "shortcode",
    "plugin", "theme", "customizer", "gutenberg", "elementor",
    # v50.5 FIX 23: Wikipedia sidebar language names
    # Scraper extracts language links from Wikipedia interlanguage sidebar.
    # spaCy misclassifies these as PERSON/LOC entities with high salience.
    "asturianu", "azərbaycanca", "afrikaans", "aragonés", "bân",
    "català", "čeština", "cymraeg", "dansk", "eesti", "esperanto",
    "euskara", "galego", "hrvatski", "ido", "interlingua",
    "íslenska", "italiano", "kurdî", "latina", "latviešu",
    "lietuvių", "magyar", "македонски", "bahasa", "melayu",
    "nordfriisk", "nynorsk", "occitan", "oʻzbekcha", "piemontèis",
    "português", "română", "shqip", "sicilianu", "slovenčina",
    "slovenščina", "srpskohrvatski", "suomi", "svenska", "tagalog",
    "türkçe", "українська", "tiếng", "việt", "volapük",
    "walon", "winaray", "ייִדיש",
    "башҡортса", "беларуская", "български", "қазақша", "кыргызча",
    "монгол", "русский", "српски", "татарча", "тоҷикӣ", "ўзбекча",
    "العربية", "فارسی", "עברית", "हिन्दी", "বাংলা",
    "ગુજરાતી", "ಕನ್ನಡ", "தமிழ்", "తెలుగు",
    "中文", "日本語", "한국어", "粵語",
    # Common multi-word Wikipedia language labels
    "fiji hindi", "basa jawa", "basa sunda", "kreyòl ayisyen",
    # v50.5 FIX 24: Wikipedia/website navigation artifacts
    # Buttons, links, and navigation elements scraped as entities
    "przejdź", "sprawdź", "edytuj", "historia", "dyskusja",
    "zaloguj", "utwórz", "szukaj", "wyszukaj", "pokaż",
    "ukryj", "rozwiń", "zwiń", "zamknij", "otwórz",
    "czytaj", "wyświetl", "pobierz", "udostępnij",
    "read", "view", "edit", "search", "login", "signup",
    "subscribe", "download", "upload", "skip", "next", "previous",
    "more", "less", "show", "hide", "back", "forward",
}

def _is_css_garbage(text):
    if not text or not isinstance(text, str):
        return True
    text = text.strip()
    if len(text) < 2:
        return True
    special = sum(1 for c in text if c in '{}:;()[]<>=#.@')
    if len(text) > 0 and special / len(text) > 0.15:
        return True
    if text.lower() in _CSS_NGRAM_EXACT:
        return True
    if text.lower() in _CSS_ENTITY_WORDS:
        return True
    # v47.2: CSS compound tokens: inherit;color, section{display, serif;font
    t_lower = text.lower()
    if _re.match(r'^[\w-]+[;{}\[\]:]+[\w-]+$', t_lower):
        _CSS_TOKENS = {
            "inherit", "color", "display", "flex", "block", "inline", "grid",
            "none", "auto", "hidden", "visible", "solid", "dotted", "dashed",
            "bold", "normal", "italic", "pointer", "cursor", "border",
            "margin", "padding", "font", "section", "strong", "help",
            "center", "wrap", "cover", "contain", "serif", "sans",
            "position", "relative", "absolute", "fixed", "opacity",
            "background", "transform", "overflow", "scroll", "width",
            "height", "text", "decoration", "underline", "uppercase",
            "hover", "focus", "active", "image", "repeat", "content",
            "table", "row", "column", "collapse", "weight", "size", "style",
        }
        parts = _re.split(r'[;{}\[\]:]+', t_lower)
        parts = [p.strip('-') for p in parts if p]
        if parts and any(p in _CSS_TOKENS for p in parts):
            return True
    # v47.2: Font names
    _FONT_NAMES = {
        "menlo", "monaco", "consolas", "courier", "arial", "helvetica",
        "verdana", "georgia", "tahoma", "trebuchet", "lucida", "roboto",
        "poppins", "raleway", "montserrat", "lato", "inter",
    }
    if t_lower in _FONT_NAMES:
        return True
    # v45.4.1: Detect repeated-word patterns ("list list list", "heading heading")
    words = text.lower().split()
    if len(words) >= 2 and len(set(words)) == 1:
        return True  # All words identical ("list list", "heading heading heading")
    if len(words) >= 3 and len(set(words)) <= 2:
        return True  # 3+ words but only 1-2 unique ("container expand container")
    # v45.4.1: Detect CSS class-like multi-word tokens
    # Only flag if ALL words are short ASCII-only AND match common CSS vocabulary
    _CSS_VOCAB = {
        'list', 'heading', 'container', 'expand', 'item', 'image', 'form',
        'table', 'responsive', 'button', 'section', 'row', 'column', 'grid',
        'card', 'wrapper', 'inner', 'outer', 'block', 'embed', 'content',
        'input', 'label', 'icon', 'link', 'nav', 'tab', 'panel', 'modal',
        'badge', 'alert', 'toast', 'spinner', 'loader', 'overlay', 'toggle',
        'dropdown', 'collapse', 'accordion', 'breadcrumb', 'pagination',
        'thumbnail', 'carousel', 'slider', 'progress', 'tooltip', 'popover',
        'utf', 'meta', 'viewport', 'charset', 'script', 'noscript',
        'dim', 'cover', 'inherit', 'font', 'serif', 'sans', 'display',
        'border', 'margin', 'padding', 'strong', 'color',
        # v49: CSS variable tokens
        'ast', 'var', 'global', 'min', 'max', 'wp',
        # v50.7 FIX 39: CSS font-face declaration fragments from @font-face rules
        'family', 'face', 'style', 'weight', 'swap', 'src', 'url',
        'unicode', 'range', 'fonts', 'woff', 'woff2', 'ttf', 'eot', 'svg',
        'format', 'local', 'fallback', 'optional', 'preload',
        # v50.7: Font Awesome / icon fonts scraped as entities
        'awesome', 'regular', 'solid', 'brands', 'duotone', 'sharp',
        'fa', 'fab', 'fas', 'far', 'fal', 'fad',
        # v50.7: Blog/CMS URL fragments
        'blog', 'post', 'page', 'category', 'tag', 'author', 'archive',
        'sidebar', 'footer', 'header', 'nav', 'menu',
    }
    if len(words) >= 2 and all(w in _CSS_VOCAB for w in words):
        return True
    # v50.4: Sentence fragments: real entities are max 5-6 words,
    # scraper sometimes extracts entire sentence fragments as "entities"
    if len(words) > 6:
        return True
    # v50.4: Pure ASCII single words that aren't Polish proper nouns
    # These are typically CSS class names, HTML element names, or English words
    # that spaCy misclassifies as entities in Polish competitor pages.
    if len(words) == 1 and text.isascii() and text[0].islower():
        return True  # Lowercase single ASCII word = never a Polish entity
    # v50.5 FIX 23: Multi-word Wikipedia sidebar artifacts
    # When scraper concatenates adjacent language links: "Asturianu Azərbaycanca"
    # Check if ALL words in the text are known Wikipedia language names
    if len(words) >= 2:
        _all_wiki_lang = all(w.lower() in _CSS_ENTITY_WORDS for w in words)
        if _all_wiki_lang:
            return True  # All words are blocked terms -> garbage
    # v50.5 FIX 23: Detect non-Polish/non-English single capitalized words
    # Wikipedia sidebar contains language names in native script (Turkce, Cestina...)
    # Polish proper nouns contain Polish diacritics (a, c, e, l, n, o, s, z, z)
    # but NOT characters like e, o, u, c, s, d, p, n etc.
    if len(words) == 1 and len(text) >= 3 and text[0].isupper():
        _NON_POLISH_CHARS = set("əöüçşðþñãâêîôûàèìòùäëïü")
        if any(c.lower() in _NON_POLISH_CHARS for c in text):
            return True  # Contains non-Polish diacritics -> likely Wikipedia language name
    # v50.7 FIX 39: Hex color codes (A7FF, FEFC, FF00, 3B82F6 etc.)
    # Scraper extracts CSS hex colors as "entities"
    if len(words) == 1 and _re.match(r'^[0-9A-Fa-f]{3,8}$', text):
        return True  # Pure hex string -> CSS color code
    # v50.7 FIX 39: Font Awesome / icon font declarations
    if 'font awesome' in t_lower or 'fontawesome' in t_lower:
        return True
    # v50.7 FIX 39: CSS strings with quotes ('"Font Awesome 6 Regular";')
    if '"' in text or "'" in text:
        # Entities shouldn't contain quotes, these are CSS font-family values
        stripped = text.replace('"', '').replace("'", '').replace(';', '').strip()
        if stripped.lower() in {'font awesome', 'font awesome 6', 'font awesome 6 regular',
                                'font awesome 6 free', 'font awesome 6 brands',
                                'font awesome 5', 'font awesome 5 free'}:
            return True
        # Any string with semicolons + quotes = CSS
        if ';' in text:
            return True
    # v50.7 FIX 39: Detect CSS @font-face artifacts in multi-word strings
    _FONT_FACE_WORDS = {'font', 'family', 'face', 'style', 'weight', 'swap',
                        'src', 'url', 'unicode', 'range', 'format', 'woff',
                        'woff2', 'ttf', 'eot', 'local', 'awesome', 'regular'}
    if len(words) >= 2 and all(w in _FONT_FACE_WORDS for w in words):
        return True
    return bool(_CSS_GARBAGE_PATTERNS.search(text))

def _extract_text(item):
    """Extract text value from entity dict or string."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return (item.get("entity") or item.get("text") or item.get("name")
                or item.get("ngram") or item.get("phrase") or "")
    return str(item)

def _filter_entities(entities):
    if not entities:
        return []
    clean = []
    brand_count = 0
    medicine_brand_count = 0  # v45.3: track medicine brands separately
    for ent in entities:
        if isinstance(ent, dict):
            text = ent.get("text", "") or ent.get("entity", "") or ent.get("name", "")
            if _is_css_garbage(text):
                continue
            # v45.3: Medicine/pharmaceutical brand check — max 1 per article
            if _is_medicine_brand(text):
                medicine_brand_count += 1
                if medicine_brand_count > 1:
                    continue  # Skip excess medicine brands
            # v50: Brand entity cap: max 2 brand entities per article
            if _is_brand_entity(text):
                brand_count += 1
                if brand_count > 2:
                    continue  # Skip excess brands
            clean.append(ent)
        elif isinstance(ent, str):
            if _is_css_garbage(ent):
                continue
            if _is_medicine_brand(ent):
                medicine_brand_count += 1
                if medicine_brand_count > 1:
                    continue
            if _is_brand_entity(ent):
                brand_count += 1
                if brand_count > 2:
                    continue
            clean.append(ent)
    return clean


# v50: Brand entity detection patterns
_BRAND_PATTERNS = {
    # Energy companies (common in "prąd" articles)
    "tauron", "pge", "enea", "energa", "innogy", "rwe", "e.on", "edf",
    # Telecom
    "orange", "play", "t-mobile", "plus", "polkomtel", "vectra",
    # Banks
    "pko", "mbank", "ing", "santander", "pekao", "bnp paribas", "millennium",
    # Insurance
    "pzu", "warta", "ergo hestia", "allianz", "generali", "axa",
    # Tech / general
    "allegro", "amazon", "google", "microsoft", "apple", "samsung",
    # Legal entity suffixes
    "s.a.", "sp. z o.o.", "sp.j.", "s.c.",
}

# v45.3: Pharmaceutical / medicine brand detection
_MEDICINE_BRAND_PATTERNS = {
    # Polish OTC medicine brands
    "sunewd", "sunewmed", "nurofen", "apap", "no-spa", "no spa",
    "strepsils", "flegamina", "hedelix", "mucosolvan",
    "rutinoscorbin", "polopiryna", "gripex", "theraflu",
    "coldrex", "fervex", "cholinex", "ibuprom", "metafen",
    "ketonal", "voltaren", "fastum", "diclac", "naproxen",
    "tantum verde", "neo-angin", "strepfen", "orofar",
    # Supplement brands
    "solgar", "swanson", "now foods", "olimp", "biotech",
    # Cosmetic/health brands (common in medical articles)
    "neutrogena", "cetaphil", "eucerin", "avène", "avene",
    "bioderma", "vichy", "la roche-posay", "laroche",
    "cerave", "dove", "nivea",
}

def _is_medicine_brand(text: str) -> bool:
    """v45.3: Check if entity looks like a pharmaceutical product/medicine brand."""
    if not text:
        return False
    t = text.lower().strip()
    # Direct match
    if t in _MEDICINE_BRAND_PATTERNS:
        return True
    # Partial match (e.g. "SunewMed+ serum")
    for pattern in _MEDICINE_BRAND_PATTERNS:
        if pattern in t:
            return True
    # Heuristic: contains ® or + (common in product names)
    if "®" in text or (text.endswith("+") and len(text) > 3):
        return True
    return False

def _is_brand_entity(text: str) -> bool:
    """Check if entity text looks like a brand/company name."""
    if not text:
        return False
    t = text.lower().strip()
    # Direct match
    if t in _BRAND_PATTERNS:
        return True
    # Partial match (e.g. "TAURON Dystrybucja S.A.")
    for pattern in _BRAND_PATTERNS:
        if pattern in t:
            return True
    # Heuristic: ends with legal entity suffix
    if any(t.endswith(suf) for suf in (" s.a.", " sp. z o.o.", " sp.j.", " s.c.", " sa", " sp z oo")):
        return True
    return False

def _filter_ngrams(ngrams):
    if not ngrams:
        return []
    clean = []
    for ng in ngrams:
        text = ng.get("ngram", ng) if isinstance(ng, dict) else str(ng)
        if not _is_css_garbage(text):
            clean.append(ng)
    return clean
