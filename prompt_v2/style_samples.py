"""
═══════════════════════════════════════════════════════════
PROMPT V2 — STYLE SAMPLES (few-shot voice anchoring)
═══════════════════════════════════════════════════════════
Wzorcowe akapity polskiego tekstu per kategoria.
To najsilniejszy sygnał jakościowy dla Claude.

ZASADY:
  • 3-4 akapity per kategoria, ~100-150 słów każdy
  • Napisane przez człowieka lub ręcznie poprawione
  • Demonstrują: naturalny rytm, kolokacje, encje jako podmiot,
    dane liczbowe, brak fraz z listy zakazów
  • Rotowane losowo (2 z 3-4) → zapobiega overfittingowi

JAK DODAWAĆ NOWE PRÓBKI:
  1. Weź najlepszy fragment z artykułu ocenionego na A+
  2. Sprawdź: zero fraz AI, encja jako podmiot, min. 1 konkret (liczba/nazwa/procedura)
  3. Dodaj do listy odpowiedniej kategorii
  4. Max 4 próbki per kategoria (więcej = mniej efektywne)
═══════════════════════════════════════════════════════════
"""

import random
from typing import List, Optional


# ════════════════════════════════════════════════════════════
# SAMPLES PER CATEGORY
# ════════════════════════════════════════════════════════════

_SAMPLES = {

    # ── PRAWO ──
    "prawo": [
        (
            "Pierwsza rozmowa z policją zwykle dzieje się szybko i w stresie. Wtedy padają pytania, na które ludzie odpowiadają odruchowo: „piłem wczoraj”, „to tylko kawałek”, „nie wiem”. Jeśli sprawa dotyczy alkoholu za kółkiem, kluczowy jest wynik badania i to, czy był powtarzany. Protokół powinien mieć godzinę, miejsce i dwie wartości, jeżeli robiono dwa pomiary. Brak tych danych nie uniewinnia, ale daje pole do kwestionowania wiarygodności. W praktyce najwięcej szkody robi nie sam wynik, tylko chaos w papierach."
        ),
        (
            "Gdy sąd orzeka zakaz prowadzenia, pytanie „na ile?” pojawia się zawsze. Zakres jest szeroki: od 3 lat do 15 lat, a w cięższych sprawach nawet dożywotnio. To nie jest losowanie. Na długość wpływa recydywa, stężenie alkoholu, wypadek i to, czy ktoś wcześniej łamał zakazy. Jeśli kierowca pracuje zawodowo, sąd może ograniczyć zakaz do określonych kategorii, ale robi to rzadko i wymaga to mocnego uzasadnienia. Warto mieć dokumenty z pracy, a nie samą prośbę „bo potrzebuję”."
        ),
        (
            "Najczęstszy błąd w pismach to bezosobowe „można złożyć wniosek”. Sąd nie rozpatruje wniosków z powietrza. Składa je konkretna strona, w konkretnym terminie, z konkretnym załącznikiem. Jeśli chodzi o odwołanie, liczysz 14 dni od doręczenia, nie od daty na wyroku. I tu wraca praktyka: odbierasz pismo na poczcie w piątek — termin i tak biegnie. Dlatego pierwsze co robisz po doręczeniu, to zapisujesz datę i robisz skan."
        ),
    ],

    # ── MEDYCYNA ──
    "medycyna": [
        (
            "W aptece pytanie „co na ból?” brzmi prosto, ale różnica zaczyna się w dawce i w ryzyku. Ibuprofen 400 mg działa zwykle w 30–60 minut i trzyma 6–8 godzin, ale u osób z chorobą wrzodową potrafi pogorszyć sytuację już po kilku dniach. Jeśli ktoś bierze leki na nadciśnienie, warto dopytać o interakcje — to nie jest straszenie, tylko praktyka z gabinetu. Paracetamol bywa bezpieczniejszy dla żołądka, ale łatwiej przekroczyć dawkę dobową, gdy łączy się preparaty."
        ),
        (
            "Przy infekcji górnych dróg oddechowych większość objawów mija sama, ale są trzy czerwone flagi, które widzę na dyżurze najczęściej: duszność, wysoka gorączka utrzymująca się >3 dni i ból w klatce piersiowej. To są sygnały, że trzeba zbadać pacjenta, a nie „przeczekać”. W domu sensownie działa prosty plan: nawodnienie, odpoczynek, leki objawowe w odpowiednich dawkach, a jeśli stan się pogarsza — konsultacja. Bez antybiotyku „na zapas”."
        ),
        (
            "Skóra reaguje na retinoidy przewidywalnie: najpierw podrażnienie, potem adaptacja. Jeśli ktoś startuje od zbyt wysokiego stężenia i nakłada codziennie, kończy z pieczeniem i łuszczeniem. Bez magii. Bez „złego produktu”. W praktyce lepsze efekty daje start 2× w tygodniu, cienka warstwa i nawilżacz po 10–15 minutach. Gdy pojawia się rumień, robi się przerwę na kilka dni i wraca wolniej. To jest proces, nie sprint."
        ),
    ],

    # ── BUDOWNICTWO ──
    "budownictwo": [
        (
            "Najwięcej pieniędzy ucieka nie na materiałach, tylko na „drobiazgach”, których nie policzysz w głowie. Weź łazienkę 6 m². Płytki to jedno, ale dochodzi klej, fuga, hydroizolacja, listwy, docinki. Na robociźnie różnica między prostym układem a wzorem w jodełkę potrafi wynieść 40–60 zł/m². Jeśli budżet jest napięty, zacznij od decyzji: gdzie ma być efekt, a gdzie ma być łatwo w montażu. Potem dopiero wybieraj płytkę. Inaczej skończysz z pięknym projektem i wyceną, która boli."
        ),
        (
            "Przed wylaniem wylewki zrób jeden pomiar, który oszczędza tydzień reklamacji: wilgotność podkładu. Nie „na oko”. Miernikiem. Dla większości okładzin granica kręci się wokół 2% CM, a przy drewnie jeszcze niżej. Gdy podkład jest mokry, panel zaczyna pracować, a listwy odchodzą po miesiącu. Wtedy winny jest nie materiał, tylko harmonogram. Lepiej poczekać 7–10 dni niż poprawiać całość."
        ),
        (
            "Na papierze ocieplenie ściany to „X cm wełny”. Na budowie różnicę robi detal: ościeża, nadproża, łączenie z dachem. Tam właśnie uciekają mostki. Najprostsza kontrola po wykonaniu: kamera termowizyjna wieczorem albo zwykły test dłonią przy mrozie — czujesz zimny pas, masz problem. Jeżeli ekipa tnie płyty „na styk” bez piany i taśm, to rachunek za ogrzewanie rośnie, nawet gdy grubość izolacji się zgadza."
        ),
    ],

    # ── FINANSE ──
    "finanse": [
        (
            "Najbardziej mylący moment przy kredycie to dzień, w którym bank pokazuje „zdolność” jako jedną liczbę. W praktyce liczą się dwa progi: rata, którą zniesie budżet, i bufor na gorszy miesiąc. Weź prosty wariant: 300 000 zł na 25 lat. Różnica między 6,5% a 7,5% to około 180–220 zł miesięcznie. To nie jest abstrakcja — to jeden rachunek albo tydzień zakupów. Zanim podpiszesz umowę, policz ratę w trzech scenariuszach: dziś, +1 pp, +2 pp. Jeśli w scenariuszu +2 pp zaczyna brakować na życie, to sygnał ostrzegawczy."
        ),
        (
            "Lokata „na 8%” brzmi dobrze dopóki nie zobaczysz warunków: limit kwoty, nowe środki, konto w pakiecie. W praktyce najlepsze oferty są krótkie — 3 miesiące — i służą do pozyskania klienta. Zrób checklistę jak w banku: ile możesz wpłacić, na ile zamrażasz, czy musisz wykonać płatności kartą. Jeżeli warunek to 5 transakcji miesięcznie, policz, czy i tak je robisz. Jeśli nie, realne oprocentowanie spada, bo do gry wchodzi opłata za konto."
        ),
        (
            "Podatek od zysku kapitałowego zabiera 19% i działa automatycznie, więc łatwo go zignorować. A potem dziwią rozjazdy w kalkulatorze. Jeśli inwestujesz 10 000 zł i zarabiasz 1 000 zł, to do ręki zostaje 810 zł. Prosta zasada planowania: cele krótkie trzymaj w produktach z mniejszą zmiennością, bo podatek i tak zje część zysku, a strata boli podwójnie. Na długim horyzoncie ważniejsze jest, żeby nie sprzedawać w panice, niż żeby polować na najwyższy procent na start."
        ),
    ],

    # ── TECHNOLOGIA ──
    "technologia": [
        (
            "Specyfikacja wygląda świetnie dopiero do momentu, gdy odpalisz test w realnym scenariuszu. Laptop z szybkim dyskiem i 16 GB RAM potrafi i tak „chrupnąć”, jeśli system zjada pamięć w tle, a przeglądarka ma 30 kart. Zrób prosty pomiar: uruchom projekt, skompiluj, a potem zrób eksport — zmierz czas w minutach, nie w punktach z benchmarku. Jeżeli różnica między trybem zasilania „wydajność” i „zrównoważony” wynosi 15–20%, to wiesz, gdzie uciekają waty. Parametry są ważne, ale decyzję podejmuj po teście, nie po tabelce."
        ),
        (
            "Przy wyborze routera liczby z pudełka kłamią z definicji, bo łączą kilka pasm i idealne warunki. W mieszkaniu liczy się, czy sygnał przechodzi przez dwie ściany i czy stabilnie trzyma 200–300 Mb/s w drugim pokoju. Zrób mapę zasięgu: trzy punkty pomiarowe, dwa pomiary na punkcie, ten sam kanał. Jeśli widzisz spadki co kilka minut, to nie „internet”, tylko zakłócenia i automatyczna zmiana kanału. Wtedy pomaga ręczne ustawienie kanału albo przeniesienie routera o 1–2 m — brzmi banalnie, działa."
        ),
        (
            "Zanim wymienisz telefon „bo ma słaby aparat”, sprawdź, co naprawdę psuje zdjęcie: drganie, zbyt długi czas naświetlania, agresywne odszumianie. Zrób serię 10 kadrów w tym samym świetle i porównaj ostrość w rogach. Jeśli 7/10 jest miękkich, winny bywa stabilizator albo algorytm, nie matryca. W praktyce lepszy efekt daje ręczne doświetlenie sceny małą lampą i krótszy czas, niż pogoń za kolejnym megapikselem."
        ),
    ],

    # ── URODA ──
    "uroda": [
        (
            "Najczęściej psuje pielęgnację nie brak składników, tylko brak konsekwencji. Jeżeli skóra ściąga po myciu, problem zwykle siedzi w barierze hydrolipidowej, nie w „niedoborze kwasu”. Wtedy działają proste rzeczy: łagodny środek myjący, ceramidy i ochrona przed słońcem. Retinoid można dołożyć później. Gdy ktoś zmienia kosmetyk co tydzień, skóra nie ma kiedy się uspokoić, a podrażnienie rośnie i wygląda jak „reakcja na wszystko”."
        ),
        (
            "Przy witaminie C większość rozczarowań wynika z formy i przechowywania. Serum może mieć 15%, ale jeśli stoi w łazience i ciemnieje, aktywność spada. Prosty test: kolor. Jasny — ok, bursztynowy — czas na wymianę. Dla wrażliwej skóry lepiej zacząć od niższego stężenia i aplikacji co drugi dzień, niż od „mocnego” produktu, który kończy w szufladzie. Efekt widać po 6–8 tygodniach regularności, nie po trzech dniach."
        ),
        (
            "Jeśli produkt „piecze”, to nie zawsze znaczy, że działa. Pieczenie po kwasach bywa sygnałem, że bariera jest już uszkodzona. W takiej sytuacji dokładanie kolejnego aktywnego składnika pogarsza sprawę. Praktyczny plan naprawczy na 7 dni: mycie raz dziennie, krem z ceramidami, filtr SPF rano, zero peelingów. Dopiero po tygodniu wracasz do aktywów, ale rzadziej. Skóra lubi nudę."
        ),
    ],

    # ── INNE ──
    "inne": [
        (
            "Na stole leży próbny wydruk na niepowlekanym papierze 90 g/m². Dopiero tutaj widać, że akapit „pływa” — raz mieści 68 znaków w wierszu, raz 76. W pliku wyglądało równo. Na papierze już nie. Najszybszy test: przyłóż kartkę pod lampę z boku i sprawdź, czy między wyrazami nie układają się jasne „rzeki”. Jeśli są, masz dwa ruchy: zwęzić kolumnę o 2–3 mm albo podnieść interlinię z 12 do 13,5 pt. Nie zmieniaj fontu w panice. Zrób jedną korektę, drukuj próbkę, dopiero potem kolejną."
        ),
        (
            "Drukarnia tnie arkusz z tolerancją. To nie jest teoria — przy naklejkach i ulotkach potrafi „uciec” 1 mm bez żadnego alarmu na maszynie. Dlatego drobny tekst 8–9 pt nie może stać przy krawędzi. Zostaw 5 mm marginesu bezpieczeństwa i 3 mm spadu. Prosty trik z prepressu: ustaw cienką ramkę pomocniczą na 5 mm od brzegu i traktuj ją jak ścianę. Jeśli litera ją dotyka, przenieś blok. Na proofie oszczędzasz godzinę nerwów."
        ),
        (
            "Jeśli skład idzie do druku wypukłego, papier nagle zaczyna być częścią projektu. Karton 350 g/m² przyjmie docisk, ale cienkie szeryfy w 7 pt potrafią się „zalać” farbą i zniknąć. Zanim zamówisz nakład, odbij jeden arkusz na docelowym papierze i obejrzyj litery lupą. Krawędź znaku powinna być czysta, bez rozlania na zewnątrz. Gdy widzisz przyrost punktu, poszerz światło liter albo podnieś stopień o 0,5–1 pt. To drobiazg, który w gotowym zaproszeniu robi różnicę."
        ),
    ],

}


def get_samples(category: str, count: int = 2, seed: Optional[int] = None) -> List[str]:
    """
    Return `count` random style samples for given category.
    Uses seed for reproducibility (e.g. batch_number) to avoid
    same samples in consecutive batches of one article.
    """
    pool = _SAMPLES.get(category, _SAMPLES["inne"])
    count = min(count, len(pool))

    if seed is not None:
        rng = random.Random(seed)
        return rng.sample(pool, count)
    return random.sample(pool, count)


def format_samples_block(category: str, count: int = 2, seed: Optional[int] = None) -> str:
    """
    Format style samples as a prompt block ready to inject.
    """
    samples = get_samples(category, count, seed)
    samples_text = "\n\n".join(samples)
    return (
        f"<styl_wzorcowy>\n"
        f"Wzoruj się na stylu tych akapitów — rytm, kolokacje, konkretność:\n\n"
        f"{samples_text}\n\n"
        f"Zwróć uwagę: krótkie zdania przeplatane dłuższymi. Konkret (liczby, procedury, testy). "
        f"Encja jako podmiot. Brak fraz AI. Zdania równoważne. Partykuły.\n"
        f"</styl_wzorcowy>"
    )
