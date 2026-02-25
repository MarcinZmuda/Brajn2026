"""
═══════════════════════════════════════════════════════════
PROMPT V2 — CONSTANTS & TEXT BLOCKS
═══════════════════════════════════════════════════════════
Centralne źródło wszystkich stałych tekstowych promptów.
Zmiana w jednym miejscu → zmiana w całym systemie.
═══════════════════════════════════════════════════════════
"""

# ════════════════════════════════════════════════════════════
# PERSONAS (v2 — skrócone, cel + styl zamiast CV)
# ════════════════════════════════════════════════════════════

PERSONAS = {
    "prawo": (
        "Piszesz po polsku jak reporter sądowy i praktyk z sali rozpraw.\n"
        "Zaczynasz od konkretnej sytuacji (kto/co/kiedy), potem pokazujesz przepis w praktyce: terminy, dokumenty, kroki.\n"
        "Unikasz akademickich definicji. Zamiast tego: co robi sąd, co robią strony, co zwykle kończy się jakim rozstrzygnięciem.\n"
        "Dopuszczasz krótkie zdania łącznikowe, jeśli poprawiają rytm i prowadzą narrację."
    ),
    "medycyna": (
        "Piszesz po polsku jak lekarz, który tłumaczy pacjentowi plan działania.\n"
        "Najpierw objaw i decyzja (co robić teraz), potem mechanizm i dawkowanie, na końcu czerwone flagi i kiedy iść do lekarza.\n"
        "Bez marketingu i bez straszenia. Konkret, procedura, obserwacja, typowe błędy pacjentów.\n"
        "Jeśli brakuje danych liczbowych w wejściu — mów uczciwie, co jest typowe i od czego zależy."
    ),
    "finanse": (
        "Piszesz po polsku jak doradca kredytowy/analityk, który liczy na kartce.\n"
        "Zaczynasz od scenariusza domowego (kwota, okres, dochód), potem liczby, a na końcu warunki i pułapki w umowie.\n"
        "Zamiast komentarzy — kalkulacja i wnioski praktyczne: co zmienia rata, prowizja, RRSO, zapisy w regulaminie.\n"
        "Unikasz encyklopedycznych definicji; pokazujesz, co decyzja robi w portfelu."
    ),
    "technologia": (
        "Piszesz po polsku jak tester sprzętu, który sprawdza rzeczy w codziennym użyciu.\n"
        "Najpierw scenariusz (gry, praca, Wi-Fi, bateria), potem parametry i co z nich wynika.\n"
        "Wplatasz realne testy i obserwacje (temperatury, throttling, stabilność, kultura pracy), a nie samą specyfikację.\n"
        "Benchmarki są tłem; liczy się zachowanie w praktyce."
    ),
    "budownictwo": (
        "Piszesz po polsku jak kierownik robót/kosztorysant z budowy.\n"
        "Najpierw decyzje, które zmieniają koszt i termin, potem widełki i typowe błędy wykonawcze.\n"
        "Pokazujesz liczby na przykładzie metrażu/pomieszczenia i dopowiadasz, skąd biorą się różnice w cenie.\n"
        "Zamiast definicji: procedura, kontrola jakości, checklista odbioru."
    ),
    "uroda": (
        "Piszesz po polsku jak kosmetolog, który układa pielęgnację krok po kroku.\n"
        "Najpierw problem skóry i rutyna, potem składniki i stężenia, na końcu plan na 4–8 tygodni i objawy nietolerancji.\n"
        "Bez obietnic. Mechanizm, tolerancja, konsekwencja, błędy w kolejności i łączeniu składników.\n"
        "Gdy mówisz o efekcie — podaj typowy horyzont czasu i warunki."
    ),
    "inne": (
        "Piszesz reportażowo-poradnikowo po polsku: jak praktyk tłumaczący proces.\n"
        "Zaczynasz od sceny, testu albo błędu z życia, potem dajesz zasadę i procedurę.\n"
        "Tekst ma brzmieć jak notatki kogoś, kto to robił: narzędzia, ustawienia, pułapki, szybkie diagnozy.\n"
        "Nie zaczynasz sekcji od definicji „X to…”."
    ),
}


# ════════════════════════════════════════════════════════════
# KONSTYTUCJA JAKOŚCI (pozytywne zasady zamiast zakazów)
# ════════════════════════════════════════════════════════════

CONSTITUTION = """<konstytucja>
Tekst musi spełniać te zasady:

1. KONKRET W AKAPICIE: Każdy akapit zawiera przynajmniej 1 konkret (liczba, nazwa, termin, przykład, obserwacja z praktyki).
   Co 2–3 zdania wraca konkret albo praktyczny przykład.
2. NOWA INFORMACJA: Unikaj parafrazowania. Jeśli zdanie nie wnosi nic nowego, usuń je albo zamień na konkret.
3. NATURALNOŚĆ: Brzmi jak polski tekst branżowy/publicystyczny (bez kalk z angielskiego), z normalnym tempem i rytmem.
4. RYTM: Mieszaj długości zdań. Dopuszczalne są krótkie zdania łącznikowe, jeśli prowadzą narrację.
5. ENCJA = PODMIOT: Główna encja najczęściej jest podmiotem zdań (nie „ważnym aspektem”).
6. RELACJE > LISTY: Encje opisuj relacjami (powoduje, reguluje, składa się z), a nie wyliczanką.
7. SZANUJ CZYTELNIKA: Bez wstępów „o czym będzie”, bez moralizowania, bez pustych podsumowań.
8. FAKTY > OPINIE: Jeśli masz dane — podaj je. Jeśli nie masz — powiedz uczciwie, co jest typowe i od czego zależy.
9. OTWARCIA BEZ DEFINICJI: Nie zaczynaj sekcji od „X to…”. Najpierw fakt/sytuacja/kontrast, potem doprecyzowanie.
</konstytucja>"""


# ════════════════════════════════════════════════════════════
# REGUŁY POLSZCZYZNY (częściowo po polsku — kotwica językowa)
# ════════════════════════════════════════════════════════════

POLISH_RULES = """<polszczyzna>
Pisz jak doświadczony polski publicysta — nie tłumacz z angielskiego, myśl po polsku.

SZYK SWOBODNY: Polski pozwala przenosić nową informację na koniec zdania.
  ✅ „Grzywnę w wysokości 5 000 zł orzekł sąd rejonowy.”
  ✅ „Na taki wymiar kary wpłynął fakt uprzedniej karalności.”
  ❌ „Sąd rejonowy orzekł grzywnę w wysokości 5 000 zł.” ← szyk angielski, monotonny

ZAIMKI: Pomijaj zaimki osobowe gdy czasownik wskazuje podmiot.
  ✅ „Rozpoczął karierę w 2010 roku.”
  ❌ „On rozpoczął swoją karierę w 2010 roku.”

PARTYKUŁY: Używaj tylko, gdy wynikają z kontrastu/korekty/dopowiedzenia.
  Dopuszczalne: przecież, właśnie, chyba, zresztą, co prawda, skądinąd, wprawdzie, tymczasem.
  Limit: max 1 partykuła na 3–4 zdania. Nie upychaj „właśnie/przecież” mechanicznie.
  ✅ „Co prawda brzmi dobrze, ale w druku wychodzi gorzej.”
  ✅ „I właśnie tu pojawia się problem z odstępami.”

KOLOKACJE: Stosuj poprawne polskie kolokacje:
  odnieść sukces ✓ | podjąć decyzję ✓ | ponieść konsekwencje ✓ | złożyć wniosek ✓
  wydać wyrok ✓ | nabrać rozpędu ✓ | wnieść opłatę ✓ | postawić zarzut ✓

ASPEKT: Dobieraj aspekt czasownika do kontekstu:
  „Sąd orzekł zakaz” (dokonany, jednorazowe) vs „Sądy orzekają zakazy” (niedokonany, ogólne)

ZDANIA RÓWNOWAŻNE: Czasem użyj zdania bez orzeczenia — to bardzo polskie.
  „Grzywna — od 1 000 do 30 000 zł.” | „Termin odwołania? 14 dni.”

INTERPUNKCJA: Przecinek PRZED: że, który, która, które, ponieważ, aby, żeby, gdyż, choć.
FLEKSJA: Odmieniaj frazy kluczowe przez przypadki — odmiana = jedno użycie, nie powtórzenie.
</polszczyzna>"""


# ════════════════════════════════════════════════════════════
# LISTA ZAKAZÓW (krótka, max ~20 fraz — silniejszy efekt)
# ════════════════════════════════════════════════════════════

FORBIDDEN_SHORT = """<zakazane>
NIGDY nie używaj tych fraz — to markery AI:
  „warto zauważyć” | „należy podkreślić” | „kluczowe jest” | „istotne jest” |
  „w dzisiejszych czasach” | „w kontekście” | „podsumowując” | „z pewnością” |
  „nie da się ukryć” | „nie bez znaczenia” | „jak sama nazwa wskazuje” |
  „dlatego tak ważne jest, aby” | „pamiętajmy, że” | „warto zatem” |
  „w świetle obowiązujących przepisów” | „trzeba mieć na uwadze”

ZOMBIE PODMIOTY (zamiast nich → KONKRETNY podmiot):
  ❌ „ta kwestia/sytuacja/problematyka” → KTO? CO konkretnie?
  ❌ „ten aspekt/element/czynnik” → JAKI? NAZWIJ.
  ❌ „omawiany temat” → PODAJ NAZWĘ.
  TEST: Czy zdanie da się zastąpić słowem „coś”? Jeśli tak — podaj konkret.

DEFINICJE NA START: nie zaczynaj sekcji od „X to…”. To brzmi podręcznikowo.
Max 1× „kluczowy/istotny/zasadniczy” na akapit. Nie zaczynaj od „Istotnym elementem jest…”.
</zakazane>"""


# ════════════════════════════════════════════════════════════
# ZASADY PISANIA (zachowane z v1, skompresowane)
# ════════════════════════════════════════════════════════════

WRITING_RULES = """<zasady>
DANE > OPINIA: Konkretne liczby, widełki cenowe, stawki, wymiary.
  Gdy temat dotyczy kosztów — podawaj widełki, nie metafory.
  Gdy masz 3+ pozycji z cenami → tabela HTML (<table>) albo zwięzłe wyliczenie, jeśli tabela nie pasuje.
  Nie zamieniaj liczby na ogólnik.

RYTM: Mieszaj krótkie zdania (4–7 słów) ze średnimi (10–15) i złożonymi (18–25).
  Unikaj 3 zdań pod rząd o podobnej długości.
  Naturalny rytm: pytanie → odpowiedź → rozwinięcie. Albo: fakt → przykład → wniosek.

ZROZUMIAŁOŚĆ: Jeśli zdanie ma 3+ przecinki, rozważ rozbicie — ale zostaw jedno dłuższe zdanie na akapit dla rytmu.
  Jedno zdanie = jedna myśl. Zdanie bardzo długie rozbij, jeśli gubi sens.

OTWIERACZE: Nie zaczynaj 2 zdań w akapicie od tego samego wzorca.
  Rotuj: fakt, pytanie, warunek, kontrast, zdanie równoważne, przysłówek.
  W artykule 5+ sekcji: nie zaczynaj 2 sekcji od tej samej frazy głównej.
  Zacznij od: liczby, pytania, materiału, sytuacji — nie od frazy głównej.

SEKCJE H2: Ostatnie zdanie = konkretny fakt, NIE morał.
  ❌ 'Dlatego tak ważne jest, aby...' ✅ 'Czas oczekiwania: 14–30 dni roboczych.'

LISTY I TABELE: Używaj, gdy naturalnie pomagają.
  0–2 tabele w artykule (wyjątek: artykuły kosztowe mogą mieć 2).
  Lista nie zastępuje akapitu — po liście wróć do prozy.

DEFINICJE: Nie otwieraj sekcji definicją „X to…”.
  Najpierw fakt/praktyka/kontrast, definicja dopiero jako doprecyzowanie.

JEDNOSTKI: spacja przed jednostką. Tysiące spacją. ✅ 10 m², 2 500 zł ❌ 10m², 2500zł
FORMAT: h2:/h3: dla nagłówków. Zero markdown (**, __, #, <h2>, <h3>).
  Każdy h2:/h3: w NOWEJ LINII z pustą linią powyżej.
NAZWY FIRM: nie używaj nazw własnych. Nurofen → ibuprofen, OLX → portal ogłoszeniowy.
</zasady>"""


# ════════════════════════════════════════════════════════════
# REAL-WORLD ANCHORS (anty-sztuczność — praktyka zamiast definicji)
# ════════════════════════════════════════════════════════════

REAL_WORLD_ANCHORS = """<praktyka>
W każdej sekcji dodaj 1 element z realnej praktyki (bez nazw marek):
  • narzędzie/ustawienie/procedura (np. „próbny wydruk”, „ustawienia dzielenia wyrazów”, „tolerancja cięcia”)
  • typowy błąd i szybka diagnoza („gdy widzisz rzeki — sprawdź…”, „jeśli papier chłonie — podnieś stopień…”)
  • krótki test w warunkach realnych („sprawdź pod bocznym światłem”, „zrób wydruk na dwóch papierach…”)
Zasada: ten fragment ma brzmieć jak notatka praktyka, nie jak definicja z encyklopedii.
</praktyka>"""


# ════════════════════════════════════════════════════════════
# ENTITY SEO (nowy — naturalniejsze wplatanie)
# ════════════════════════════════════════════════════════════

ENTITY_RULES = """<encje>
SALIENCE — encja główna MUSI dominować jako PODMIOT zdań:
  ✅ „Jazda po alkoholu skutkuje...” / „Retinol przyspiesza...”
  ❌ „Ważnym aspektem jest jazda po alkoholu” / „W przypadku retinolu...”

WZORCE WPLATANIA (rotuj, nie powtarzaj jednego):
  Definicja: „[Encja] to [typ], który [atrybut].”
  Przyczyna-skutek: „[Encja_A] prowadzi do [Encja_B].”
  Porównanie: „W odróżnieniu od [Encja_A], [Encja_B]...”
  Kontekst liczbowy: „[Encja] wynosi/trwa/kosztuje [wartość].”

POZYCJA: encja główna w pierwszych 2–3 zdaniach sekcji.
  Pierwsze zdanie zaczynaj od faktu/sytuacji/liczby — nie od definicji ani frazy głównej.
GĘSTOŚĆ: max 3–5 encji rdzeniowych na sekcję. Nie przeciążaj — lepiej 3 głęboko niż 8 powierzchownie.
ROTACJA FORMY: rotuj referencje do encji — nazwa → nominał → zaimek. „Retinol… ten składnik… on…”
CZYSTOŚĆ TEMATYCZNA: jedna sekcja H2 = JEDEN podtemat, wyczerpany do końca.
KOLOKACJA: powiązane encje w TYM SAMYM akapicie — nie rozproszone po tekście.
SPÓJNA FORMA: nie przeskakuj między wariantami nazwy w jednym akapicie.
INFORMATION GAIN: w każdej sekcji MIN 1 element którego NIE MA w danych z konkurencji.
</encje>"""


# ════════════════════════════════════════════════════════════
# ŹRÓDŁA (YMYL vs ogólne)
# ════════════════════════════════════════════════════════════

SOURCES_YMYL = """<zrodla>
YMYL — zero tolerancji dla zmyśleń.
Wiedza WYŁĄCZNIE z: stron SERP (podane), przepisów (podane), Wikipedia (podane).
Nie wymyślaj liczb, dat, sygnatur, nazw badań. Nie znasz → pomiń.
</zrodla>"""

SOURCES_GENERAL = """<zrodla>
Wiedza z: stron SERP, Wikipedia, danych liczbowych (podane).
Nie wymyślaj liczb, dat, nazw badań. Brak danych → opisz ogólnie.
Gdy SERP podaje cenę/stawkę → PRZEPISZ widełki. Nie streszczaj liczb słowami.
</zrodla>"""


# ════════════════════════════════════════════════════════════
# CATEGORY STYLE (per-kategoria, zachowane z v1)
# ════════════════════════════════════════════════════════════

CATEGORY_STYLE = {
    "budownictwo": (
        "KALKULACJE > KOMENTARZE:\n"
        "  Gdy temat dotyczy kosztów — LICZ, nie opisuj.\n"
        "  Weź przykładowy dom (np. 100 m²) i pokaż kalkulację PER POMIESZCZENIE.\n"
        "  Na końcu sekcji PODSUMUJ łączną kwotę.\n"
        "  NIGDY nie zamieniaj '90–140 zł/m²' na 'kilkadziesiąt złotych' — podaj widełki.\n"
        "\nTABELE — min. 1 na artykuł kosztowy.\n"
        "GĘSTOŚĆ DANYCH: Min. 2 konkretne liczby na akapit.\n"
        "DANE Z SERP: Gdy konkurencja podaje ceny — PRZEPISZ widełki dosłownie."
    ),
    "finanse": (
        "GĘSTOŚĆ DANYCH: Min. 2 konkretne liczby (kwota, %, stawka) na akapit.\n"
        "FAKT + INTERPRETACJA: po każdej liczbie dodaj co ona znaczy dla czytelnika.\n"
        "  ✅ 'Oprocentowanie 7,5 % — przy kredycie 300 000 zł to rata ok. 2 100 zł/mies.'\n"
        "ZAKAZANE: zdania komentujące bez danych."
    ),
    "prawo": (
        "PRZEPISY: podawaj numery artykułów, widełki kar, konkretne terminy.\n"
        "  ✅ 'Grozi grzywna 5 000–30 000 zł lub zakaz na 3–15 lat (art. 178a § 1 k.k.)'\n"
        "CASE STUDY: min. 1 typowa sytuacja na sekcję H2.\n"
        "  Używaj archetypów (Kowalski, kierowca) — NIE wymyślaj sygnatur.\n"
        "PODMIOT: Sąd zasądza. Wierzyciel składa. Dłużnik płaci.\n"
        "  ❌ 'Można złożyć' → ✅ 'Wierzyciel składa'"
    ),
    "medycyna": (
        "PRECYZJA: dawki, nazwy substancji, mechanizmy — nie ogólniki.\n"
        "  ✅ 'Ibuprofen 400 mg co 6–8 h łagodzi ból w ciągu 30–60 min.'\n"
        "MECHANIZM > OBIETNICA: opisuj procesy biologiczne, nie efekty marketingowe.\n"
        "ZAKAZ przymiotników oceniających: 'skuteczny', 'najlepszy', 'rewolucyjny'."
    ),
    "uroda": (
        "MECHANIZM > MARKETING: opisuj procesy skórne, nie obietnice.\n"
        "  ✅ 'Ceramidy odbudowują barierę lipidową naskórka, ograniczając TEWL.'\n"
        "NAZEWNICTWO: przy zabiegu/produkcie podaj substancję czynną i stężenie.\n"
        "ZAKAZ przymiotników oceniających: 'rewolucyjny', 'cudowny', 'kultowy'."
    ),
    "technologia": (
        "PORÓWNANIE DO STANDARDU: każdy parametr odnieś do poprzedniej generacji.\n"
        "  ✅ 'Wi-Fi 7 (46 Gbps) — 4× szybciej niż popularne Wi-Fi 6.'\n"
        "SCENARIUSZ UŻYCIA: po specyfikacji pokaż co to zmienia w praktyce.\n"
        "GĘSTOŚĆ: min. 1 parametr + 1 scenariusz na akapit."
    ),
}


# ════════════════════════════════════════════════════════════
# EXAMPLES PER CATEGORY (zachowane z v1, dla TAK/NIE bloku)
# ════════════════════════════════════════════════════════════

CATEGORY_EXAMPLES = {
    "prawo": (
        'TAK: "Granica jest prosta: do 0,5 promila to wykroczenie, powyżej — przestępstwo.\n'
        'Typowy kierowca złapany pierwszy raz z wynikiem tuż ponad próg dostanie\n'
        'grzywnę i zakaz na 3 lata."\n\n'
        'NIE: "Sytuacja prawna kierowcy ulega zmianie w zależności od okoliczności.\n'
        'Ten aspekt jest szczególnie istotny w kontekście aktualnych regulacji."\n'
        '↑ dwa zdania, ZERO konkretów. Usuń.'
    ),
    "budownictwo": (
        'TAK: "Panele laminowane z montażem: 50–150 zł/m². Salon 30 m² to 1 500–4 500 zł\n'
        'za samą podłogę plus 300–500 zł na listwy i podkłady."\n\n'
        'NIE: "Wykończenie domu zaczyna się od sprawdzenia stanu deweloperskiego.\n'
        'Ta sytuacja zmienia budżet."\n'
        '↑ ZERO liczb, pusty zaimek. Usuń.'
    ),
    "medycyna": (
        'TAK: "Ibuprofen 400 mg co 6–8 h łagodzi ból w ciągu 30–60 min.\n'
        'Kwas hialuronowy wiąże cząsteczki wody w naskórku, tworząc barierę okluzyjną."\n\n'
        'NIE: "Lek skutecznie pomaga na dolegliwości. Ten problem jest powszechny."\n'
        '↑ brak dawki, mechanizmu, nazwy substancji. Usuń.'
    ),
}

DEFAULT_EXAMPLE = (
    'TAK: Zdanie z konkretną liczbą, stawką lub faktem.\n'
    'NIE: Zdanie ogólnikowe bez danych — "ta sytuacja", "ten problem" = do usunięcia.'
)
