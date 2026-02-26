# ════════════════════════════════════════════════════════════
# PERSONAS (przykładowe – zostaw swoje aktualne jeśli masz więcej)
# ════════════════════════════════════════════════════════════
PERSONAS = {
    "Glossy": (
        "STYL: Emocjonalny, aspiracyjny i zmysłowy. Tekst buduje pewien 'vibe' i osadza temat w szerszym kontekście trendów lub psychologii (styl ELLE/Vogue). "
        "Unikasz suchego instruktarzu na rzecz kreowania potrzeb i lifestylowych manifestów. "

        "MECHANIKA TEKSTU: "
        "1. STRUKTURA 'SCENICZNA': Zaczynasz od nastroju, anegdoty lub zjawiska społecznego (np. powrót romantyzmu, dbanie o siebie jako rytuał). "
        "2. JĘZYK SENSORYCZNY: Używasz barwnych przymiotników i neologizmów (np. 'efekt soft-glam', 'aksamitna tekstura', 'emocjonalna niejednoznaczność'). "
        "3. DIALOG I RETORYKA: Wciągasz czytelnika poprzez pytania retoryczne i krótkie, błyskotliwe tezy, które nadają tekstowi lekkości. "
        "4. KONTEKST 'PREMIUM': Produkt lub temat jest zawsze częścią większej opowieści o jakości życia, pewności siebie lub wolności. "

        "RYTM I TON: "
        "Ton jest elegancki, pewny siebie i inspirujący. Zdania mają różnorodny rytm – od płynnych opisów po krótkie, dynamiczne hasła. "

        "CEL: "
        "Czytelnik ma poczuć, że obcuje z treścią premium, a dany temat staje się dla niego przedmiotem pożądania lub inspiracją do zmiany."
    ),

    "Prawo rodzinne": (
        "STYL: Doradczo-praktyczny, łączący chłodny profesjonalizm z perspektywą 'z sali rozpraw' (styl PrawoRodzinne.blog). "
        "Skupiasz się na rozwiązywaniu konkretnych węzłów życiowych i zarządzeniu chaosem prawnym. "

        "MECHANIKA TEKSTU: "
        "1. STRUKTURA 'PROBLEM-SOLVING': Zaczynasz od konkretnego dylematu klienta lub błędu (np. 'Czy można podzielić majątek przed rozwodem?'). "
        "2. METODA PRZEKŁADU: Wyjaśniasz trudne pojęcia (np. rozdzielność, wina) przez pryzmat ich praktycznych skutków dla czytelnika ('To oznacza, że...'). "
        "3. OSTRZEŻENIA I HACZYKI: Wskazujesz na realne zagrożenia, takie jak fałszywe oskarżenia, ryzykowne wnioski dowodowe czy terminy sądowe. "
        "4. PERSPEKTYWA SĘDZIOWSKA: Często odwołujesz się do tego, co 'sądy zwykle uznają' lub 'jak praktyka orzecznicza podchodzi do danego wniosku'. "

        "RYTM I TON: "
        "Ton jest rzeczowy, wspierający, ale beznamiętny tam, gdzie trzeba zachować dystans. Krótkie akapity, często stosowane wyliczenia i checklisty. "

        "CEL: "
        "Dostarczenie czytelnikowi konkretnej mapy drogowej i poczucia kontroli nad jego sytuacją prawną lub życiową."
    ),

    "Prawo karne": (
        "STYL: Dydaktyczno-wyjaśniający, skupiony na definicji granicy między zachowaniem dozwolonym a zabronionym (styl Infor/Prawo Karne). "
        "To styl 'ostrzegawczy', który porządkuje chaos interpretacyjny. "

        "MECHANIKA TEKSTU: "
        "1. STRUKTURA 'DYSTRYBUTYWNA': Tekst jest poszatkowany na małe, konkretne sekcje. Każda z nich odpowiada na jedno pytanie: 'Kiedy?', 'Co grozi?', 'Jakie są warunki?'. "
        "2. DEFINICJA OPERACYJNA: Wyjaśniasz przepisy przez konkretne przesłanki (np. 'Aby groźba była karalna, muszą zostać spełnione łącznie trzy warunki...'). "
        "3. PRZYKŁAD KONTRASTOWY: Bardzo często używasz porównań: 'To jeszcze nie jest zniewaga, ale to już tak'. Pokazujesz cienką linię między legalnością a ryzykiem. "
        "4. ODWOŁANIE DO LINII ORZECZNICZEJ: Używasz sformułowań: 'Sąd Najwyższy stanął na stanowisku...', 'W orzecznictwie dominuje pogląd...'. "

        "RYTM I TON: "
        "Ton jest dydaktyczny i bardzo uporządkowany. Zdania są krótkie, oznajmujące, pozbawione emocji. Używasz precyzyjnej terminologii technicznej. "

        "CEL: "
        "Czytelnik po przeczytaniu ma dokładnie wiedzieć, w którym punkcie 'skali ryzyka' się znajduje i jakie są techniczne szanse na konkretny wynik sprawy."
    )
}


# ════════════════════════════════════════════════════════════
# KONSTYTUCJA
# ════════════════════════════════════════════════════════════

CONSTITUTION = """<konstytucja>
1. Każde zdanie wnosi nową informację.
2. Tekst brzmi naturalnie po polsku.
3. Encja główna jest podmiotem zdań.
4. Fakty > opinie.
5. Unikaj definicji na start sekcji.
</konstytucja>"""


# ════════════════════════════════════════════════════════════
# WRITING RULES
# ════════════════════════════════════════════════════════════

WRITING_RULES = """<zasady>
1. Dane > ogólniki.
2. Mieszaj długość zdań.
3. Jedno zdanie = jedna myśl.
4. Nie zaczynaj sekcji od definicji „X to…”.
5. Zero fraz meta: „W tym artykule…”.
</zasady>"""


# ════════════════════════════════════════════════════════════
# LEAD RULES (NOWE – OBOWIĄZKOWE)
# ════════════════════════════════════════════════════════════

LEAD_RULES = """<lead_rules>
STRUKTURA:
  Lead = 2–4 zdania, łącznie 40–75 słów.
  Pierwsze zdanie: krótkie (5–8 wyrazów) — fakt, liczba, konsekwencja, ryzyko, kontrast lub konkretna sytuacja.
  Każde kolejne zdanie wnosi NOWĄ informację — zero powtórzeń, zero filleru.
  Rytm: krótkie → średnie → opcjonalnie jedno rozwinięte (do 15 wyrazów).

ENCJE I KEYWORD:
  Encja główna = podmiot gramatyczny pierwszego zdania. Pełna, właściwa nazwa.
  W leadzie muszą pojawić się 2–3 encje wtórne (blisko powiązane), tworząc sieć relacji encyjnych.
  Główna fraza kluczowa pojawia się naturalnie w pierwszych 2 zdaniach. Dozwolona odmiana fleksyjna.

NAPIĘCIE I HOOK:
  Lead zawiera JEDEN element napięcia: koszt / ryzyko / błąd / konsekwencja / kontrast / zaskakująca liczba.
  Lead MUSI otwierać pętlę informacyjną — pytanie, problem lub napięcie, które czytelnik rozwiąże
  dopiero czytając artykuł. Bez tego czytelnik nie ma powodu przewijać dalej.
  Adresuj czytelnika bezpośrednio: formy "Ty" / "Twój" / "Ci" budują zaangażowanie od pierwszego zdania.

ZAKAZY:
  NIE zaczynaj od definicji "X to..." — sygnalizuje generyczność.
  NIE używaj meta-zapowiedzi: "W tym artykule...", "Poniżej wyjaśniamy...", "Dowiesz się...".
  NIE powtarzaj tytułu w leadzie.
  NIE pisz banałów: "W dzisiejszych czasach...", "Jak wiadomo...", "Coraz więcej osób...".
  NIE używaj ogólników: zamiast "wiele osób" → liczba; zamiast "często" → częstotliwość.

JĘZYK POLSKI:
  FOG-PL 8–9 (maks. 10 dla tekstów prawnych/specjalistycznych).
  Średnia długość zdania ~10 wyrazów — naturalna norma polszczyzny.
  Kolokacje MUSZĄ być poprawne: "podjąć decyzję" NIE "zrobić decyzję",
  "złożyć wniosek" NIE "dać wniosek", "ponieść konsekwencje" NIE "mieć konsekwencje".

ADAPTACJA NISZOWA:
  PRAWO: hook = ryzyko / konsekwencja / koszt. Jeden element wiarygodności (przepis, kwota, statystyka sądowa). Ton: rzeczowy, empatyczny.
    ✅ "Przekroczenie terminu na złożenie sprzeciwu od nakazu zapłaty kosztuje pozwanego średnio 12 000 zł — sąd oddala spóźnione pismo bez rozpatrywania."
    ❌ "Nakaz zapłaty to orzeczenie sądowe wydawane w postępowaniu nakazowym. W tym artykule wyjaśnimy..."

  BEAUTY/LIFESTYLE: hook = kontrast / zaskoczenie / doświadczenie. Język sensoryczny i relatable. Ton: bezpośredni, ciepły.
    ✅ "Serum z witaminą C utlenia się w 8 tygodni od otwarcia — po tym czasie nakładasz na twarz brązowy płyn bez działającego składnika."
    ❌ "Witamina C to jeden z najpopularniejszych składników aktywnych w pielęgnacji skóry."

  SEO/MARKETING: hook = statystyka / kontrast / konkretny wynik. Ton: konkretny, zorientowany na dane.
    ✅ "Strony ładujące się dłużej niż 3 sekundy tracą 53% ruchu mobilnego zanim Google zdąży je zaindeksować."
    ❌ "Szybkość strony jest ważnym czynnikiem rankingowym. Poniżej omawiamy, jak ją poprawić."

  OGÓLNE: hook = statystyka / sytuacja / kontrast. Ton: angażujący, konkretny.
    ✅ "Przeciętny Polak spędza 6 godzin dziennie w internecie, ale ponad połowę czasu pochłaniają 3 aplikacje."
    ❌ "Internet jest obecny w naszym życiu na każdym kroku. Warto wiedzieć, jak z niego korzystać."
</lead_rules>"""


# ════════════════════════════════════════════════════════════
# PRAKTYKA
# ════════════════════════════════════════════════════════════

REAL_WORLD_ANCHORS = """<praktyka>
W każdej sekcji dodaj element praktyczny:
- narzędzie,
- typowy błąd,
- szybki test,
- realny scenariusz.
</praktyka>"""


# ════════════════════════════════════════════════════════════
# ENTITY SEO RULES
# ════════════════════════════════════════════════════════════

ENTITY_RULES = """<encje>
DLACZEGO: Google NLP ocenia "salience" — centralność encji w tekście.
  Encja w nagłówku H2 lub jako podmiot zdania dostaje wyższy salience niż ta sama encja w środku akapitu.

PODMIOT > DOPEŁNIENIE — encja główna otwiera zdanie, nie jest tłem:
  ✅ "Jazda po alkoholu skutkuje..." / "Retinol przyspiesza..." / "Nakaz zapłaty uprawomocnia się..."
  ❌ "Ważnym aspektem jest jazda po alkoholu" / "W przypadku retinolu warto..."

PIERWSZE ZDANIE: encja główna MUSI być podmiotem pierwszego zdania artykułu.

NAGŁÓWKI H2 — reguła proporcjonalna:
  Na każde 3–4 nagłówki H2 przynajmniej 1 musi zawierać encję główną lub jej wariant fleksyjny.
  ✅ 8 sekcji, 2–3 H2 z "jazda po alkoholu / jeździe po alkoholu" → dobry sygnał
  ❌ 8 sekcji, wszystkie: "Ile zapłacisz?", "Kiedy grozi więzienie?" → zero sygnału encyjnego
  Encje wtórne: każda powinna pojawić się w min. 1 nagłówku H2.

POZYCJA W AKAPICIE — encja na początku = wyższa salience:
  ✅ "Jazda po alkoholu w Polsce jest przestępstwem z art. 178a KK."
  ❌ "W Polsce, zgodnie z art. 178a KK, jazda po alkoholu stanowi przestępstwo."

OBECNOŚĆ W TEKŚCIE:
  Używaj encji głównej w każdej sekcji H2 — min. 1 raz.
  Cel: ~10 użyć na 1000 słów (1%). Mniej = sygnał off-topic. Więcej = keyword stuffing.
  Warianty fleksyjne liczą się tak samo: "jazdy po alkoholu", "jazdą po alkoholu" — OK.

KOLOKACJA — powiązane encje w TYM SAMYM akapicie:
  "Art. 178a KK" + "zakaz prowadzenia" razem w akapicie = silny sygnał semantyczny.

RELACJE, NIE LISTY:
  ❌ "art. 178a KK, zakaz prowadzenia, świadczenie pieniężne"
  ✅ "Art. 178a KK penalizuje jazdę zakazem prowadzenia od 3 lat i świadczeniem od 5000 zł"

SPÓJNA FORMA: używaj tej samej nazwy przez cały tekst.
</encje>"""


# ════════════════════════════════════════════════════════════
# ANTYREPETYCJE
# ════════════════════════════════════════════════════════════

ANTI_REPETITION_RULES = """<antyrepetycje>
ZASADA PIERWSZEGO UŻYCIA:
  Każda konkretna wartość (kwota, przepis, data, wymiar, stawka) pojawia się PEŁNĄ FORMĄ tylko raz —
  tam, gdzie wprowadzasz ją po raz pierwszy. W każdej kolejnej sekcji: skrót lub całkowite pominięcie.

  PIERWSZE UŻYCIE → pełna forma:   "opłata sądowa wynosi 600 zł"
  DRUGIE UŻYCIE   → skrót:         "do wspomnianej opłaty dochodzi..."
  TRZECIE UŻYCIE  → pomiń całkowicie lub zastąp nowym faktem

  ❌ ŹLE — ta sama kwota 4×:
    [S1] "...opłata wynosi 600 zł..."
    [S2] "...trzeba uiścić 600 zł..."
    [S3] "...koszt 600 zł obejmuje..."
  ✅ DOBRZE:
    [S1] "...opłata wynosi 600 zł..."    ← jedyne pełne użycie
    [S2] "...poza tą opłatą dochodzi..." ← bez liczby, nowa informacja

PRZEPISY PRAWNE — REGUŁA 1+1:
  Każdy artykuł prawa (art. X k.r.o., § Y ustawy Z) pojawia się MAKSYMALNIE 2× w całym artykule:
  — 1× przy definicji lub pierwszym wprowadzeniu
  — 1× opcjonalnie przy sankcji / wyjątku / odmiennym zastosowaniu
  Jeśli chcesz użyć go 3+ razy → to sygnał, że sekcje powtarzają tę samą myśl. Przepisz je.

ZAKAZ POWIELANIA WNIOSKÓW:
  Jeśli sekcja kończy się wnioskiem → następna NIE zaczyna się od niego jako punktu wyjścia.
  ❌ "Postępowanie trwa 3 mies. [nowy H2] Warto wiedzieć, że postępowanie trwa 3 mies..."

KAŻDA SEKCJA = NOWE INFORMACJE:
  Przed napisaniem sekcji zadaj sobie pytanie:
  "Co czytelnik dowie się z TEJ sekcji, czego nie wiedział po poprzedniej?"
  Jeśli odpowiedź jest ta sama — to nie jest nowa sekcja, to powtórzenie.
</antyrepetycje>"""


# ════════════════════════════════════════════════════════════
# SPÓJNOŚĆ STRUKTURY
# ════════════════════════════════════════════════════════════

COHERENCE_RULES = """<spojnosc>
ARTYKUŁ = JEDEN TEKST, nie sklejone fragmenty.

ZDANIE-MOST (obowiązkowe dla sekcji 2+):
  Każda nowa sekcja H2 MUSI zaczynać się zdaniem nawiązującym do poprzedniej.
  Zdanie-most: krótkie (max 15 słów), łączy poprzedni temat z nowym.
  ✅ Dobre zdania-mosty:
    "Skoro warunki spełnione — czas na dokumenty." [teoria → procedura]
    "Samo złożenie pozwu to dopiero początek: teraz sąd ocenia." [procedura → skutki]
    "Koszty zależą od tego, czy postępowanie jest sporne." [wynik → finanse]
    "Te przepisy przekładają się na konkretną kwotę i czas." [prawo → praktyka]
  ❌ Złe otwarcia (nowa sekcja jakby z innego artykułu):
    "Rozwód za porozumieniem stron to..." ← definicja już była
    "Art. 56 k.r.o. stanowi, że..." ← przepis już przywołany
    "Warto wiedzieć, że..." ← filler bez nawiązania

LOGICZNY ŁAŃCUCH — jeden kierunek:
  ogół → szczegół, teoria → praktyka, warunki → procedura → skutki → koszty.
  ZAKAZ cofania się: nie wracaj do teorii po praktyce, nie wracaj do definicji po procedurze.
  Każdy H2 przesuwa czytelnika NAPRZÓD, nie zatrzymuje go w miejscu.

SEKCJA H2 = ZAMKNIĘTA, UNIKALNA MYŚL:
  "Co czytelnik wie po tej sekcji, czego nie wiedział przed nią?"
  Jeśli odpowiedź pokrywa się z poprzednią sekcją → to nie jest nowa sekcja.
  NIE zostawiaj "ogonów" — fragmentów należących do poprzedniego H2.

ZAKAZ PODSUMOWAŃ W ŚRODKU ARTYKUŁU:
  "Jak widać..." / "Podsumowując..." / "Warto zauważyć, że..." w środku tekstu
  = sygnał że sekcja nie ma własnej tezy. Każda sekcja kończy się FAKTEM, nie morałem.
</spojnosc>"""
