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
  2. Sprawdź: zero fraz AI, encja jako podmiot, min. 2 liczby
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
            "Za jazdę pod wpływem alkoholu z art. 178a § 1 k.k. grozi kara pozbawienia "
            "wolności do lat 2. W praktyce sądy najczęściej orzekają grzywnę — od 5 000 "
            "do 15 000 zł — połączoną z zakazem prowadzenia na 3 lata. Recydywa zmienia "
            "obraz radykalnie: drugie skazanie to bezwzględne więzienie i zakaz na minimum "
            "6 lat. Sąd nakłada też świadczenie pieniężne na rzecz Funduszu Pomocy "
            "Pokrzywdzonym, zwykle 5 000–60 000 zł."
        ),
        (
            "Odmowa poddania się badaniu alkomatem to osobne wykroczenie. Konsekwencja? "
            "Sąd traktuje odmowę jak przyznanie się — a kara bywa surowsza niż przy "
            "współpracy z policją. Przeciętny kierowca zatrzymany po raz pierwszy "
            "z wynikiem 0,6 promila zapłaci grzywnę i straci prawo jazdy na 3 lata. Ale "
            "ten sam kierowca odmawiający dmuchania ryzykuje wyrok skazujący bez zawieszenia."
        ),
        (
            "Granica między wykroczeniem a przestępstwem przebiega przy 0,5 promila we krwi. "
            "Poniżej — art. 87 Kodeksu wykroczeń: grzywna do 5 000 zł i zakaz prowadzenia "
            "od 6 miesięcy do 3 lat. Powyżej — art. 178a k.k.: kara pozbawienia wolności "
            "do 2 lat, zakaz od 3 do 15 lat i świadczenie pieniężne. Różnica kilku "
            "setnych promila oznacza przeskok z mandatu na sprawę karną z wpisem do "
            "Krajowego Rejestru Karnego."
        ),
    ],

    # ── MEDYCYNA ──
    "medycyna": [
        (
            "Ibuprofen w dawce 400 mg łagodzi ból w ciągu 30–60 minut. Działanie utrzymuje "
            "się przez 6–8 godzin. Przekroczenie 1 200 mg na dobę zwiększa ryzyko krwawienia "
            "z przewodu pokarmowego — szczególnie u osób po 65. roku życia. Alternatywą jest "
            "paracetamol: słabszy przeciwzapalnie, ale bezpieczniejszy dla żołądka."
        ),
        (
            "Retinol przyspiesza odnowę komórkową naskórka. Pierwsze efekty — wygładzenie "
            "drobnych zmarszczek — pojawiają się po 8–12 tygodniach regularnego stosowania. "
            "Stężenie 0,3 % wystarczy na początek; skóra wrażliwa toleruje je bez "
            "podrażnień. Wyższe stężenia (0,5–1,0 %) wymagają stopniowego wprowadzania: "
            "co drugi wieczór przez 2 tygodnie, potem codziennie."
        ),
        (
            "Kwas hialuronowy o masie cząsteczkowej poniżej 50 kDa przenika w głąb "
            "naskórka i wiąże tam cząsteczki wody. Efekt? Skóra wygładzona od wewnątrz, "
            "nie tylko pokryta filmem okluzyjnym. Frakcja wysoko-cząsteczkowa (powyżej "
            "1 000 kDa) działa powierzchniowo — tworzy barierę ograniczającą TEWL. "
            "Serum łączące obie frakcje daje najlepsze rezultaty."
        ),
    ],

    # ── BUDOWNICTWO ──
    "budownictwo": [
        (
            "Panele laminowane z montażem: 50–150 zł/m². Salon 30 m² to 1 500–4 500 zł "
            "za samą podłogę plus 300–500 zł na listwy i podkłady. Deska warstwowa "
            "wychodzi drożej — 120–250 zł/m² — ale nie wymaga cyklinowania przez "
            "10–15 lat. Najtańsza opcja? Wykładzina PCV: 25–60 zł/m², montaż w jeden dzień."
        ),
        (
            "Ocieplenie ścian styropianem grafitowym o grubości 15 cm kosztuje 180–250 zł/m² "
            "z robocizną. Dla domu o powierzchni elewacji 200 m² to 36 000–50 000 zł. "
            "Wełna mineralna jest droższa o 20–30 %, ale przepuszcza parę wodną — "
            "lepszy wybór przy ścianach z ceramiki poryzowanej. Czas realizacji: "
            "3–5 tygodni, zależnie od pogody i dostępności ekipy."
        ),
        (
            "Łazienka 8 m² w standardzie średnim zamyka się w 15 000–25 000 zł. "
            "Największa pozycja to płytki z montażem: 90–140 zł/m² za gres rektyfikowany, "
            "plus 80–120 zł/m² za robociznę. Armatura od Grohe lub Hansgrohe zaczyna się "
            "od 1 500 zł za komplet (bateria umywalkowa + prysznicowa). Tańsze zamienniki "
            "z Cersanit — od 400 zł."
        ),
    ],

    # ── FINANSE ──
    "finanse": [
        (
            "Kredyt hipoteczny na 300 000 zł przy oprocentowaniu 7,5 % daje ratę "
            "ok. 2 100 zł miesięcznie (raty równe, 25 lat). Łączny koszt odsetek: "
            "ponad 330 000 zł — więcej niż sam kredyt. Obniżenie marży o 0,3 p.p. "
            "(np. z 2,1 % na 1,8 %) to oszczędność ok. 18 000 zł przez cały okres "
            "spłaty. Warto negocjować — banki mają na to budżet."
        ),
        (
            "Lokata 6-miesięczna w największych bankach oferuje 4,5–5,5 % w skali roku. "
            "Przy 50 000 zł to 1 125–1 375 zł brutto odsetek. Po potrąceniu 19 % "
            "podatku Belki zostaje 911–1 113 zł netto. Konto oszczędnościowe daje mniej "
            "— 3,0–4,0 % — ale pieniądze są dostępne od ręki, bez zrywania."
        ),
    ],

    # ── TECHNOLOGIA ──
    "technologia": [
        (
            "Wi-Fi 7 (IEEE 802.11be) osiąga teoretyczną przepustowość 46 Gbps — "
            "4,8× więcej niż Wi-Fi 6. W praktyce oznacza to stabilny streaming 8K "
            "na 3 urządzeniach jednocześnie, bez buforowania. Kanały 320 MHz "
            "podwajają pasmo w porównaniu z Wi-Fi 6 (160 MHz). Pierwsze routery "
            "z certyfikatem Wi-Fi 7 kosztują od 1 200 zł."
        ),
        (
            "Chip Apple M4 Pro wykorzystuje 3-nanometrowy proces TSMC drugiej "
            "generacji. Względem M3 Pro to 20 % więcej wydajności CPU przy tym samym "
            "poborze mocy — albo identyczna wydajność przy 25 % niższym zużyciu energii. "
            "Przekłada się to na 22 godziny odtwarzania wideo na jednym ładowaniu "
            "w MacBooku Pro 14."
        ),
    ],

    # ── URODA ──
    "uroda": [
        (
            "Ceramidy odbudowują barierę lipidową naskórka, ograniczając TEWL "
            "(transepidermalną utratę wody). Efekt widoczny po 2–4 tygodniach: "
            "mniej ściągania, mniej zaczerwienień. Krem z ceramidami 1, 3 i 6-II "
            "w stężeniu łącznym 3–5 % pokrywa potrzeby większości typów skóry. "
            "Skóra atopowa wymaga wyższego stężenia — 5–8 %."
        ),
        (
            "Peeling z kwasem glikolowym 30 % działa na poziomie naskórka — rozpuszcza "
            "wiązania między korneocytami, przyspieszając złuszczanie martwych komórek. "
            "Czas ekspozycji: 3–5 minut przy pierwszym zabiegu, do 10 minut po "
            "3–4 sesjach. Odstęp między zabiegami: 2–4 tygodnie. Efekt: wyrównanie "
            "kolorytu i wygładzenie tekstury po 3 sesjach."
        ),
    ],

    # ── INNE (fallback) ──
    "inne": [
        (
            "Proces trwa 3–4 tygodnie. Pierwszy krok — złożenie wniosku online lub "
            "w placówce. Dokumenty: dowód osobisty, zaświadczenie o dochodach, formularz "
            "A-1. Opłata administracyjna: 17 zł. Decyzja zapada w ciągu 14 dni "
            "roboczych, choć w praktyce bywa szybciej — średnio 8–10 dni."
        ),
        (
            "Rynek rośnie o 12 % rocznie od 2020 roku. Trzy lata temu obroty sięgały "
            "2,3 mld zł — w 2024 przekroczyły 3,6 mld zł. Główny motor: zmiana "
            "przyzwyczajeń konsumentów po pandemii. Prognozy na 2026: wzrost o kolejne "
            "8–10 %, przy czym segment premium rośnie szybciej niż economy."
        ),
    ],
}


# ════════════════════════════════════════════════════════════
# PUBLIC API
# ════════════════════════════════════════════════════════════

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
        f"Zwróć uwagę: krótkie zdania przeplatane dłuższymi. Konkretne liczby. "
        f"Encja jako podmiot. Brak fraz AI. Zdania równoważne. Partykuły.\n"
        f"</styl_wzorcowy>"
    )
