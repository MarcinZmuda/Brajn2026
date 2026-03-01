"""
═══════════════════════════════════════════════════════════
BRAJEN PROMPT BUILDER v2.1
═══════════════════════════════════════════════════════════
v2.1 changes (vs v1.1):
  - System prompt: ~900 słów (było ~3500). Usunięto:
    * 8 kategorii ANTY-AI → krótka lista + grammar_checker
    * Subject rotation / position rule → usunięte
    * Opening patterns A-F → naturalna wolność
    * Mosty semantyczne → kolokacja wystarczy
    * Passage-first 40-58 słów → "odpowiedz wprost"
    * Limity zdań w prompcie → walidator post-hoc
  - User prompt: 10 formatterów (było 18). Usunięto:
    * _fmt_smart_instructions → duplikuje system
    * _fmt_coverage_density → reviewer
    * _fmt_phrase_hierarchy → reviewer
    * _fmt_natural_polish → reviewer
    * _fmt_style → zintegrowany w system prompt
    * _fmt_depth_signals → expert persona
    * _fmt_experience_markers → expert persona
    * _fmt_causal_context → naturalny autor
  - EAV/SVO: "jeśli pasują" zamiast "MUSI"
  - Entity SEO: 3 zasady (kolokacja, nazewnictwo, hierarchia)
  - Intro: 3 proste punkty (definicja → kontekst → zapowiedź)

Architecture:
  SYSTEM PROMPT = Expert persona + Minimal rules
  USER PROMPT   = Data-driven instructions (no micromanagement)
  Category/FAQ/H2 builders = unchanged from v1.1
═══════════════════════════════════════════════════════════
"""

import json
import logging

try:
    from shared_constants import (
        SENTENCE_AVG_TARGET, SENTENCE_AVG_TARGET_MIN, SENTENCE_AVG_TARGET_MAX,
        SENTENCE_SOFT_MAX, SENTENCE_HARD_MAX, SENTENCE_AVG_MAX_ALLOWED
    )
except ImportError:
    SENTENCE_AVG_TARGET = 13
    SENTENCE_AVG_TARGET_MIN = 8
    SENTENCE_AVG_TARGET_MAX = 20
    SENTENCE_SOFT_MAX = 30
    SENTENCE_HARD_MAX = 40
    SENTENCE_AVG_MAX_ALLOWED = 22

_pb_logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════

def _word_trim(text, max_chars):
    if not text or len(text) <= max_chars:
        return text
    trimmed = text[:max_chars]
    nl = chr(10)
    last_break = max(trimmed.rfind(" "), trimmed.rfind(nl), trimmed.rfind(". "))
    if last_break > max_chars // 2:
        trimmed = trimmed[:last_break]
    return trimmed.rstrip(" ,;:") + "..."


def _find_variants(keyword, variant_dict):
    """Find variants for a keyword in the entity variant dictionary.
    Matches exact key or by 4-char Polish stem prefix."""
    if not keyword or not variant_dict:
        return []
    kw_lower = keyword.lower().strip()
    # Exact match
    for key, variants in variant_dict.items():
        if key.lower().strip() == kw_lower:
            return variants
    # Stem match (first 4 chars of each word)
    kw_stems = set(w[:4] for w in kw_lower.split() if len(w) >= 4)
    if not kw_stems:
        return []
    for key, variants in variant_dict.items():
        key_stems = set(w[:4] for w in key.lower().split() if len(w) >= 4)
        if kw_stems and key_stems and kw_stems & key_stems:
            return variants
    return []


# ════════════════════════════════════════════════════════════
# PERSONAS (v2.1)
# ════════════════════════════════════════════════════════════

_PERSONAS = {
    "prawo": (
        "Jesteś prawnikiem-praktykiem i dziennikarzem prawnym.\n"
        "Wzorzec: Prawo.pl + GazetaPrawna — nie komentarz akademicki.\n"
        "Każdy przepis = sygnatura + konsekwencja + typowa sytuacja.\n"
        "Podmiot konkretny: sąd zasądza, wierzyciel składa, dłużnik płaci.\n"
        "Opinie dozwolone, ale z podstawą prawną — nie 'wydaje się'."
    ),
    "medycyna": (
        "Jesteś dziennikarzem medycznym z wiedzą kliniczną.\n"
        "Wzorzec: Medycyna Praktyczna (dział pacjent) — spokojny, precyzyjny, bez alarmu.\n"
        "Podmiot konkretny: lekarz zaleca, pacjent przyjmuje, organizm wytwarza.\n"
        "Opisuj PROCESY biologiczne, nie efekty marketingowe.\n"
        "Uczciwość wobec ograniczeń: 'nie ma leków o udowodnionym działaniu' > obietnica."
    ),
    "finanse": (
        "Jesteś dziennikarzem finansowym i analitykiem.\n"
        "Wzorzec: Bankier.pl SMART — nie Forbes, nie press release.\n"
        "Tłumaczysz liczby na język portfela: każda stopa + RATA, każda opłata + HORYZONT.\n"
        "Podawaj WARIANTY — scenariusz optymistyczny vs pesymistyczny z liczbami.\n"
        "Terminologia inline: RRSO, WIBOR, LTV = jednozdaniowe wyjaśnienie przy 1. użyciu."
    ),
    "technologia": (
        "Jesteś dziennikarzem technologicznym i testerem sprzętu.\n"
        "Wzorzec: Benchmark.pl — nie press release producenta.\n"
        "Parametr bez scenariusza to martwy numer. SPEC → KONTEKST → SCENARIUSZ.\n"
        "CENA W PLN obowiązkowa przy każdym produkcie. Segmentacja: budżet / średnia / premium.\n"
        "Nazwy technologii: pełna + wyjaśnienie inline przy 1. użyciu, potem skrót."
    ),
    "budownictwo": (
        "Jesteś inżynierem budownictwa i dziennikarzem technicznym.\n"
        "Wzorzec: MuratorDom.pl + BudujemyDom.pl — nie katalog producenta.\n"
        "Ton doradcy z placu budowy: PARAMETR + NORMA + KONTEKST w każdym akapicie.\n"
        "Koszty: MATERIAŁ + ROBOCIZNA osobno (zł/m²). Porównanie technologii z λ i ceną.\n"
        "Etapowanie: kolejność prac + warunki + konsekwencja pominięcia."
    ),
    "uroda": (
        "Jesteś redaktorką beauty z wiedzą kosmetologiczną.\n"
        "Wzorzec: Paula's Choice (evidence) + Wizaz.pl (ton) — nie katalog producenta.\n"
        "SKŁADNIK → MECHANIZM → STĘŻENIE → ŁĄCZENIE w każdym akapicie.\n"
        "Każdy składnik = INCI + polska nazwa + pora aplikacji + typ cery.\n"
        "Granica: pielęgnacja = uroda, dermatologia kliniczna = medycyna → kieruj do lekarza."
    ),
    "lifestyle": (
        "Jesteś dziennikarzem kulturalnym i redaktorem lifestyle.\n"
        "Wzorzec: między Vogue Polska a Noizz — inteligentny, ale nie pretensjonalny.\n"
        "Konkretne nazwy własne: projektant, dom mody, kolekcja, sezon.\n"
        "Kontekst kulturowy: nie opisuj trendu — WYJAŚNIJ go (dlaczego teraz, skąd, co komunikuje).\n"
        "Opinie subtelnie: parentezą, zestawieniem, krótką pointą. Understatement > patos."
    ),
    "inne": (
        "Jesteś doświadczonym dziennikarzem i redaktorem.\n"
        "Twoja siła to rzemiosło: konkret, kontekst, pointa.\n"
        "Każde twierdzenie = min. 1 nazwa własna, liczba, data lub źródło.\n"
        "Nie opisuj — WYJAŚNIAJ: dlaczego, skąd, co z tego wynika.\n"
        "Pisz jak dziennikarz, nie jak influencer. Zero clickbaitu, zero infantylizmu."
    ),
}

# ── Category-specific density/style rules (injected into system prompt) ──
_CATEGORY_STYLE = {
    "prawo": (
        "PRZEPISY: sygnatura + konsekwencja + typowa sytuacja.\n"
        "  ❌ 'Sąd może orzec karę' → ✅ 'Grozi grzywna 5 000–30 000 zł lub zakaz na 3–15 lat (art. 178a § 1 k.k.)'\n"
        "  Gdy SERP podaje sygnatury/orzeczenia → użyj ich.\n"
        "CASE STUDY: min. 1 typowa sytuacja na sekcję H2.\n"
        "  Używaj archetypów (Kowalski, kierowca, właściciel) — NIE wymyślaj sygnatur ani kwot.\n"
        "PODMIOT: Sąd zasądza. Inwestor składa. Dłużnik płaci.\n"
        "  ❌ 'Można złożyć wniosek' → ✅ 'Wierzyciel składa wniosek'\n"
        "  ❌ 'Należy pamiętać' → ✅ 'Sąd bierze pod uwagę'\n"
        "ZAMKNIĘCIE AKAPITU: konsekwencja prawna w 1 zdaniu.\n"
        "  ✅ 'Brak oświadczenia w terminie 6 mies. = przyjęcie spadku z dobrodziejstwem inwentarza.'\n"
        "BLACKLISTA: 'w świetle obowiązujących przepisów', 'zgodnie z literą prawa',\n"
        "  'ustawodawca przewidział', 'regulacja ta ma na celu', 'na gruncie prawa'."
    ),
    "medycyna": (
        "PRECYZJA: podmiot konkretny + dawka + czas + mechanizm.\n"
        "  ❌ 'Lek pomaga na ból' → ✅ 'Ibuprofen 400 mg co 6–8 h łagodzi ból w ciągu 30–60 min\n"
        "     — blokuje cyklooksygenazę, hamując syntezę prostaglandyn.'\n"
        "MECHANIZM > OBIETNICA: opisuj procesy biologiczne, nie efekty.\n"
        "  ❌ 'Skuteczny lek' → ✅ 'Antybiotyk hamuje namnażanie bakterii, ale nie cofa\n"
        "     uszkodzeń toksycznych — dlatego kaszel utrzymuje się mimo leczenia.'\n"
        "FAZY CHOROBY jako oś narracji: wylęganie → objawy → leczenie → zdrowienie.\n"
        "DAWKI: TYLKO gdy SERP je podaje. Inaczej → mechanizm + 'dawkę ustala lekarz'.\n"
        "SYGNAŁY ALARMOWE: 'Wizyta u lekarza jest konieczna, gdy...' (nie 'warto skonsultować').\n"
        "BLACKLISTA: 'rewolucyjny lek', 'skuteczne leczenie', 'cudowne właściwości',\n"
        "  'nowoczesna terapia', 'groźna choroba', 'w 100 % bezpieczny', 'detox',\n"
        "  'wzmacnia odporność', 'oczyszcza organizm'."
    ),
    "finanse": (
        "WYLICZENIE > KOMENTARZ:\n"
        "  Gęstość: min. 2 konkretne liczby (kwota, %, stawka, termin) na akapit.\n"
        "  Każda liczba + HORYZONT: '12 zł/mies. × 30 lat = 4 320 zł'.\n"
        "  Każda stopa + RATA: 'Oprocentowanie 7,5 % przy 300 000 zł = rata ok. 2 100 zł/mies.'\n"
        "  Gdy SERP podaje ofertę → PRZEPISZ: nazwa banku + kwota + oprocentowanie.\n"
        "TERMINOLOGIA INLINE: każdy termin finansowy = jednozdaniowe wyjaśnienie przy 1. użyciu.\n"
        "  ✅ 'RRSO (rzeczywista roczna stopa oprocentowania — uwzględnia marżę, prowizję\n"
        "     i ubezpieczenia) wynosi 7,2 %.'\n"
        "  Po pierwszym wyjaśnieniu → sam skrót.\n"
        "WARIANTY: scenariusz optymistyczny vs pesymistyczny z liczbami.\n"
        "  ❌ 'Stałe oprocentowanie zapewnia spokój' → ✅ 'Stałe 6,4 %: rata 3 124 zł.\n"
        "     Zmienne dziś mniej, ale po wzroście stóp o 1 p.p. rata rośnie o ok. 350 zł.'\n"
        "TABELE: gdy 3+ produkty/oferty → <table> z kolumnami: Produkt | Oprocentowanie | Rata | RRSO.\n"
        "BLACKLISTA: 'korzystne warunki', 'atrakcyjne oprocentowanie', 'konkurencyjna oferta',\n"
        "  'może się opłacać', 'warto rozważyć', 'inwestycja w przyszłość', 'gwarantowany zysk'."
    ),
    "technologia": (
        "SPEC → KONTEKST → SCENARIUSZ (w każdym akapicie):\n"
        "  1. PARAMETR: nazwa technologii, wartość liczbowa.\n"
        "  2. KONTEKST: porównanie z poprzednią generacją lub standardem rynkowym.\n"
        "  3. SCENARIUSZ: co to zmienia w praktyce dla użytkownika.\n"
        "  ❌ 'Wi-Fi 7 oferuje 46 Gbps' → ✅ 'Wi-Fi 7 (46 Gbps) — 4× szybciej niż Wi-Fi 6.\n"
        "     W praktyce: stabilny streaming 8K na 3 urządzeniach jednocześnie.'\n"
        "CENA — OBOWIĄZKOWA: każdy produkt z nazwy = cena w PLN lub przedział.\n"
        "  ❌ 'ASUS ROG to płyta premium' → ✅ 'ASUS ROG Maximus Z890 Hero — ok. 3 000 zł.'\n"
        "  Segmentacja: budżet / średnia / premium z widełkami PLN.\n"
        "NAZWY TECHNOLOGII: pełna nazwa + wyjaśnienie inline przy 1. użyciu, potem skrót.\n"
        "  ✅ 'Litografia Intel 18A (następca TSMC 3 nm) — mniejszy pobór energii.'\n"
        "WERDYKT: zamykaj akapit 1 zdaniem — dla kogo, za ile, czy warto czekać.\n"
        "BLACKLISTA: 'rewolucyjny', 'przełomowy', 'game changer', 'niesamowita wydajność',\n"
        "  'imponujące parametry', 'w przystępnej cenie', 'bogata specyfikacja'."
    ),
    "budownictwo": (
        "PARAMETR + NORMA + KONTEKST (w każdym akapicie technicznym):\n"
        "  ❌ 'Dobra izolacyjność' → ✅ 'U = 0,15 W/(m²·K) — norma WT: max. 0,20. Zapas 25 %.'\n"
        "  Materiały izolacyjne ZAWSZE: λ [W/(m·K)] + grubość + wariant.\n"
        "  ✅ 'Styropian grafitowy (λ = 0,032) 14 cm vs biały (λ = 0,044) 20 cm\n"
        "     — ten sam efekt, mniejsza grubość, wyższa cena.'\n"
        "KOSZTY — MATERIAŁ + ROBOCIZNA OSOBNO:\n"
        "  ❌ 'Ocieplenie ok. 200 zł/m²' → ✅ 'Materiał ok. 50 zł/m², robocizna ok. 110 zł/m².\n"
        "     Razem: ok. 160 zł/m² bez tynku.'\n"
        "  Gdy SERP podaje cenę → PRZEPISZ z datą aktualności.\n"
        "PORÓWNANIE TECHNOLOGII: gdy wybór materiału → tabela lub A vs B vs C.\n"
        "  Kolumny: Materiał | λ | Grubość | Cena zł/m² | Uwagi.\n"
        "ETAPOWANIE: kolejność prac + warunki atmosferyczne + zależności.\n"
        "  ✅ 'Klejenie płyt: temp. 5–25°C, brak deszczu. PRZED kołkowaniem — min. 24 h schnięcia.'\n"
        "BLACKLISTA: 'dobra izolacyjność', 'wysoka wytrzymałość', 'innowacyjna technologia',\n"
        "  'odpowiednia grubość', 'profesjonalna ekipa', 'marzenie o własnym domu'."
    ),
    "uroda": (
        "SKŁADNIK → MECHANIZM → STĘŻENIE → ŁĄCZENIE (hierarchia akapitu):\n"
        "  1. INCI + polska nazwa: ✅ 'Niacynamid (INCI: Niacinamide, witamina B3)'\n"
        "  2. MECHANIZM w 1 zdaniu: ✅ 'Hamuje transfer melanosomów → wyrównuje koloryt.'\n"
        "  3. STĘŻENIE: ✅ 'Skuteczne: od 2 %, optymalne: 5 %. Powyżej 10 % — ryzyko podrażnienia.'\n"
        "  4. ŁĄCZENIE: ✅ 'Z retinolem: TAK (łagodzi podrażnienia). Z AHA/BHA: ostrożnie (pH).'\n"
        "RUTYNA: każdy składnik = pora (rano/wieczór) + miejsce w sekwencji.\n"
        "  Od najlżejszej do najgęstszej. SPF ZAWSZE ostatni rano.\n"
        "TYP CERY: każda rekomendacja = dla jakiego typu cery.\n"
        "BEZPIECZEŃSTWO: retinol + ciąża = PRZECIWWSKAZANY (alternatywa: bakuchiol).\n"
        "  Faza adaptacji retinolu: 3–6 tyg. SPF obowiązkowy przy retinolu/wit. C/kwasach.\n"
        "BLACKLISTA: 'cudowne właściwości', 'must-have', 'kultowy produkt',\n"
        "  'twoja skóra pokocha', 'magiczny składnik', 'natychmiast odmładza'."
    ),
    "lifestyle": (
        "KONKRETY > OGÓLNIKI: każde twierdzenie o trendzie = min. 1 nazwa własna.\n"
        "  ❌ 'Ten trend podbija wybiegi' → ✅ 'Baleriny na koturnach: Miu Miu, Alaïa, Simone Rocha.\n"
        "     Po trzech sezonach platform wybiegi skręciły w stronę lekkości.'\n"
        "  Daty: sezon + rok (jesień–zima 2025–2026).\n"
        "KONTEKST KULTUROWY: nie opisuj trendu — WYJAŚNIJ go.\n"
        "  Dlaczego teraz? Skąd pochodzi? Co komunikuje?\n"
        "  Osadzaj w historii, popkulturze, architekturze.\n"
        "EKSPERCI: cytat z nazwiska + tytułu, wpleciony w narrację (nie Q&A).\n"
        "  ✅ '— mówi Monika Michalik, psychoterapeutka'\n"
        "ZAMYKANIE: krótka, sucha pointa. Understatement > patos.\n"
        "PARENTEZY: wtrącenia oddzielone myślnikami dozwolone i pożądane.\n"
        "  ✅ 'Jego nagranie — w pięć dni 5 mln wyświetleń — uruchomiło lawinę.'\n"
        "BLACKLISTA: 'must-have', 'game changer', 'it-piece', 'kultowy',\n"
        "  'przepiękny', 'niesamowity', 'niepowtarzalny', 'perfekcyjny'."
    ),
    "inne": (
        "KONKRET > OGÓLNIK: każde twierdzenie = min. 1 nazwa własna, liczba lub źródło.\n"
        "  ❌ 'Ta potrawa jest popularna w wielu krajach.'\n"
        "  ✅ 'Ramen zyskał popularność w Europie po 2015 r. — w samym Paryżu\n"
        "     działa ponad 80 specjalizowanych lokali.'\n"
        "KONTEKST > OPIS: nie opisuj — WYJAŚNIAJ. Dlaczego? Skąd? Co z tego wynika?\n"
        "  ❌ 'Ogród japoński jest piękny' → ✅ 'Ogród japoński opiera się na asymetrii i pustce\n"
        "     — kamienie i mech zastępują kwiaty, bo celem jest kontemplacja.'\n"
        "POINTA: każdy akapit kończy się krótką, suchą pointą zamykającą myśl.\n"
        "BLACKLISTA: 'niesamowity', 'niezwykły', 'wyjątkowy', 'rewolucyjny',\n"
        "  'nie uwierzysz', 'musisz to zobaczyć', 'zmieni twoje życie', 'absolutny hit'."
    ),
}



# ════════════════════════════════════════════════════════════
# SYSTEM PROMPT (v2.1 — ~900 słów)
# ════════════════════════════════════════════════════════════

def build_system_prompt(pre_batch, batch_type):
    pre_batch = pre_batch or {}
    parts = []

    detected_category = pre_batch.get("detected_category", "")

    # voice_preset z UI nadpisuje auto-detekcję
    # Nowy dropdown wysyła bezpośrednio nazwę kategorii (prawo, medycyna, ...)
    # Legacy presety zachowane dla kompatybilności wstecznej
    _voice_preset = pre_batch.get("voice_preset", "auto") or "auto"
    _voice_map = {
        # Direct category names (nowy dropdown)
        "prawo": "prawo",
        "medycyna": "medycyna",
        "finanse": "finanse",
        "technologia": "technologia",
        "budownictwo": "budownictwo",
        "uroda": "uroda",
        "lifestyle": "lifestyle",
        "inne": "inne",
        # Legacy presets (stary dropdown — backward compat)
        "Glossy": "uroda",
        "Prawo rodzinne": "prawo",
        "Prawo karne": "prawo",
        "Lifestyle": "lifestyle",
    }
    if _voice_preset != "auto" and _voice_preset in _voice_map:
        detected_category = _voice_map[_voice_preset]

    is_ymyl = detected_category in ("prawo", "medycyna", "finanse")

    # ═══ 1. ROLA ═══
    persona = _PERSONAS.get(detected_category, _PERSONAS["inne"])
    parts.append(f"""<rola>
{persona}
Ton: pewny, konkretny, rzeczowy. 3. osoba. ZAKAZ 2. osoby (ty/Twój).
Tłumacz temat czytelnikowi — nie pisz jak encyklopedia.
</rola>""")

    # ═══ 2. ZASADY PISANIA ═══
    parts.append(f"""<zasady>
Każde zdanie = nowa informacja. Fakt podany raz — potem skrót lub pomiń.

DANE > OPINIA: konkretne liczby, widełki, stawki, wymiary.
  ✅ „Malowanie z gładziami: 60–120 zł/m². Deska z montażem: 150–250 zł/m²."
  Gdy SERP podaje cenę → PRZEPISZ widełki. 3+ pozycji z cenami → tabela HTML (<table>).

STYL: fakt + co to znaczy dla czytelnika (portfel, kalendarz, zdrowie).
  ✅ „Najczęściej grzywna i zakaz na 3 lata — recydywa oznacza więzienie bez zawieszenia."

RYTM: mieszaj długość zdań. Czasem 5 słów. Czasem 25. Trzy zbliżone pod rząd = monotonia.

ZDANIA: max 2 przecinki. Zdanie > 22 słów → rozbij. Jedno zdanie = jedna myśl.
  Cel czytelności: FOG-PL 8–9 (liceum). Wyrazy trudne = 4+ sylab — ograniczaj.

PODMIOT KONKRETNY: inwestor, lekarz, sąd, ekipa — zamiast „można", „należy", „warto".
  ✅ „Wierzyciel składa wniosek"  ✅ „Sąd bierze pod uwagę"

OTWIERANIE SEKCJI: każda H2 od INNEGO zdania. Zacznij od: liczby, pytania, nazwy, sytuacji.
  Frazę kluczową umieszczaj w ŚRODKU zdania — nie jako opener akapitu.

LISTY: 1–2 <ul> w artykule. Większość treści = proza.

JEDNOSTKI: spacja przed jednostką, tysiące ze spacją: ✅ 10 m², 2 500 zł  ❌ 10m², 2500zł

INTERPUNKCJA: przecinek przed: że, który, ponieważ, aby.
  Cofnięty przecinek: ✅ „Zostanę, mimo że..." ❌ „Zostanę mimo, że..."
  Imiesłów (-ąc, -wszy): ten sam podmiot co zdanie główne + przecinek.

FORMAT: h2:/h3: dla nagłówków. Zero markdown (**, __, #). Każdy h2:/h3: w NOWEJ LINII.

NAZWY FIRM: Nurofen → ibuprofen, OLX → portal ogłoszeniowy.
</zasady>""")

    # ═══ 2b. ANTYREPETYCJE ═══
    parts.append("""<antyrepetycje>
ZASADA PIERWSZEGO UŻYCIA: konkretna wartość (kwota, przepis, data) pełną formą TYLKO RAZ.
  Potem: skrót, zaimek lub pomiń. Trzecie powtórzenie = za dużo → przepisz sekcję.

PRZEPISY: max 2× ten sam artykuł w całym tekście (1× definicja + 1× sankcja/wyjątek).

Każda sekcja H2 = nowa informacja. Pytaj się: „Czego czytelnik dowie się z TEJ sekcji,
  czego nie wiedział po poprzedniej?" Jeśli odpowiedź się pokrywa — to powtórzenie, nie sekcja.
</antyrepetycje>""")

    # ═══ 2c. SPÓJNOŚĆ STRUKTURY ═══
    parts.append("""<spojnosc>
ZDANIE-MOST: sekcja 2+ zaczyna się od krótkiego (max 15 słów) nawiązania do poprzedniej.
  ✅ „Skoro warunki spełnione — czas na dokumenty."  ✅ „Koszty zależą od trybu postępowania."

KIERUNEK: ogół → szczegół → praktyka → koszty. Każdy H2 przesuwa czytelnika naprzód.

ZAMKNIĘCIE SEKCJI: ostatnie zdanie = fakt lub liczba. Morał, podsumowanie = usuń.
  ✅ „Czas oczekiwania: 14–30 dni roboczych."  ❌ „Dlatego tak ważne jest, aby..."
</spojnosc>""")

        # ═══ 3. ENTITY SEO ═══
    parts.append("""<encje>
Encja główna = podmiot zdania, nie dopełnienie. Stawiaj ją na początku.
  ✅ „Jazda po alkoholu skutkuje..."  ❌ „Ważnym aspektem jest jazda po alkoholu"

POZYCJA: encja główna w 1. zdaniu artykułu (podmiot). W co 3.–4. nagłówku H2.
  W każdej sekcji H2 — min. 1× encja główna, rotuj formę fleksyjną.

KOLOKACJA: powiązane encje w TYM SAMYM akapicie — nie rozrzucone po tekście.
  ✅ „Art. 178a KK penalizuje jazdę zakazem prowadzenia od 3 lat i świadczeniem od 5 000 zł."
  ❌ Lista tagów: „art. 178a KK, zakaz prowadzenia, świadczenie pieniężne"

INFORMATION GAIN: w każdej sekcji H2 min. 1 element, którego NIE MA w danych z konkurencji.
CZYSTOŚĆ: każda sekcja H2 = JEDEN podtemat, wyczerpany do końca.
</encje>""")

    # ═══ 4. JĘZYK: NATURALNOŚĆ + KOLOKACJE + ORTOGRAFIA ═══
    parts.append("""<jezyk>
NATURALNY POLSKI — pisz jak redaktor, nie jak tłumacz z angielskiego.
  Podmiot + orzeczenie + dopełnienie. Zdanie od podmiotu, nie od okolicznika.
  ✅ „Sąd orzeka zakaz prowadzenia."  ❌ „W odniesieniu do orzekania — sąd może..."
  Puste startery: „warto zauważyć", „należy podkreślić", „kluczowe jest",
    „istotne jest", „w tym kontekście" → USUŃ i zacznij od faktu.

KOLOKACJE POLSKIE (błąd = marker AI):
  ✅ podjąć decyzję          ❌ zrobić decyzję
  ✅ mocna kawa              ❌ silna kawa
  ✅ ponieść konsekwencje    ❌ mieć konsekwencje
  ✅ odnieść sukces          ❌ osiągnąć sukces (kalk z EN)
  ✅ prowadzić działalność   ❌ robić działalność
  ✅ zawrzeć umowę           ❌ zrobić/podpisać umowę (podpisać = potocznie OK)
  ✅ wyciągnąć wnioski       ❌ zrobić wnioski
  ✅ budzić wątpliwości      ❌ rodzić wątpliwości (rodzić = przestarzałe, ale akceptowane)
  ✅ spełnić warunki         ❌ wypełnić warunki (wypełnić formularz ≠ warunki)
  ✅ odgrywać rolę           ❌ grać rolę (grać = teatr)
  ✅ nabrać przekonania      ❌ zyskać przekonanie
  ✅ zasięgnąć opinii        ❌ wziąć opinię
  ✅ wyrządzić szkodę        ❌ zrobić szkodę
  ✅ wywrzeć wpływ           ❌ zrobić wpływ
  ✅ postawić diagnozę       ❌ zrobić diagnozę
  ✅ złożyć wniosek          ❌ zrobić wniosek
  ✅ doznać obrażeń          ❌ otrzymać obrażenia
  ✅ pełnić funkcję          ❌ robić funkcję
  ✅ brać pod uwagę          ❌ brać na uwagę
  ✅ w dalszym ciągu         ❌ w dalszym stopniu

PUSTE PODMIOTNIKI: „ta sytuacja / ten problem / ten aspekt" → nazwij KTO lub CO.

PRO-DROP: polszczyzna nie potrzebuje zaimków osobowych. ✅ „Idę" ❌ „Ja idę".
  Strona czynna > bierna: ✅ „Uchwalono nowe zasady" ❌ „Zostały wprowadzone zmiany".
  Czasowniki > nominalizacje: ✅ „wdrożyć" ❌ „dokonanie realizacji procesu wdrożenia".

ORTOGRAFIA 2026 (reforma RJP weszła w życie):
  • nie + przymiotnik/przysłówek ŁĄCZNIE gdy orzeka cechę: „niedrogi", „nielepszy", „niedaleko".
    ROZDZIELNIE tylko przy przeciwstawieniu z „lecz/ale": „nie drogi, lecz tani".
  • Zapis „w ogóle" (nie „wogóle"). „Z powrotem" (nie „spowrotem").
  • „-by" z osobowymi formami cz. ŁĄCZNIE: „zrobiłby", „poszłaby".
    Z innymi wyrazami ROZDZIELNIE: „kto by pomyślał", „jakby nie patrzeć".
  • Partykuła „by" po „że", „gdy", „chociaż" — ŁĄCZNIE: „żeby", „gdyby", „choćby".
  • Wielka litera: nazwy świąt (Boże Narodzenie), nazwy dokumentów urzędowych
    (Kodeks karny — ale: kodeks karny gdy opisowo).
</jezyk>""")

    # ═══ 5. ŹRÓDŁA ═══
    if is_ymyl:
        parts.append("""<zrodla>
YMYL — zero tolerancji dla zmyśleń.
Wiedza WYŁĄCZNIE z: stron SERP (podane), przepisów (podane), Wikipedia (podane).
Nie wymyślaj liczb, dat, sygnatur, nazw badań. Nie znasz → pomiń.
</zrodla>""")
    else:
        parts.append("""<zrodla>
Wiedza z: stron SERP, Wikipedia, danych liczbowych (podane).
Nie wymyślaj liczb, dat, nazw badań. Brak danych → opisz ogólnie.
Gdy SERP podaje cenę/stawkę → PRZEPISZ widełki. Nie streszczaj liczb słowami.
</zrodla>""")

    # ═══ 5b. STYL KATEGORII ═══
    cat_style = _CATEGORY_STYLE.get(detected_category, "")
    if cat_style:
        parts.append(f"<styl_kategorii>\n{cat_style}\n</styl_kategorii>")

    # ═══ 6. PRZYKŁAD (per-kategoria) ═══
    _EXAMPLES = {
        "prawo": (
            'TAK: "Granica jest prosta: do 0,5 promila to wykroczenie, powyżej — przestępstwo.\n'
            'Typowy kierowca złapany pierwszy raz z wynikiem tuż ponad próg dostanie\n'
            'grzywnę i zakaz na 3 lata. Brak oświadczenia w terminie 6 mies.\n'
            '= przyjęcie spadku z dobrodziejstwem inwentarza (art. 1015 § 2 k.c.)."\n\n'
            'NIE: "Sytuacja prawna kierowcy ulega zmianie w zależności od okoliczności.\n'
            'Ten aspekt jest szczególnie istotny w kontekście aktualnych regulacji."\n'
            '↑ dwa zdania, ZERO konkretów — brak artykułu, brak kary, brak scenariusza. Usuń.'
        ),
        "medycyna": (
            'TAK: "Ibuprofen 400 mg co 6–8 h łagodzi ból w ciągu 30–60 min\n'
            '— blokuje cyklooksygenazę, hamując syntezę prostaglandyn.\n'
            'Powyżej 3 dni gorączki u dziecka — wizyta u pediatry jest konieczna,\n'
            'nie «warto się skonsultować»."\n\n'
            'NIE: "Lek skutecznie pomaga na dolegliwości. Ten problem jest powszechny."\n'
            '↑ brak dawki, mechanizmu, nazwy substancji. Usuń.'
        ),
        "finanse": (
            'TAK: "Zdolność kredytowa rodziny z dochodem 15 000 zł netto:\n'
            'VeloBank — ok. 1,1 mln zł, Millennium — ok. 950 000 zł.\n'
            'Karta kredytowa z limitem 10 000 zł obniża zdolność nawet przy zerowym saldzie\n'
            '— bank liczy potencjalne zadłużenie. Zmiana z umowy zlecenia na o pracę\n'
            'podnosi zdolność o 15–20 % — nie przez wyższe zarobki, lecz inną wycenę stabilności."\n\n'
            'NIE: "Warto rozważyć skorzystanie z atrakcyjnej oferty kredytowej."\n'
            '↑ ZERO: brak banku, brak kwoty, brak oprocentowania. Usuń.'
        ),
        "technologia": (
            'TAK: "ASRock B860M (ok. 600 zł) — DDR5, M.2 PCIe 5.0, Wi-Fi 6E.\n'
            'Wystarczy do wydajnego komputera bez podkręcania.\n'
            'Premium: ASUS ROG Maximus Z890 (ok. 3 000 zł) — trzy M.2 PCIe 5.0,\n'
            'Thunderbolt 4, Wi-Fi 7. Różnica pięciokrotna w cenie — opłacalna\n'
            'przy topowych Core Ultra 9, zbędna przy i5."\n\n'
            'NIE: "Ta płyta główna oferuje imponujące parametry w przystępnej cenie."\n'
            '↑ ZERO: brak modelu, brak ceny, brak parametru. Usuń.'
        ),
        "budownictwo": (
            'TAK: "Ocieplenie ścian — norma WT: U ≤ 0,20 W/(m²·K).\n'
            'Styropian grafitowy (λ = 0,032): 14 cm. Biały (λ = 0,038): 18–20 cm.\n'
            'Koszt kompletny: materiał 50 zł/m² + robocizna 110 zł/m² = 160 zł/m² bez tynku.\n'
            'Tynk: +40–60 zł/m². Klejenie przy temp. 5–25°C, dni suche."\n\n'
            'NIE: "Wykończenie domu zaczyna się od sprawdzenia stanu deweloperskiego.\n'
            'Ta sytuacja zmienia budżet."\n'
            '↑ ZERO liczb, brak λ, brak cen materiał/robocizna. Usuń.'
        ),
        "uroda": (
            'TAK: "Niacynamid (INCI: Niacinamide, witamina B3) reguluje sebum,\n'
            'hamuje transfer melaniny, wspiera syntezę ceramidów.\n'
            'Skuteczne stężenie: od 2 %, optymalnie 5 %. Powyżej 10 % — ryzyko zaczerwienienia.\n'
            'Łączy się z retinolem (łagodzi efekty uboczne). Ostrożność z AHA/BHA — różnica pH.\n'
            'Cera tłusta/mieszana: serum 5 % rano, pod krem + SPF."\n\n'
            'NIE: "Ten kultowy składnik to absolutny must-have w każdej rutynie."\n'
            '↑ brak INCI, brak stężenia, brak mechanizmu, brak typu cery. Usuń.'
        ),
        "lifestyle": (
            'TAK: "Baleriny na koturnach — Miu Miu, Alaïa, Simone Rocha — po trzech sezonach\n'
            'platform wybiegi skręciły w stronę lekkości. Trend nie jest nowy:\n'
            'Ferragamo eksperymentował z niskim koturnem już w latach 40.\n'
            'Dziś powrót wiąże się z estetyką quiet luxury — mniej platformy, więcej proporcji."\n\n'
            'NIE: "Ten niesamowity trend podbija wybiegi na całym świecie."\n'
            '↑ brak projektanta, brak kolekcji, brak kontekstu kulturowego. Usuń.'
        ),
        "inne": (
            'TAK: "Zakwas na chleb żytni dojrzewa 5–7 dni: mąka razowa + woda 1:1,\n'
            'dokarmianie co 24 h w 24–26°C. Gotowy zakwas: pH 3,5–4,0.\n'
            'Proporcja do wypieku: 20–30 % masy mąki. Przy 500 g mąki = 100–150 g zakwasu."\n\n'
            'NIE: "Pieczenie chleba to niesamowita przygoda kulinarna.\n'
            'Ten proces wymaga cierpliwości."\n'
            '↑ ZERO danych — brak proporcji, temperatury, czasu. Usuń.'
        ),
    }
    _default_example = (
        'TAK: Zdanie z konkretną liczbą, nazwą własną, datą lub źródłem.\n'
        'NIE: Zdanie ogólnikowe — "ta sytuacja", "ten problem", "niesamowity" = do usunięcia.'
    )
    example_text = _EXAMPLES.get(detected_category, _default_example)
    parts.append(f"<przyklad>\n{example_text}\n</przyklad>")

    return "\n\n".join(parts)


# ════════════════════════════════════════════════════════════
# SCHEMA GUARD
# ════════════════════════════════════════════════════════════

_CRITICAL_FIELDS = ["keywords", "main_keyword", "batch_number"]
_IMPORTANT_FIELDS = [
    "gpt_instructions_v39", "enhanced", "h2_remaining",
    "article_memory", "keyword_limits", "coverage",
]

def _schema_guard(pre_batch):
    missing_critical = [f for f in _CRITICAL_FIELDS if f not in pre_batch or pre_batch[f] is None]
    missing_important = [f for f in _IMPORTANT_FIELDS if f not in pre_batch or pre_batch[f] is None]
    if missing_critical:
        _pb_logger.warning(f"⚠️ SCHEMA GUARD: Missing CRITICAL fields: {missing_critical}.")
    if missing_important:
        _pb_logger.info(f"ℹ️ Schema guard: Missing optional: {missing_important}")
    enhanced = pre_batch.get("enhanced") or {}
    if enhanced:
        expected = ["smart_instructions_formatted", "causal_context", "information_gain", "relations_to_establish"]
        missing_enh = [f for f in expected if not enhanced.get(f)]
        if missing_enh:
            _pb_logger.info(f"ℹ️ Enhanced missing: {missing_enh}")


# ════════════════════════════════════════════════════════════
# USER PROMPT (v2.1 — 10 formatterów)
# ════════════════════════════════════════════════════════════

def build_user_prompt(pre_batch, h2, batch_type, article_memory=None):
    pre_batch = pre_batch or {}
    sections = []

    _schema_guard(pre_batch)

    formatters = [
        lambda: _fmt_batch_header(pre_batch, h2, batch_type),
        lambda: _fmt_keywords(pre_batch),
        lambda: _fmt_legal_medical(pre_batch),
        lambda: _fmt_entity_context_v2(pre_batch),
        lambda: _fmt_natural_polish(pre_batch),
        lambda: _fmt_continuation(pre_batch),
        lambda: _fmt_article_memory(article_memory),
        lambda: _fmt_serp_enrichment_v2(pre_batch),
        lambda: _fmt_h2_remaining(pre_batch),
        lambda: _fmt_intro_guidance_v2(pre_batch, batch_type),
        lambda: _fmt_output_format(h2, batch_type),
    ]

    for fmt in formatters:
        try:
            result = fmt()
            if result:
                sections.append(result)
        except Exception as exc:
            _pb_logger.warning(f"Formatter failed: {exc}")

    return "\n\n".join(sections)


# ════════════════════════════════════════════════════════════
# SHARED FORMATTERS (used by article + category prompts)
# ════════════════════════════════════════════════════════════

def _fmt_batch_header(pre_batch, h2, batch_type):
    batch_number = pre_batch.get("batch_number", 1)
    total_batches = pre_batch.get("total_planned_batches", 1)
    batch_length = pre_batch.get("batch_length") or {}

    # INTRO: fixed length, no section header
    if batch_type in ("INTRO", "intro"):
        return f"""═══ BATCH {batch_number}/{total_batches}: INTRO ═══
Długość: 120-200 słów"""

    min_w = batch_length.get("min_words", 350)
    max_w = batch_length.get("max_words", 500)

    section_length = pre_batch.get("section_length_guidance") or {}
    length_hint = ""
    if section_length:
        suggested = section_length.get("suggested_words") or section_length.get("target_words")
        if suggested:
            length_hint = f"\nSugerowana długość tej sekcji: ~{suggested} słów."

    return f"""═══ BATCH {batch_number}/{total_batches}: {batch_type} ═══
Sekcja H2: {h2}
Długość: {min_w}-{max_w} słów{length_hint}
Zaczynaj DOKŁADNIE od: h2: {h2}"""


def _parse_target_max(target_total_str):
    if not target_total_str:
        return 0
    if isinstance(target_total_str, (int, float)):
        return int(target_total_str)
    try:
        parts = str(target_total_str).replace("x", "").split("-")
        if len(parts) >= 2:
            return int(parts[-1].strip())
        return int(parts[0].strip())
    except (ValueError, IndexError):
        return 0


def _get_kw_variants(name, pre_batch):
    """v67: Get fleksyjne + peryfrazy for a keyword from search_variants.
    
    Returns (fleksyjne_list, peryfrazy_list) — both may be empty.
    Checks: search_variants.secondary[name], search_variants.fleksyjne (for main kw),
    and entity_variants as fallback.
    """
    sv = pre_batch.get("_search_variants") or {}
    secondary = sv.get("secondary", {})
    
    # 1. Check secondary dict (per-keyword variants)
    name_lower = name.lower().strip()
    for key, variants in secondary.items():
        if key.lower().strip() == name_lower:
            # secondary variants are a mixed list — split into fleksyjne/peryfrazy
            # heuristic: short variants (±3 words diff) = fleksyjne, longer = peryfrazy
            base_words = len(name.split())
            fleks = [v for v in variants if abs(len(v.split()) - base_words) <= 1]
            peri = [v for v in variants if abs(len(v.split()) - base_words) > 1]
            return fleks[:3], peri[:3]
    
    # 2. For main keyword — use top-level fleksyjne/peryfrazy
    _raw_main = pre_batch.get("main_keyword") or {}
    main_kw = _raw_main.get("keyword", "") if isinstance(_raw_main, dict) else str(_raw_main)
    if main_kw and name_lower == main_kw.lower().strip():
        fleks = sv.get("fleksyjne", [])[:3]
        peri = sv.get("peryfrazy", [])[:3]
        return fleks, peri
    
    # 3. Fallback to entity_variants
    entity_variants = pre_batch.get("_entity_variants") or secondary
    variants = _find_variants(name, entity_variants)
    if variants:
        return variants[:2], []
    
    return [], []


def _fmt_keywords(pre_batch):
    keywords_info = pre_batch.get("keywords") or {}
    keyword_limits = pre_batch.get("keyword_limits") or {}
    soft_caps = pre_batch.get("soft_cap_recommendations") or {}

    _kw_global_remaining = pre_batch.get("_kw_global_remaining", None)
    _main_kw_budget_exhausted = (_kw_global_remaining is not None and _kw_global_remaining == 0)
    _raw_main_kw = pre_batch.get("main_keyword") or {}
    main_kw = _raw_main_kw.get("keyword", "") if isinstance(_raw_main_kw, dict) else str(_raw_main_kw)

    # ── MUST USE ──
    must_raw = keywords_info.get("basic_must_use", [])
    must_lines = []
    _budget_exhausted_kws = []
    for kw in must_raw:
        if isinstance(kw, dict):
            name = kw.get("keyword", "")
            if _main_kw_budget_exhausted and name and main_kw and name.lower() == main_kw.lower():
                _budget_exhausted_kws.append(name)
                continue
            actual = kw.get("actual", kw.get("actual_uses", kw.get("current_count", 0)))
            target_total = kw.get("target_total", "")
            target_max = _parse_target_max(target_total) or kw.get("target_max", 0)
            hard_max = kw.get("hard_max_this_batch", "")
            remaining = kw.get("remaining", kw.get("remaining_max", ""))
            if not remaining and target_max and isinstance(actual, (int, float)):
                remaining = max(0, target_max - int(actual))
            line = f'  • "{name}"'
            if hard_max:
                line += f" (max {hard_max}×)"
            elif remaining and int(remaining) <= 2:
                line += f" (jeszcze {remaining}×)"
            # v67: Add variant hints — fleksyjne + peryfrazy
            fleks, peri = _get_kw_variants(name, pre_batch)
            if fleks:
                line += f'\n    odmiany: {", ".join(fleks)}'
            if peri:
                line += f'\n    peryfrazy: {", ".join(peri)}'
            must_lines.append(line)
        else:
            line = f'  • "{kw}"'
            fleks, peri = _get_kw_variants(str(kw), pre_batch)
            if fleks:
                line += f'\n    odmiany: {", ".join(fleks)}'
            if peri:
                line += f'\n    peryfrazy: {", ".join(peri)}'
            must_lines.append(line)

    # ── EXTENDED ──
    ext_raw = keywords_info.get("extended_this_batch", [])
    ext_lines = []
    for kw in ext_raw:
        if isinstance(kw, dict):
            name = kw.get("keyword", "")
            line = f'  • "{name}"'
            # v67: Variant hints for extended too
            fleks, peri = _get_kw_variants(name, pre_batch)
            if peri:
                line += f' (lub: {", ".join(peri[:2])})'
            elif fleks:
                line += f' (lub: {", ".join(fleks[:2])})'
            ext_lines.append(line)
        else:
            line = f'  • "{kw}"'
            fleks, peri = _get_kw_variants(str(kw), pre_batch)
            if peri:
                line += f' (lub: {", ".join(peri[:2])})'
            elif fleks:
                line += f' (lub: {", ".join(fleks[:2])})'
            ext_lines.append(line)

    # ── STOP ──
    stop_raw = keyword_limits.get("stop_keywords") or []
    entity_variants = pre_batch.get("_entity_variants") or \
        (pre_batch.get("_search_variants") or {}).get("secondary", {})
    stop_lines = []
    for s in stop_raw:
        if isinstance(s, dict):
            name = s.get("keyword", "")
            current = s.get("current_count", s.get("current", s.get("actual", "?")))
            max_c = s.get("max_count", s.get("max", s.get("target_max", "?")))
            line = f'  • "{name}" (już {current}×, limit {max_c}) STOP!'
            # v2.3: Show variant replacements
            variants = _find_variants(name, entity_variants)
            if variants:
                line += f'\n    → zamiast użyj: {", ".join(variants[:4])}'
            stop_lines.append(line)
        else:
            line = f'  • "{s}"'
            variants = _find_variants(str(s), entity_variants)
            if variants:
                line += f'\n    → zamiast użyj: {", ".join(variants[:4])}'
            stop_lines.append(line)
    for exhausted_kw in _budget_exhausted_kws:
        line = f'  • "{exhausted_kw}" (limit globalny osiągnięty — NIE UŻYWAJ!)'
        variants = _find_variants(exhausted_kw, entity_variants)
        if variants:
            line += f'\n    → zamiast użyj: {", ".join(variants[:4])}'
        stop_lines.append(line)

    # ── CAUTION ──
    caution_raw = keyword_limits.get("caution_keywords") or []
    caution_names = []
    caution_variant_hints = []
    for c in caution_raw:
        if isinstance(c, dict):
            name = c.get("keyword", "")
            caution_names.append(name)
        else:
            name = str(c)
            caution_names.append(name)
        if name:
            variants = _find_variants(name, entity_variants)
            if variants:
                caution_variant_hints.append(f'  "{name}" → {", ".join(variants[:3])}')
    caution_names = [n for n in caution_names if n]

    # ── SOFT CAPS ──
    soft_notes = []
    if soft_caps:
        for kw_name, info in soft_caps.items():
            if isinstance(info, dict):
                action = info.get("action", "")
                if action and action != "OK":
                    soft_notes.append(f'  ℹ️ "{kw_name}": {action}')

    _kw_force_ban = pre_batch.get("_kw_force_ban", False)
    if _kw_force_ban and main_kw:
        must_lines = [l for l in must_lines if main_kw.lower() not in l.lower()]

    # ── BUILD ──
    parts = ["═══ FRAZY KLUCZOWE ═══"]
    parts.append("⚡ ROTACJA FORM: Google liczy odmiany jako to samo slowo (lematyzacja).\n"
                 "  'wykroczenie' + 'wykroczenia' + 'wykroczeniem' = 3 uzycia jednego lematu.\n"
                 "  Dlatego: NIE powtarzaj exact match — rotuj przez odmiany i peryfrazy.\n"
                 "  Jesli fraza ma podane odmiany/peryfrazy — UZYWAJ ICH zamiast powtarzac te sama forme.")
    # v67: Anti-paragraph-opener rule — prevents MK stuffing pattern
    if main_kw:
        parts.append(f'🚫 ZAKAZ ANAFORY: NIGDY nie zaczynaj akapitu od frazy kluczowej "{main_kw}".\n'
                     f'  ❌ "{main_kw} to..." / "{main_kw} bywa..." / "{main_kw} lekami..."\n'
                     f'  ✅ Zacznij od kontekstu, konsekwencji, pytania lub zaimka.\n'
                     f'  Jesli musisz uzyc frazy — wstaw ja w SRODEK zdania, nie na poczatku.')

    if _kw_force_ban and main_kw:
        parts.append(f'⛔ STOP: Fraza "{main_kw}" jest PRZEKROCZONA — nie używaj w tym batchu.\n')

    if must_lines:
        parts.append("TEMATY OBOWIĄZKOWE (poruszyj w treści):")
        parts.extend(must_lines)
    if ext_lines:
        parts.append("\nTEMATY DODATKOWE (wpleć jeśli pasują):")
        parts.extend(ext_lines)
    if stop_lines:
        parts.append("\n🛑 STOP — nie używaj (przekroczone):")
        parts.extend(stop_lines)
    if caution_names:
        parts.append(f"\n⚠️ OSTROŻNIE (max 1× każda): {', '.join(caution_names)}")
        if caution_variant_hints:
            parts.extend(caution_variant_hints)
    if soft_notes:
        parts.append("")
        parts.extend(soft_notes)

    return "\n".join(parts) if len(parts) > 1 else ""


def _fmt_continuation(pre_batch):
    continuation = pre_batch.get("continuation_v39") or {}
    enhanced = pre_batch.get("enhanced") or {}
    cont_ctx = enhanced.get("continuation_context") or {}

    last_h2 = cont_ctx.get("last_h2") or continuation.get("last_h2", "")
    last_ending = cont_ctx.get("last_paragraph_ending") or continuation.get("last_paragraph_ending", "")
    last_topic = cont_ctx.get("last_topic") or continuation.get("last_topic", "")
    transition_hint = continuation.get("transition_hint", "")

    if not last_h2 and not last_ending:
        return ""

    parts = ["═══ KONTYNUACJA ═══", "Poprzedni batch zakończył się na:"]
    if last_h2:
        parts.append(f'  Ostatni H2: "{last_h2}"')
    if last_ending:
        ending_preview = last_ending[:150] + ("..." if len(last_ending) > 150 else "")
        parts.append(f'  Ostatnie zdanie: "{ending_preview}"')
    if last_topic:
        parts.append(f'  Temat: {last_topic}')
    parts.append("\nZacznij PŁYNNIE: nawiąż do poprzedniego wątku, ale nie powtarzaj zakończenia.")
    if transition_hint:
        parts.append(f'Sugerowane przejście: {transition_hint}')
    return "\n".join(parts)


def _fmt_article_memory(article_memory):
    if not article_memory:
        return ""

    parts = ["═══ PAMIĘĆ ARTYKUŁU ═══"]

    if isinstance(article_memory, dict):
        topics = article_memory.get("topics_covered") or article_memory.get("covered_topics") or []
        if topics:
            parts.append("Sekcje już napisane:")
            for t in topics[:10]:
                if isinstance(t, str):
                    parts.append(f'  ✓ {t}')
                elif isinstance(t, dict):
                    parts.append(f'  ✓ {t.get("topic", t.get("h2", ""))}')

        # ── KONKRETNE WARTOŚCI: zakaz powtarzania ──
        concrete_facts = article_memory.get("concrete_facts_used") or []
        if concrete_facts:
            parts.append(
                "\n🚫 WARTOŚCI JUŻ UŻYTE — nie pisz ich ponownie pełną formą "
                "(maks. skrót jeśli absolutnie konieczne, np. \"ww. kwota\", \"wspomniany przepis\"):"
            )
            for v in concrete_facts[:30]:
                parts.append(f'  ❌ {v}')

        facts = article_memory.get("key_facts_used") or article_memory.get("facts", [])
        key_points = article_memory.get("key_points") or []
        avoid_rep = article_memory.get("avoid_repetition") or []

        all_facts = list(facts) + list(key_points)
        if all_facts:
            parts.append("\nFakty już podane (NIE POWTARZAJ):")
            for f in all_facts[:12]:
                parts.append(f'  • {f}' if isinstance(f, str) else f'  • {json.dumps(f, ensure_ascii=False)[:100]}')

        if avoid_rep:
            parts.append("\n⛔ UŻYTE ZDANIA — NIE POWTARZAJ DOSŁOWNIE:")
            for r in avoid_rep[:8]:
                parts.append(f'  ❌ "{r}"')

        # ── PRE-ANALIZA (technika #6 z badań — najskuteczniejsza) ──
        # Zmuszamy model do wylistowania zakazów ZANIM zacznie pisać.
        # Badania: modele które "widzą" co jest zakazane przed generowaniem
        # produkują ~90% mniej duplikacji niż te z samymi instrukcjami.
        if topics or concrete_facts or all_facts:
            batch_n = len(topics) + 1
            parts.append(
                f"\n📋 PRZED NAPISANIEM SEKCJI {batch_n} wykonaj w myślach analizę:\n"
                "  1. Jakie konkretne wartości (kwoty, przepisy, daty) już padły? → nie powtarzaj ich pełną formą\n"
                "  2. Jaką myśl kończyła poprzednia sekcja? → zacznij od zdania-mostu, nie od tej samej myśli\n"
                "  3. Co NOWEGO wnosi ta sekcja, czego poprzednie nie omówiły? → to jest Twoja teza\n"
                "Dopiero po tej analizie zacznij pisać."
            )

    elif isinstance(article_memory, str):
        parts.append(_word_trim(article_memory, 1500))

    return "\n".join(parts) if len(parts) > 1 else ""


def _fmt_h2_remaining(pre_batch):
    h2_remaining = pre_batch.get("h2_remaining") or []
    if not h2_remaining:
        return ""
    h2_list = ", ".join(f'"{h}"' for h in h2_remaining[:6])
    return f"═══ PLAN ═══\nPozostałe sekcje H2: {h2_list}\nNie zachodź na ich tematy."


def _fmt_output_format(h2, batch_type):
    if batch_type in ("INTRO", "intro"):
        return """═══ FORMAT ODPOWIEDZI ═══
Pisz TYLKO treść leadu. NIE zaczynaj od "h2:". Lead nie ma nagłówka.
120-200 słów. Frazę główną wpleć w PIERWSZE zdanie.
NIE dodawaj komentarzy, meta-tekstu. TYLKO treść leadu."""

    return f"""═══ FORMAT ODPOWIEDZI ═══
Pisz TYLKO treść tego batcha. Zaczynaj od:

h2: {h2}

Akapity po 3-5 zdań. Opcjonalnie h3: [podsekcja].
Gdy masz 3+ warunków/kroków/wymagań → lista <ul><li> (max 1-2 listy w artykule).
Gdy porównujesz dane liczbowe → tabela <table> (max 1 w artykule).
Każdy akapit powinien zawierać min. 1 konkretny fakt (liczbę, stawkę, wymiar, termin).
Zdania bez informacji ("Ta sytuacja...", "Ten problem...") = DO USUNIĘCIA.
Zdanie z 3+ przecinkami = za złożone → rozbij na dwa zdania.
KAŻDY h3: na OSOBNEJ linii z pustą linią powyżej i poniżej.
ŻADEN nagłówek NIE może być wklejony w środek akapitu.
Zero markdown (**, __, #). Zero tagów HTML (<h2>, <h3>, <b>).
NIE dodawaj komentarzy. TYLKO treść artykułu."""


# ════════════════════════════════════════════════════════════
# NEW v2 FORMATTERS (article only)
# ════════════════════════════════════════════════════════════

def _fmt_entity_context_v2(pre_batch):
    """v2.3: Smart S1 context — per-H2 filtered data from _build_batch_s1_context."""
    parts = []
    s1_ctx = pre_batch.get("_s1_context") or {}

    _raw_main = pre_batch.get("main_keyword") or {}
    main_name = _raw_main.get("keyword", "") if isinstance(_raw_main, dict) else str(_raw_main)
    _entity_seo = (pre_batch.get("s1_data") or {}).get("entity_seo") or \
        pre_batch.get("entity_seo") or {}

    # ── Block 1: Synonyms (from search_variants or fallback to entity_synonyms) ──
    if main_name:
        sv = pre_batch.get("_search_variants") or {}
        peryfrazy = sv.get("peryfrazy", [])
        if peryfrazy:
            parts.append(f"═══ ENCJE ═══\nSynonimy: {', '.join(peryfrazy[:5])}")
        else:
            synonyms = _entity_seo.get("entity_synonyms", [])[:5]
            if synonyms:
                parts.append(f"═══ ENCJE ═══\nSynonimy: {', '.join(str(s) for s in synonyms)}")
            else:
                parts.append("═══ ENCJE ═══")

    # ── Block 2: Lead entity + concepts for THIS section ──
    lead = s1_ctx.get("lead_entity")
    concepts = s1_ctx.get("concepts", [])
    e_gaps = s1_ctx.get("entity_gaps", [])

    concept_parts = []
    if lead and lead.lower() != main_name.lower():
        concept_parts.append(f"🎯 Encja wiodąca sekcji: {lead}")
    all_to_weave = concepts[:]
    for g in e_gaps:
        if g not in all_to_weave:
            all_to_weave.append(f"{g} [luka]")
    if all_to_weave:
        concept_parts.append(f"Wpleć: {', '.join(all_to_weave[:6])}")
    if concept_parts:
        parts.append("\n".join(concept_parts))

    # ── Block 3: EAV facts (filtered per H2) ──
    eav = s1_ctx.get("eav", [])
    if eav:
        eav_lines = ["Fakty (wpleć w zdania, nie listuj):"]
        for e in eav[:5]:
            marker = "🎯" if e.get("is_primary") else "•"
            eav_lines.append(f'  {marker} {e.get("entity","")} → {e.get("attribute","")} → {e.get("value","")}')
        parts.append("\n".join(eav_lines))

    # ── Block 4: SVO relations (filtered per H2 — NEW in article prompt) ──
    svo = s1_ctx.get("svo", [])
    if svo:
        svo_lines = ["Relacje (opisz swoimi słowami):"]
        for t in svo[:3]:
            ctx = f' [{t.get("context","")}]' if t.get("context") else ""
            svo_lines.append(f'  • {t.get("subject","")} → {t.get("verb","")} → {t.get("object","")}{ctx}')
        parts.append("\n".join(svo_lines))

    # ── Block 5: Causal chains (NEW — first time in article prompt) ──
    causal = s1_ctx.get("causal", [])
    if causal:
        causal_lines = ["Łańcuchy przyczynowe (użyj do wyjaśniania DLACZEGO):"]
        for c in causal[:2]:
            if isinstance(c, dict):
                text = c.get("chain", c.get("text", str(c)))
            else:
                text = str(c)
            causal_lines.append(f"  ⛓️ {_word_trim(text, 150)}")
        parts.append("\n".join(causal_lines))

    # ── Block 6: Content gaps for THIS section (NEW) ──
    gaps = s1_ctx.get("gaps", [])
    if gaps:
        parts.append(f"Luki TOP10 (information gain): {', '.join(gaps[:3])}")

    # ── Block 7: Co-occurrence pairs for THIS section ──
    cooc = s1_ctx.get("cooc", [])
    if cooc:
        parts.append(f"Encje razem w akapicie: {' | '.join(cooc[:4])}")

    # ── Block 8: Information gain (from master API, per-batch) ──
    enhanced = pre_batch.get("enhanced") or {}
    info_gain = enhanced.get("information_gain", "")
    if info_gain:
        parts.append(f"Przewaga nad konkurencją: {_word_trim(info_gain, 200)}")

    # ── Block 9: Semantic angle (from master API, per-batch) ──
    plan = pre_batch.get("semantic_batch_plan") or {}
    if plan:
        h2_coverage = plan.get("h2_coverage") or {}
        for h2_name, info in h2_coverage.items():
            if isinstance(info, dict):
                angle = info.get("semantic_angle", "")
                if angle:
                    parts.append(f"Kąt sekcji: {angle}")
                    break

    # ── Fallback: if _s1_context empty, use old static fields ──
    if not s1_ctx:
        must_concepts = pre_batch.get("_must_cover_concepts") or []
        old_eav = pre_batch.get("_eav_triples") or []
        old_gaps = pre_batch.get("_entity_gaps") or []
        if must_concepts:
            names = [c.get("text", c) if isinstance(c, dict) else str(c) for c in must_concepts[:8]]
            parts.append(f"Wpleć: {', '.join(n for n in names if n)}")
        if old_eav:
            eav_lines = ["Fakty (wpleć w zdania):"]
            for e in old_eav[:4]:
                eav_lines.append(f'  • {e.get("entity","")} → {e.get("attribute","")} → {e.get("value","")}')
            parts.append("\n".join(eav_lines))
        if old_gaps:
            gap_names = [g.get("entity", "") for g in old_gaps if g.get("priority") == "high"][:3]
            if gap_names:
                parts.append(f"Luki: {', '.join(gap_names)}")

    return "\n\n".join(parts) if parts else ""


def _fmt_serp_enrichment_v2(pre_batch):
    serp = pre_batch.get("serp_enrichment") or {}
    enhanced = pre_batch.get("enhanced") or {}

    paa = serp.get("paa_for_batch") or enhanced.get("paa_from_serp") or []
    lsi = serp.get("lsi_keywords") or []
    chips = serp.get("refinement_chips") or []

    if not paa and not lsi and not chips:
        return ""

    parts = ["═══ SERP ═══"]
    if chips:
        parts.append(f"Podtematy Google: {', '.join(str(c) for c in chips[:8])}")
    if paa:
        q_strs = []
        for q in paa[:4]:
            q_text = q.get("question", q) if isinstance(q, dict) else q
            if q_text:
                q_strs.append(str(q_text))
        if q_strs:
            parts.append("Pytania PAA (odpowiedz na 1-2):\n  " + "\n  ".join(q_strs))
    if lsi:
        # Deduplicate: skip LSI keywords already in EXTENDED
        _ext_kws = pre_batch.get("keywords", {}).get("extended_this_batch", [])
        _ext_names = {(k.get("keyword", k) if isinstance(k, dict) else str(k)).lower().strip()
                      for k in _ext_kws}
        lsi_names = []
        for l in lsi[:8]:
            name = l.get("keyword", l) if isinstance(l, dict) else l
            if str(name).lower().strip() not in _ext_names:
                lsi_names.append(str(name))
        if lsi_names:
            parts.append(f"LSI: {', '.join(lsi_names)}")

    return "\n".join(parts) if len(parts) > 1 else ""


def _fmt_intro_guidance_v2(pre_batch, batch_type):
    if batch_type not in ("INTRO", "intro"):
        return ""

    main_kw = pre_batch.get("main_keyword") or {}
    kw_name = main_kw.get("keyword", "") if isinstance(main_kw, dict) else str(main_kw)
    serp = pre_batch.get("serp_enrichment") or {}

    parts = ["═══ LEAD (WSTĘP) ═══"]
    parts.append("120-200 słów. NIE zaczynaj od h2:. Lead nie ma nagłówka.")
    if kw_name:
        parts.append(f'Zacznij od sedna: czym jest "{kw_name}" i dlaczego czytelnik powinien czytać dalej.')
    parts.append("Kontekst praktyczny + konkretny fakt liczbowy w PIERWSZYM akapicie.")
    parts.append("NIE zapowiadaj co będzie dalej. NIE pisz 'w tym artykule dowiesz się'.")

    search_intent = serp.get("search_intent", "")
    if search_intent:
        parts.append(f"Intencja wyszukiwania: {search_intent}")

    # ── Priority 1: Featured Snippet ──
    fs = serp.get("featured_snippet", "")
    fs_text = ""
    if fs:
        fs_text = fs if isinstance(fs, str) else (fs.get("text", "") if isinstance(fs, dict) else str(fs))
    if fs_text and len(fs_text) > 20:
        parts.append(f"\n📋 Google Featured Snippet (PRZELICYTUJ tę odpowiedź — daj więcej faktów i konkretów):")
        parts.append(f"  \"{fs_text[:300]}\"")

    # ── Priority 2: AI Overview ──
    aio = serp.get("ai_overview", "")
    aio_text = ""
    if aio:
        aio_text = aio if isinstance(aio, str) else (aio.get("text", "") if isinstance(aio, dict) else str(aio))
    if aio_text and len(aio_text) > 20:
        parts.append(f"\n🤖 Google AI Overview (Twój lead MUSI być bardziej konkretny):")
        parts.append(f"  \"{aio_text[:400]}\"")

    # ── Fallback: when NO snippet AND NO AI overview ──
    if not (fs_text and len(fs_text) > 20) and not (aio_text and len(aio_text) > 20):
        parts.append("\n⚠️ Brak Featured Snippet i AI Overview — zbuduj lead z tych danych:")

        # v2.3: Competitor first paragraphs — strongest fallback signal
        comp_intros = serp.get("competitor_intros", [])
        if comp_intros:
            parts.append("  📖 Pierwsze akapity konkurencji (PRZELICYTUJ — daj więcej konkretów):")
            for ci in comp_intros[:3]:
                _title = ci.get("title", "")[:50]
                _intro = ci.get("intro", "")[:250]
                if _intro:
                    parts.append(f"    [{_title}]: \"{_intro}\"")
            parts.append("  → Twój lead musi być LEPSZY: bardziej konkretny, z liczbami, od razu do sedna.")

        # Competitor titles → what angle works
        comp_titles = serp.get("competitor_titles", [])
        if comp_titles:
            titles_str = ", ".join(
                str(t.get("title", t) if isinstance(t, dict) else t)[:60]
                for t in comp_titles[:5] if t
            )
            if titles_str:
                parts.append(f"  📰 Top wyniki Google: {titles_str}")
                parts.append("  → Twój lead musi odpowiedzieć na pytanie lepiej niż te tytuły.")

        # Competitor snippets → what Google shows
        comp_snippets = serp.get("competitor_snippets", [])
        if comp_snippets:
            snippet_texts = []
            for sn in comp_snippets[:3]:
                txt = sn.get("snippet", sn) if isinstance(sn, dict) else str(sn)
                if txt and len(str(txt)) > 20:
                    snippet_texts.append(str(txt)[:100])
            if snippet_texts:
                parts.append(f"  📝 Meta opisy konkurencji:")
                for st in snippet_texts:
                    parts.append(f"    • {st}")

        # PAA → the first question is often the core user intent
        paa = serp.get("paa_questions", [])
        if paa:
            paa_texts = []
            for q in paa[:3]:
                qt = q.get("question", q) if isinstance(q, dict) else str(q)
                if qt and len(str(qt)) > 5:
                    paa_texts.append(str(qt))
            if paa_texts:
                parts.append(f"  ❓ Ludzie pytają: {' | '.join(paa_texts)}")
                parts.append("  → Lead powinien odpowiedzieć na PIERWSZE pytanie w 1-2 zdaniach.")

        # S1 context — key facts
        s1_ctx = pre_batch.get("_s1_context") or {}
        eav = s1_ctx.get("eav", [])
        if eav:
            facts = []
            for e in eav[:3]:
                if isinstance(e, dict):
                    facts.append(f"{e.get('entity','')}: {e.get('value','')}")
            if facts:
                parts.append(f"  📊 Fakty do wplecenia: {', '.join(facts)}")

    # ── Custom intro guidance (from master API) ──
    guidance = pre_batch.get("intro_guidance", "")
    if guidance:
        if isinstance(guidance, dict):
            hook = guidance.get("hook", "")
            if hook:
                parts.append(f"Hak: {hook}")
        elif isinstance(guidance, str) and len(str(guidance)) > 10:
            parts.append(str(guidance)[:300])

    return "\n".join(parts)


# ════════════════════════════════════════════════════════════
# LEGAL / MEDICAL (used by article v2 — kept in full)
# ════════════════════════════════════════════════════════════

def _fmt_legal_medical(pre_batch):
    legal_ctx = pre_batch.get("legal_context") or {}
    medical_ctx = pre_batch.get("medical_context") or {}
    ymyl_enrich = pre_batch.get("_ymyl_enrichment") or {}
    ymyl_intensity = pre_batch.get("_ymyl_intensity", "full")

    parts = []

    if ymyl_intensity == "light":
        light_note = pre_batch.get("_light_ymyl_note", "")
        if light_note:
            parts.append("═══ ASPEKT REGULACYJNY (peryferyjny) ═══")
            parts.append(f"  {light_note}")
            parts.append("  ⚠️ Wspomnij o regulacjach MAX 1-2 razy w CAŁYM artykule.")
        return "\n".join(parts) if parts else ""

    if legal_ctx and legal_ctx.get("active"):
        parts.append("═══ KONTEKST PRAWNY (YMYL) ═══")
        parts.append("NIE wymyślaj sygnatur, dat orzeczeń ani numerów artykułów.")
        parts.append("Placeholder 'odpowiednich przepisów' → zawsze podaj konkretny art.")
        parts.append("""⚠️ KRYTYCZNE ZASADY DLA TREŚCI PRAWNYCH:
  1. SPRAWDŹ NAZWĘ USTAWY — nie mylij ustaw:
     ❌ „Art. 87 ustawy o ochronie konkurencji i konsumentów" ← TO INNA USTAWA
     ✅ „Art. 87 § 1 Kodeksu wykroczeń"
  2. SPRAWDŹ NUMER ARTYKUŁU — nie zaokrąglaj:
     ❌ „Art. 178 k.k." ← to zaostrzenie karalności, nie samodzielny typ czynu
     ✅ „Art. 178a § 1 k.k." ← prowadzenie w stanie nietrzeźwości
  3. PODAWAJ PEŁNĄ SYGNATURĘ z paragrafem (§):
     ❌ „Art. 178 Kodeksu karnego"
     ✅ „Art. 178a § 1 k.k."
  4. NIE MIESZAJ JEDNOSTEK: promile (‰) = krew, mg/dm³ = wydychane powietrze.
  5. Jeśli NIE masz pewności co do numeru artykułu — POMIŃ go. Lepiej ogólnik niż błąd.
  6. Każdą podstawę prawną podawaj w formacie: „Art. X § Y [skrót ustawy]".""")


        wiki_arts = pre_batch.get("legal_wiki_articles") or []
        if wiki_arts:
            parts.append("\nWIKIPEDIA:")
            for w in wiki_arts[:4]:
                if w.get("found"):
                    parts.append(f"  [{w['article_ref']}] {w['title']}:")
                    parts.append(f"  {w['extract'][:300]}")
                    parts.append(f"  Źródło: {w['url']}")
                    parts.append("")

        legal_enrich = ymyl_enrich.get("legal", {})
        if legal_enrich.get("articles"):
            parts.append("\nPODSTAWA PRAWNA:")
            for art in legal_enrich["articles"][:5]:
                parts.append(f"  • {art}")
        if legal_enrich.get("acts"):
            parts.append(f"  Ustawy: {', '.join(legal_enrich['acts'][:4])}")
        if legal_enrich.get("key_concepts"):
            parts.append(f"  Pojęcia: {', '.join(legal_enrich['key_concepts'][:6])}")

        instruction = legal_ctx.get("legal_instruction", "")
        if instruction:
            parts.append(f'\n{instruction[:600]}')

        judgments = legal_ctx.get("top_judgments") or []
        if judgments:
            parts.append("\nOrzeczenia (dostępne, ale NIE musisz cytować):")
            parts.append("  ⚠️ Użyj MAX 1 orzeczenia i TYLKO gdy bezpośrednio dotyczy tematu sekcji.")
            parts.append("  ⚠️ NIE cytuj wyroku cywilnego (sygn. I C, III RC) w tekście o odpowiedzialności karnej.")
            parts.append("  ⚠️ Lepiej pominąć orzeczenie niż wcisnąć nieadekwatne.")
            for j in judgments[:3]:
                if isinstance(j, dict):
                    sig = j.get("signature", j.get("caseNumber", ""))
                    court = j.get("court", j.get("courtName", ""))
                    date = j.get("date", j.get("judgmentDate", ""))
                    matched = j.get("matched_article", "")
                    line = f'  • {sig}, {court} ({date})'
                    if matched:
                        line += f' [dot. {matched}]'
                    parts.append(line)

        citation_hint = legal_ctx.get("citation_hint", "")
        if citation_hint:
            parts.append(f'\n{citation_hint}')

    if medical_ctx and medical_ctx.get("active"):
        if parts:
            parts.append("")
        parts.append("═══ KONTEKST MEDYCZNY (YMYL) ═══")
        parts.append("MUSISZ:")
        parts.append("  1. Cytować źródła naukowe (podane niżej)")
        parts.append("  2. NIE wymyślać statystyk ani nazw badań")

        med_enrich = ymyl_enrich.get("medical", {})
        if med_enrich.get("specialization"):
            parts.append(f"\n  Specjalizacja: {med_enrich['specialization']}")
        if med_enrich.get("condition"):
            cond = med_enrich["condition"]
            latin = med_enrich.get("condition_latin", "")
            icd = med_enrich.get("icd10", "")
            parts.append(f"  Choroba/stan: {cond}" + (f" ({latin})" if latin else "") + (f" [ICD-10: {icd}]" if icd else ""))
        if med_enrich.get("key_drugs"):
            parts.append(f"  Leki: {', '.join(med_enrich['key_drugs'][:5])}")
        if med_enrich.get("evidence_note"):
            parts.append(f"\n  ⚠️ WYTYCZNE: {med_enrich['evidence_note']}")

        parts.append("")
        parts.append("HIERARCHIA DOWODÓW:")
        parts.append("  1. Meta-analiza > 2. RCT > 3. Kohortowe > 4. Opis przypadku > 5. Opinia")

        instruction = medical_ctx.get("medical_instruction", "")
        if instruction:
            parts.append(f'\n{instruction[:600]}')

        publications = medical_ctx.get("top_publications") or []
        if publications:
            parts.append("\nPublikacje:")
            for p in publications[:5]:
                if isinstance(p, dict):
                    title = p.get("title", "")[:80]
                    authors = p.get("authors", "")[:40]
                    year = p.get("year", "")
                    pmid = p.get("pmid", "")
                    parts.append(f'  • {authors} ({year}): "{title}" PMID:{pmid}')

    return "\n".join(parts) if parts else ""


# ════════════════════════════════════════════════════════════
# CATEGORY-ONLY FORMATTERS
# (used by build_category_user_prompt — NOT by article v2)
# ════════════════════════════════════════════════════════════

def _fmt_smart_instructions(pre_batch):
    enhanced = pre_batch.get("enhanced") or {}
    smart = enhanced.get("smart_instructions_formatted", "")
    if smart:
        return f"═══ INSTRUKCJE DLA TEGO BATCHA ═══\n{smart[:1000]}"
    return ""


def _fmt_semantic_plan(pre_batch, h2):
    plan = pre_batch.get("semantic_batch_plan") or {}
    if not plan:
        return ""
    parts = ["═══ CO PISAĆ W TEJ SEKCJI ═══"]
    h2_coverage = plan.get("h2_coverage") or {}
    for h2_name, info in h2_coverage.items():
        if isinstance(info, dict):
            angle = info.get("semantic_angle", "")
            must = info.get("must_phrases", [])
            if angle:
                parts.append(f'Kąt: {angle}')
            if must:
                parts.append(f'Frazy: {", ".join(f"{p}" for p in must[:5])}')
    direction = plan.get("content_direction") or plan.get("writing_direction", "")
    if direction:
        parts.append(f'Kierunek: {direction}')
    return "\n".join(parts) if len(parts) > 1 else ""


def _fmt_coverage_density(pre_batch):
    coverage = pre_batch.get("coverage") or {}
    density = pre_batch.get("density") or {}
    main_kw = pre_batch.get("main_keyword") or {}
    if not coverage and not density and not main_kw:
        return ""
    parts = ["═══ STATUS POKRYCIA FRAZ ═══"]
    if main_kw:
        kw_name = main_kw.get("keyword", "") if isinstance(main_kw, dict) else str(main_kw)
        synonyms = main_kw.get("synonyms", []) if isinstance(main_kw, dict) else []
        if kw_name:
            parts.append(f'Hasło główne: "{kw_name}"')
        if synonyms:
            parts.append(f'Synonimy: {", ".join(synonyms[:5])}')
    current_cov = coverage.get("current", coverage.get("current_coverage"))
    target_cov = coverage.get("target", coverage.get("target_coverage"))
    if current_cov is not None and target_cov is not None:
        parts.append(f'Pokrycie: {current_cov}% z {target_cov}%')
    missing = coverage.get("missing_phrases") or coverage.get("uncovered") or []
    if missing:
        parts.append("⚠️ BRAKUJĄCE:")
        for m in missing[:8]:
            name = m.get("keyword", m) if isinstance(m, dict) else m
            parts.append(f'  → "{name}"')
    return "\n".join(parts) if len(parts) > 1 else ""


def _fmt_style(pre_batch):
    style = pre_batch.get("style_instructions") or pre_batch.get("style_instructions_v39") or {}
    if not style:
        return ""
    parts = ["═══ STYL (dodatkowy) ═══"]
    if isinstance(style, dict):
        # Skip 'tone' — system prompt already sets tone to avoid conflicts
        forbidden = style.get("forbidden_phrases") or style.get("avoid_phrases") or []
        if forbidden:
            parts.append(f'Unikaj też: {", ".join(f"{f}" for f in forbidden[:8])}')
    elif isinstance(style, str):
        parts.append(_word_trim(style, 500))
    return "\n".join(parts) if len(parts) > 1 else ""


def _fmt_entity_salience(pre_batch):
    """Entity salience — used by category prompt. Full version kept."""
    parts = []

    local_instructions = pre_batch.get("_entity_salience_instructions", "")
    if local_instructions:
        parts.append(local_instructions)

    backend_placement = pre_batch.get("_backend_placement_instruction", "")
    if backend_placement:
        parts.append("═══ ROZMIESZCZENIE ENCJI ═══")
        parts.append("⚠️ Wskazówki techniczne — NIE kopiuj dosłownie.")
        parts.append(backend_placement)

    FLEXION_NOTE = (
        "\n⚠️ FLEKSJA: Pojęcia w mianowniku — odmieniaj przez przypadki."
    )
    concept_instr = pre_batch.get("_concept_instruction", "")
    must_concepts = pre_batch.get("_must_cover_concepts", [])
    if concept_instr:
        parts.append(concept_instr + FLEXION_NOTE)
    elif must_concepts:
        concept_names = [c.get("text", c) if isinstance(c, dict) else str(c) for c in must_concepts[:10]]
        parts.append(
            "═══ POJĘCIA TEMATYCZNE ═══\n"
            f"Wpleć naturalnie: {', '.join(concept_names)}"
            + FLEXION_NOTE
        )

    cooc_pairs = pre_batch.get("_cooccurrence_pairs") or []
    if cooc_pairs:
        cooc_lines = []
        for pair in cooc_pairs[:8]:
            if isinstance(pair, dict):
                e1 = pair.get("entity1", pair.get("source", ""))
                e2 = pair.get("entity2", pair.get("target", ""))
                if e1 and e2:
                    cooc_lines.append(f'  • "{e1}" + "{e2}"')
        if cooc_lines:
            parts.append("═══ WSPÓŁWYSTĘPOWANIE ═══\n" + "\n".join(cooc_lines))

    first_para_ents = pre_batch.get("_first_paragraph_entities") or []
    if first_para_ents:
        fp_names = [ent.get("entity", ent.get("text", ent)) if isinstance(ent, dict) else str(ent) for ent in first_para_ents[:6]]
        fp_names = [f'"{n}"' for n in fp_names if n]
        if fp_names:
            parts.append(f"PIERWSZY AKAPIT: {', '.join(fp_names)}")

    h2_ents = pre_batch.get("_h2_entities") or []
    if h2_ents:
        h2_names = [ent.get("entity", ent.get("text", ent)) if isinstance(ent, dict) else str(ent) for ent in h2_ents[:8]]
        h2_names = [f'"{n}"' for n in h2_names if n]
        if h2_names:
            parts.append(f"ENCJE H2: {', '.join(h2_names)}")

    eav_triples = pre_batch.get("_eav_triples") or []
    if eav_triples:
        eav_lines = ["═══ CECHY ENCJI (EAV) ═══"]
        for e in eav_triples[:10]:
            eav_lines.append(f'  • "{e.get("entity","")}": {e.get("attribute","")} → {e.get("value","")}')
        parts.append("\n".join(eav_lines))

    svo_triples = pre_batch.get("_svo_triples") or []
    if svo_triples:
        svo_lines = ["═══ RELACJE (SVO) ═══"]
        for t in svo_triples[:12]:
            svo_lines.append(f'  {t.get("subject","")} → {t.get("verb","")} → {t.get("object","")}')
        parts.append("\n".join(svo_lines))

    entity_gaps = pre_batch.get("_entity_gaps") or []
    if entity_gaps:
        high_gaps = [g for g in entity_gaps if g.get("priority") == "high"]
        if high_gaps:
            gap_lines = ["═══ LUKI ENCYJNE ═══"]
            for g in high_gaps[:5]:
                reason = f" — {g['why']}" if g.get("why") else ""
                gap_lines.append(f'  🔴 "{g["entity"]}"{reason}')
            parts.append("\n".join(gap_lines))

    return "\n\n".join(parts) if parts else ""


def _fmt_natural_polish(pre_batch):
    """Anti-stuffing + fleksja — v2.3: uses search_variants for richer variation."""
    parts = ["═══ ANTY-STUFFING ═══"]

    _batch_type = pre_batch.get("batch_type", "")
    _is_final = _batch_type.upper() in ("FINAL", "CONCLUSION")

    parts.append(
        "FLEKSJA: Odmiany = jedno użycie w oczach Google (lematyzacja).\n"
        "  Max 2× ta sama FORMA frazy w jednym akapicie.\n"
        "  Max 3× ta sama FORMA frazy w całym batchu — potem rotuj na odmianę lub peryfrazę.\n"
        "Rozkładaj frazy RÓWNOMIERNIE po tekście — nie skupiaj w jednym akapicie.\n"
        "PERYFRAZY > POWTÓRZENIA: gdy fraza blisko limitu — użyj peryfrazy.\n"
        "  ❌ 'Wykroczenie polega... Wykroczenie grozi... Za wykroczenie kara...'\n"
        "  ✅ 'Wykroczenie polega... Czyn karalny grozi... Za ten delikt kara...'"
    )

    # v67: Extra warning for FINAL batches which tend to keyword-stuff
    if _is_final:
        parts.append(
            "⚠️ LAST BATCH RULE: To jest końcowa sekcja artykułu.\n"
            "  NIE próbuj 'nadrabiać' brakujących fraz — pisz naturalnie.\n"
            "  NIE zaczynaj każdego akapitu od frazy kluczowej.\n"
            "  Użyj MAX 2 fraz EXTENDED z listy — resztę pomiń.\n"
            "  Lepszy naturalny tekst bez fraz niż sztuczne upychanie."
        )

    # Dynamic anaphora with search variants
    _raw_main = pre_batch.get("main_keyword") or {}
    _main_name = _raw_main.get("keyword", "") if isinstance(_raw_main, dict) else str(_raw_main)
    if _main_name:
        # Try search_variants first (richest source)
        sv = pre_batch.get("_search_variants") or {}
        peryfrazy = sv.get("peryfrazy", [])
        potoczne = sv.get("potoczne", [])
        formalne = sv.get("formalne", [])

        # Build anaphora list from variants (peryfrazy first, then mix)
        anaphora_pool = []
        for v in peryfrazy[:3]:
            anaphora_pool.append(v)
        for v in potoczne[:2]:
            if v not in anaphora_pool:
                anaphora_pool.append(v)
        for v in formalne[:2]:
            if v not in anaphora_pool:
                anaphora_pool.append(v)

        # Fallback to entity_synonyms if no search_variants
        if not anaphora_pool:
            _entity_seo = (pre_batch.get("s1_data") or {}).get("entity_seo") or pre_batch.get("entity_seo") or {}
            _dynamic_synonyms = _entity_seo.get("entity_synonyms", [])
            if _dynamic_synonyms and len(_dynamic_synonyms) >= 2:
                anaphora_pool = [str(s) for s in _dynamic_synonyms[:5]]
            else:
                anaphora_pool = ["konkretny podmiot z kontekstu"]

        synonyms = ", ".join(anaphora_pool[:5])
        parts.append(f"ANTY-ANAPHORA [{_main_name}] MAX 2 ZDANIA Z RZĘDU → zmień na: {synonyms}")

        # Add fleksyjne variants hint (helps LLM with case variation)
        fleksyjne = sv.get("fleksyjne", [])
        if fleksyjne:
            parts.append(f"ODMIANY: {', '.join(fleksyjne[:4])}")

    parts.append(
        "FAQ: każde pytanie zaczynaj INNYM słowem (Czy, Kiedy, Jak, Co, Ile, Dlaczego).\n"
        "TEST STUFFINGU: usunięcie frazy NIE zmienia sensu = stuffing → usuń powtórzenie."
    )

    return "\n".join(parts)


def _fmt_serp_enrichment(pre_batch):
    """Old SERP enrichment — used by category prompt."""
    serp = pre_batch.get("serp_enrichment") or {}
    enhanced = pre_batch.get("enhanced") or {}
    paa = serp.get("paa_for_batch") or enhanced.get("paa_from_serp") or []
    lsi = serp.get("lsi_keywords") or []
    chips = serp.get("refinement_chips") or []
    if not paa and not lsi and not chips:
        return ""
    parts = ["═══ WZBOGACENIE Z SERP ═══"]
    if chips:
        parts.append(f"Refinement Chips: {', '.join(str(c) for c in chips[:8])}")
    if paa:
        parts.append("PAA:")
        for q in paa[:5]:
            q_text = q.get("question", q) if isinstance(q, dict) else q
            if q_text:
                parts.append(f'  ❓ {q_text}')
    if lsi:
        lsi_names = [l.get("keyword", l) if isinstance(l, dict) else l for l in lsi[:8]]
        parts.append(f'LSI: {", ".join(str(n) for n in lsi_names)}')
    return "\n".join(parts) if len(parts) > 1 else ""


# ════════════════════════════════════════════════════════════
# FAQ PROMPT BUILDER (unchanged)
# ════════════════════════════════════════════════════════════

def build_faq_system_prompt(pre_batch=None):
    base = (
        "Jesteś doświadczonym polskim copywriterem SEO. "
        "Piszesz sekcję FAQ: zwięzłe, konkretne odpowiedzi. "
        "Każda odpowiedź ma szansę trafić do Google Featured Snippet."
    )
    gpt_instructions = ""
    if pre_batch:
        gpt_instructions = pre_batch.get("gpt_instructions_v39", "")
    if gpt_instructions:
        return base + "\n\n" + gpt_instructions
    return base


def build_faq_user_prompt(paa_data, pre_batch=None):
    if isinstance(paa_data, list):
        paa_data = {"serp_paa": paa_data}
    elif not isinstance(paa_data, dict):
        paa_data = {}
    paa_questions = paa_data.get("serp_paa") or []
    unused = paa_data.get("unused_keywords") or {}
    avoid = paa_data.get("avoid_in_faq") or []
    if isinstance(avoid, dict):
        avoid = avoid.get("topics") or []
    elif isinstance(avoid, str):
        avoid = [avoid] if avoid.strip() else []
    elif not isinstance(avoid, list):
        avoid = []
    instructions_raw = paa_data.get("instructions", "")
    if isinstance(instructions_raw, dict):
        instr_parts = []
        for k, v in instructions_raw.items():
            if isinstance(v, str):
                instr_parts.append(f"• {v}")
            elif isinstance(v, dict):
                for sk, sv in v.items():
                    if isinstance(sv, str):
                        instr_parts.append(f"• {sk}: {sv}")
        instructions = "\n".join(instr_parts)
    elif isinstance(instructions_raw, str):
        instructions = instructions_raw
    else:
        instructions = ""

    enhanced_paa = []
    if pre_batch:
        enhanced = pre_batch.get("enhanced") or {}
        if not isinstance(enhanced, dict):
            enhanced = {}
        enhanced_paa = enhanced.get("paa_from_serp") or []
        if not isinstance(enhanced_paa, list):
            enhanced_paa = []

    keyword_limits = {}
    if pre_batch:
        keyword_limits = pre_batch.get("keyword_limits") or {}
        if not isinstance(keyword_limits, dict):
            keyword_limits = {}
    stop_raw = keyword_limits.get("stop_keywords") or []
    stop_names = [s.get("keyword", s) if isinstance(s, dict) else s for s in stop_raw]

    style = {}
    if pre_batch:
        style = pre_batch.get("style_instructions") or {}

    sections = []
    sections.append("═══ SEKCJA FAQ ═══\nNapisz sekcję FAQ. Zaczynaj od:\nh2: Najczęściej zadawane pytania")

    all_paa = list(dict.fromkeys(paa_questions + enhanced_paa))
    if all_paa:
        sections.append("Pytania z Google (PAA):")
        for i, q in enumerate(all_paa[:8], 1):
            q_text = q.get("question", q) if isinstance(q, dict) else q
            if q_text and q_text.strip():
                sections.append(f'  {i}. {q_text}')
        sections.append("Wybierz 4-6 najlepszych.")

    if unused:
        if isinstance(unused, dict):
            unused_list = []
            for cat, items in unused.items():
                if isinstance(items, list):
                    unused_list.extend(items[:5])
                elif isinstance(items, str):
                    unused_list.append(items)
            if unused_list:
                names = ", ".join(f'"{u}"' if isinstance(u, str) else f'"{u.get("keyword", "")}"' for u in unused_list[:8])
                sections.append(f'\nFrazy nieużyte: {names}')
        elif isinstance(unused, list):
            names = ", ".join(f'"{u}"' for u in unused[:8])
            sections.append(f'\nFrazy nieużyte: {names}')

    if avoid:
        topics = ", ".join(f'"{a}"' if isinstance(a, str) else f'"{a.get("topic", "")}"' for a in avoid[:8])
        sections.append(f'\nNIE powtarzaj: {topics}')

    if stop_names:
        sections.append(f'\n🛑 STOP: {", ".join(f"{s}" for s in stop_names[:5])}')

    if style:
        forbidden = style.get("forbidden_phrases") or []
        if forbidden:
            sections.append(f'ZAKAZANE: {", ".join(forbidden[:5])}')

    if pre_batch and pre_batch.get("article_memory"):
        mem = pre_batch["article_memory"]
        if isinstance(mem, dict):
            topics = mem.get("topics_covered") or []
            if topics:
                topic_names = [t if isinstance(t, str) else t.get("topic", "") for t in topics[:6]]
                sections.append(f'\nTematy z artykułu: {", ".join(topic_names)}')

    if instructions:
        sections.append(f'\n{instructions}')

    sections.append("""
═══ FORMAT ═══
h2: Najczęściej zadawane pytania

h3: [Pytanie, 5-10 słów]
[Odpowiedź 60-120 słów]
→ Zdanie 1: BEZPOŚREDNIA odpowiedź
→ Zdanie 2-3: rozwinięcie
→ Zdanie 4: praktyczna wskazówka

Zero markdown (**, __, #). Zero tagów HTML (<h3>, <b>, <strong>).
Każdy h3: na OSOBNEJ linii z pustą linią powyżej.
Napisz 4-6 pytań. TYLKO treść.""")

    return "\n\n".join(sections)


# ════════════════════════════════════════════════════════════
# H2 PLAN PROMPT BUILDER (unchanged)
# ════════════════════════════════════════════════════════════

def build_h2_plan_system_prompt():
    return (
        "Jesteś ekspertem SEO z 10-letnim doświadczeniem w planowaniu architektury treści. "
        "Tworzysz logiczne, wyczerpujące struktury nagłówków H2."
    )


def build_h2_plan_user_prompt(main_keyword, mode, s1_data, all_user_phrases, user_h2_hints=None):
    s1_data = s1_data or {}
    competitor_h2 = s1_data.get("competitor_h2_patterns") or []
    suggested_h2s = (s1_data.get("content_gaps") or {}).get("suggested_new_h2s", [])
    content_gaps = s1_data.get("content_gaps") or {}
    causal_triplets = s1_data.get("causal_triplets") or {}
    paa = s1_data.get("paa") or s1_data.get("paa_questions") or []
    serp_analysis = s1_data.get("serp_analysis") or {}
    related_searches = s1_data.get("related_searches") or serp_analysis.get("related_searches") or []

    sections = []
    mode_desc = "standard = pełny artykuł" if mode == "standard" else "fast = krótki, max 3 sekcje"
    sections.append(f"HASŁO GŁÓWNE: {main_keyword}\nTRYB: {mode} ({mode_desc})")

    if competitor_h2:
        def _h2_count(h):
            return h.get("count", h.get("sources", 0)) if isinstance(h, dict) else 0
        sorted_h2 = sorted(competitor_h2[:30], key=_h2_count, reverse=True)
        lines = ["═══ WZORCE H2 KONKURENCJI — posortowane po popularności ═══",
                 "Liczba przy H2 = ilu konkurentów używa tego tematu.",
                 "H2 z wysoką liczbą = MUST HAVE w Twoim artykule (użytkownicy tego szukają)."]
        for i, h in enumerate(sorted_h2[:20], 1):
            if isinstance(h, dict):
                pattern = h.get("text", h.get("pattern", h.get("h2", str(h))))
                count = _h2_count(h)
                bar = "█" * min(count, 8)
                lines.append(f"  {i:2}. [{bar:<8}] {count}× — {pattern}")
            elif isinstance(h, str):
                lines.append(f"  {i:2}. {h}")
        sections.append("\n".join(lines))

    if suggested_h2s:
        lines = ["═══ SUGEROWANE NOWE H2 (luki, tego NIKT z konkurencji nie pokrywa) ═══"]
        for h in suggested_h2s[:10]:
            h_text = h if isinstance(h, str) else h.get("h2", h.get("title", str(h)))
            lines.append(f"  • {h_text}")
        sections.append("\n".join(lines))

    gap_priority_map = {
        "paa_unanswered": ("🔴 HIGH", "PAA bez odpowiedzi"),
        "depth_missing": ("🟡 MED-HIGH", "Brak głębi"),
        "subtopic_missing": ("🟢 MED", "Brakujący podtemat"),
        "gaps": ("", "Luka"),
    }
    all_gaps = []
    for key in ("paa_unanswered", "depth_missing", "subtopic_missing", "gaps"):
        priority, label = gap_priority_map.get(key, ("", ""))
        items = content_gaps.get(key) or []
        for item in items[:5]:
            gap_text = item if isinstance(item, str) else item.get("gap", item.get("topic", str(item)))
            if gap_text and gap_text not in [g[0] for g in all_gaps]:
                all_gaps.append((gap_text, priority, label))
    if all_gaps:
        lines = ["═══ LUKI TREŚCIOWE (tematy do pokrycia, priorytet od najwyższego) ═══"]
        for gap_text, priority, label in all_gaps[:10]:
            prefix = f"[{priority}] " if priority else ""
            lines.append(f"  • {prefix}{gap_text}")
        sections.append("\n".join(lines))

    if paa:
        lines = ["═══ PAA ═══"]
        for q in paa[:8]:
            q_text = q.get("question", q) if isinstance(q, dict) else q
            if q_text:
                lines.append(f"  ❓ {q_text}")
        sections.append("\n".join(lines))

    if related_searches:
        rs_texts = []
        for rs in related_searches[:12]:
            rs_t = rs if isinstance(rs, str) else (rs.get("query", "") or rs.get("text", ""))
            if rs_t:
                rs_texts.append(rs_t)
        if rs_texts:
            lines = ["═══ RELATED SEARCHES (Google podpowiada po main_keyword) ═══",
                     "Użyj tych fraz jako wskazówek tematycznych przy tworzeniu H2.",
                     "Wiele z nich to podtematy których BRAK u konkurencji — Twoja szansa:"]
            for rs_t in rs_texts:
                lines.append(f"  🔍 {rs_t}")
            sections.append("\n".join(lines))

    triplet_list = (causal_triplets.get("chains") or causal_triplets.get("singles")
                    or causal_triplets.get("triplets") or [])[:8]
    if triplet_list:
        lines = ["═══ PRZYCZYNOWE ZALEŻNOŚCI (cause→effect z konkurencji) ═══",
                 "Confidence: 🔴 ≥0.9 UŻYJ | 🟡 ≥0.6 gdy pasuje | 🟢 <0.6 opcjonalnie",
                 "is_chain=True (A→B→C) = najcenniejsze. Buduj logiczny przepływ"]
        for t in triplet_list:
            if isinstance(t, dict):
                cause = t.get("cause", t.get("subject", ""))
                effect = t.get("effect", t.get("object", ""))
                conf = t.get("confidence", 0)
                is_chain = t.get("is_chain", False)
                ind = "🔴" if conf >= 0.9 else ("🟡" if conf >= 0.6 else "🟢")
                chain_tag = " [CHAIN]" if is_chain else ""
                lines.append(f"  {ind} {cause} → {effect}{chain_tag}")
            elif isinstance(t, str):
                lines.append(f"  • {t}")
        sections.append("\n".join(lines))

    if user_h2_hints:
        h2_hints_list = "\n".join(f'  • "{h}"' for h in user_h2_hints[:10])
        sections.append(f"""═══ FRAZY H2 UŻYTKOWNIKA ═══

Użytkownik podał te frazy z myślą o nagłówkach H2.
Wykorzystaj je w nagłówkach tam, gdzie brzmią naturalnie po polsku.
Nie musisz użyć każdej, ale nie ignoruj ich. Dopasuj z wyczuciem.

FRAZY H2:
{h2_hints_list}""")

    if all_user_phrases:
        phrases_text = ", ".join(f'"{p}"' for p in all_user_phrases[:15])
        sections.append(f"""═══ KONTEKST TEMATYCZNY (frazy BASIC/EXTENDED) ═══

Poniższe frazy będą użyte W TREŚCI artykułu (nie w nagłówkach).
Zaplanuj H2 tak, by każda fraza miała naturalną sekcję:

{phrases_text}""")

    # H2 scaling — driven by target length, not arbitrary thresholds
    length_analysis = s1_data.get("length_analysis") or {}
    rec_length = length_analysis.get("recommended") or s1_data.get("recommended_length") or 0
    median_length = length_analysis.get("median") or s1_data.get("median_length") or 0

    if mode == "fast":
        fast_note = "Tryb fast: DOKŁADNIE 3 sekcje + FAQ."
    else:
        target = rec_length or (median_length * 2) or 1500
        # ~250 words per H2 section + intro → derive count from length
        _raw_h2 = max(3, min(12, target // 250))
        h2_min = max(3, _raw_h2 - 1)
        h2_max = _raw_h2 + 1
        h2_range = f"{h2_min}-{h2_max}"
        fast_note = f"Tryb standard: {h2_range} sekcji + FAQ. Max {h2_max + 1} H2 łącznie."

    h2_hint_rule = ("Uwzględnij frazy H2 użytkownika." if user_h2_hints
                    else "Dobierz nagłówki na podstawie S1 i luk.")

    sections.append(f"""═══ ZASADY ═══
1. LICZBA H2: {fast_note}
2. OSTATNI H2: "Najczęściej zadawane pytania"
3. Pokryj wzorce konkurencji + luki
4. {h2_hint_rule}
5. Logiczna narracja
6. NIE powtarzaj hasła głównego w każdym H2
7. Naturalna polszczyzna

═══ FORMAT ═══
JSON array: ["H2 pierwszy", ..., "Najczęściej zadawane pytania"]""")

    return "\n\n".join(sections)


# ════════════════════════════════════════════════════════════
# CATEGORY PROMPT BUILDERS (unchanged)
# ════════════════════════════════════════════════════════════

def build_category_system_prompt(pre_batch, batch_type, category_data=None):
    pre_batch = pre_batch or {}
    category_data = category_data or {}
    parts = []

    store_name = category_data.get("store_name") or "sklep"
    store_desc = category_data.get("store_description") or ""
    brand_voice = category_data.get("brand_voice") or ""

    store_ctx = f" dla {store_name}" if store_name != "sklep" else ""
    store_desc_line = f"\n{store_desc}" if store_desc else ""
    parts.append(f"""<role>
Jesteś doświadczonym copywriterem e-commerce{store_ctx}{store_desc_line}.
Specjalizujesz się w opisach kategorii sklepów internetowych.
Nie jesteś blogerem — piszesz tekst sprzedażowy.
</role>""")

    parts.append("""<goal>
Opis kategorii e-commerce, który:
  • wspiera intencję transakcyjną,
  • naturalnie zawiera słowa kluczowe (gęstość 1,0–2,0%),
  • buduje entity salience >0,30,
  • używa konkretnych nazw produktów, cen, cech,
  • pomaga kupującemu podjąć decyzję.
80% transakcyjnych, 20% informacyjnych.
</goal>""")

    target = category_data.get("target_audience") or ""
    target_line = f"\nGrupa docelowa: {target}" if target else ""
    parts.append(f"""<audience>
Kupujący z intencją zakupową.{target_line}
</audience>""")

    voice_line = f"\nBrand voice: {brand_voice}" if brand_voice else ""
    parts.append(f"""<tone>
Ton: autorytatywny, pomocny, zwięzły.{voice_line}
Unikaj: „szeroki wybór", „coś dla każdego", „nie szukaj dalej".
</tone>""")

    parts.append("""<epistemology>
ŹRÓDŁA: dane wejściowe, konkurencja z SERP, wiedza produktowa.
❌ ZAKAZ: nie wymyślaj produktów, cen, recenzji, certyfikatów.
</epistemology>""")

    cat_type = category_data.get("category_type", "subcategory")
    if cat_type == "parent":
        struct_desc = """KATEGORIA NADRZĘDNA (200–500 słów):
  Blok 1 — INTRO (50–100 słów): keyword + opis + USP + linki podkategorii
  Blok 2 — SEO (100–300 słów): 1–2 H2, przegląd, dlaczego u nas
  Blok 3 — FAQ (2–3 pytania)"""
    else:
        struct_desc = """PODKATEGORIA (500–1200 słów):
  Blok 1 — INTRO (50–150 słów): keyword + opis + USP
  Blok 2 — SEO (400–800 słów): 2–4 H2 (jak wybrać, rodzaje, dlaczego u nas)
  Blok 3 — FAQ (3–6 pytań)"""

    parts.append(f"<category_structure>\n{struct_desc}\n</category_structure>")

    parts.append("""<rules>
KEYWORD DENSITY: 1,0–2,0%.
ENTITY SALIENCE: cel >0,30. Entity-rich: typy, materiały, technologie, marki.
PASSAGE-FIRST: intro = standalone summary.
LISTY HTML: 3+ elementów → lista.
SPACING: MAIN ~60 słów, BASIC ~80, EXTENDED ~120.
ANTI-AI: zakaz fraz kliszowych.
LINKI: 3–8 kontekstowych na 300–500 słów.
FORMAT: h2:/h3:. Zero markdown (**, __, #). Zero tagów HTML (<h2>, <h3>).
  Każdy h2:/h3: na OSOBNEJ linii z pustą linią powyżej.
</rules>""")

    parts.append("""<examples>
PRZYKŁAD DOBRY:
<example_good>
Damskie buty do biegania od Nike, ASICS i Brooks — od 299 do 1 199 zł.
Bestseller sezonu: Nike Air Zoom Pegasus 41 (4,7★, 312 recenzji)
łączy responsywną piankę React z siateczką Flyknit.
Darmowy zwrot 30 dni, wysyłka w 24h.
</example_good>
</examples>""")

    return "\n\n".join(parts)


def build_category_user_prompt(pre_batch, h2, batch_type, article_memory=None, category_data=None):
    pre_batch = pre_batch or {}
    category_data = category_data or {}
    sections = []

    sections.append(
        "Piszesz opis kategorii e-commerce — ton pomocny, "
        "konkretny, wspierający decyzję zakupową. "
        "Zasady w system prompcie."
    )

    # Opening pattern rotation for category (commercial variants)
    _CAT_PATTERNS = [
        ("A", "KONKRET PRODUKTOWY",
         "Zacznij od konkretnego produktu, ceny lub cechy. "
         "Np: 'Nike Pegasus 41 od 549 zł — bestseller z 312 recenzjami...'"),
        ("B", "ZAKRES/STATYSTYKA",
         "Zacznij od zakresu, liczby lub faktu. "
         "Np: 'Ponad 200 modeli butów do biegania od 15 marek...'"),
        ("C", "POTRZEBA KUPUJĄCEGO",
         "Zacznij od potrzeby klienta. "
         "Np: 'Szukasz buta na maraton z amortyzacją na twardym podłożu?'"),
        ("D", "USP/WYRÓŻNIK",
         "Zacznij od przewagi sklepu. "
         "Np: 'Darmowy zwrot 30 dni i dobór rozmiaru z ekspertem...'"),
    ]
    batch_num = pre_batch.get("batch_number", 1) or 1
    pattern_idx = (batch_num - 1) % len(_CAT_PATTERNS)
    p_letter, p_name, p_desc = _CAT_PATTERNS[pattern_idx]
    sections.append(
        f"OTWARCIE — wzorzec {p_letter} ({p_name}):\n{p_desc}"
    )

    # Category context
    cat_ctx_parts = []
    cat_name = category_data.get("category_name") or pre_batch.get("main_keyword", "")
    if isinstance(cat_name, dict):
        cat_name = cat_name.get("keyword", "")
    cat_type = category_data.get("category_type", "subcategory")
    hierarchy = category_data.get("hierarchy") or ""
    store_name = category_data.get("store_name") or ""
    usp = category_data.get("usp") or ""
    products = category_data.get("products") or ""
    bestseller = category_data.get("bestseller") or ""
    price_range = category_data.get("price_range") or ""

    cat_ctx_parts.append(f"Kategoria: {cat_name}")
    cat_ctx_parts.append(f"Typ: {'nadrzędna' if cat_type == 'parent' else 'podkategoria'}")
    if hierarchy: cat_ctx_parts.append(f"Hierarchia: {hierarchy}")
    if store_name: cat_ctx_parts.append(f"Sklep: {store_name}")
    if usp: cat_ctx_parts.append(f"USP: {usp}")
    if products: cat_ctx_parts.append(f"Produkty:\n{products}")
    if bestseller: cat_ctx_parts.append(f"Bestseller: {bestseller}")
    if price_range: cat_ctx_parts.append(f"Ceny: {price_range}")
    sections.append("═══ DANE KATEGORII ═══\n" + "\n".join(cat_ctx_parts))

    _schema_guard(pre_batch)

    formatters = [
        lambda: _fmt_batch_header(pre_batch, h2, batch_type),
        lambda: _fmt_keywords(pre_batch),
        lambda: _fmt_smart_instructions(pre_batch),
        lambda: _fmt_semantic_plan(pre_batch, h2),
        lambda: _fmt_coverage_density(pre_batch),
        lambda: _fmt_continuation(pre_batch),
        lambda: _fmt_article_memory(article_memory),
        lambda: _fmt_h2_remaining(pre_batch),
        lambda: _fmt_entity_salience(pre_batch),
        lambda: _fmt_serp_enrichment(pre_batch),
        lambda: _fmt_natural_polish(pre_batch),
        lambda: _fmt_style(pre_batch),
        lambda: _fmt_output_format(h2, batch_type),
    ]

    for fmt in formatters:
        try:
            result = fmt()
            if result:
                sections.append(result)
        except Exception:
            pass

    return "\n\n".join(sections)
