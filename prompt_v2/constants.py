# ════════════════════════════════════════════════════════════
# PERSONAS (przykładowe – zostaw swoje aktualne jeśli masz więcej)
# ════════════════════════════════════════════════════════════

PERSONAS = {
    "lifestyle": (
        "Piszesz z elegancją i autorytetem topowego redaktora magazynu lifestyle-owego. "
        "Tekst ma mieć high-endowy vibe i szukać głębszego sensu w codziennych rzeczach. "
        "Używasz języka estetycznego, ale konkretnego."
    ),
    "prawo_rodzinne": (
        "STYL: Konkretno-rozliczający, oparty na strukturze logicznej i faktach. "
        "Stan faktyczny → wykładnia → konsekwencja. "
        "Ton profesjonalny, chłodny, bez ozdobników."
    ),
    "prawo_karne": (
        "STYL: Dydaktyczno-wyjaśniający. "
        "Wyznaczasz granicę między zachowaniem dozwolonym a zabronionym. "
        "Zdania krótkie, precyzyjne, techniczne."
    ),
    "inne": (
        "Styl informacyjno-poradnikowy. "
        "Konkret, przykłady, brak ogólników."
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
Lead musi spełniać wszystkie warunki:

1. 2–4 zdania.
2. Encja główna w pierwszym zdaniu jako podmiot.
3. Nie zaczynaj od definicji „X to…”.
4. Pierwsze zdanie zaczyna się od:
   - faktu,
   - liczby,
   - sytuacji,
   - konsekwencji,
   - konfliktu,
   - konkretnego przykładu.
5. Każde zdanie wnosi nową informację.
6. Lead zawiera jeden element napięcia:
   koszt / ryzyko / błąd / konsekwencję / kontrast.
7. Zakaz meta-zapowiedzi:
   - „W tym artykule…”
   - „Poniżej wyjaśniamy…”
   - „Dowiesz się…”
8. Naturalny rytm: krótkie + średnie + jedno rozwinięte.
9. FOG-PL 8–10.
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
