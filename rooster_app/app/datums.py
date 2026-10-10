"""Datums zoals MyManus ze stuurt, en de weken die we daarvoor ophalen.

Het rooster antwoordt met dagnummers, geen kalenderdatums. 46303 is
10 oktober 2026 — dat is nagemeten aan de weekdagen in het rooster én aan de
ISO-tijden die naast hetzelfde verlof staan. Het Excel-nulpunt van
30 december 1899, dat je vaak als uitleg hoort, ligt twee dagen eerder en
zet 46303 op 8 oktober. Daarom rekenen we vanaf 1 januari 1900.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

# 1 januari 1900 + het serienummer. Zie de toelichting hierboven.
EPOCH = date(1900, 1, 1)

MAANDNAMEN = [
    "",
    "januari",
    "februari",
    "maart",
    "april",
    "mei",
    "juni",
    "juli",
    "augustus",
    "september",
    "oktober",
    "november",
    "december",
]

WEEKDAGEN = [
    "maandag",
    "dinsdag",
    "woensdag",
    "donderdag",
    "vrijdag",
    "zaterdag",
    "zondag",
]


def excel_naar_datum(serienummer) -> date | None:
    """Een MyManus-dagnummer naar een datum. Onbruikbare invoer wordt None."""
    if serienummer is None or serienummer == "":
        return None
    try:
        dagen = int(serienummer)
    except (TypeError, ValueError):
        return None
    # Negatieve nummers en het Lotus-spookdagnummer 60 horen hier niet voor;
    # alles wat we ophalen ligt ver na 1900.
    if dagen < 0 or dagen > 200000:
        return None
    return EPOCH + timedelta(days=dagen)


def datum_naar_excel(dag: date) -> int:
    """Omgekeerde van excel_naar_datum, voor de upcoming-aanroep."""
    return (dag - EPOCH).days


def maandnaam(jaar: int, maand: int) -> str:
    return f"{MAANDNAMEN[maand]} {jaar}"


def maand_sleutel(jaar: int, maand: int) -> str:
    return f"{jaar:04d}-{maand:02d}"


def parse_maand(sleutel: str) -> tuple[int, int] | None:
    try:
        jaar_tekst, maand_tekst = sleutel.split("-", 1)
        jaar, maand = int(jaar_tekst), int(maand_tekst)
    except (ValueError, AttributeError):
        return None
    if maand < 1 or maand > 12:
        return None
    return jaar, maand


def dagen_in_maand(jaar: int, maand: int) -> int:
    return calendar.monthrange(jaar, maand)[1]


def verschuif_maand(jaar: int, maand: int, stap: int) -> tuple[int, int]:
    index = jaar * 12 + (maand - 1) + stap
    return index // 12, index % 12 + 1


def minuten_naar_klok(minuten: int) -> str:
    """Minuten sinds middernacht, zoals het rooster ze geeft, naar 09:00."""
    minuten = int(minuten) % (24 * 60)
    return f"{minuten // 60:02d}:{minuten % 60:02d}"


def klok_naar_minuten(tekst: str) -> int | None:
    try:
        uur, minuut = tekst.strip().split(":")
        totaal = int(uur) * 60 + int(minuut)
    except (ValueError, AttributeError):
        return None
    if totaal < 0 or totaal > 24 * 60:
        return None
    return totaal


def iso_week_dagen(jaar: int, week: int) -> tuple[date, date]:
    """Maandag en zondag van een ISO-week.

    Het weekjaar is niet het kalenderjaar. 1 januari 2021 valt in week 53
    van 2020; de API verwacht dan het weekjaar, anders krijg je een andere
    week terug.
    """
    maandag = date.fromisocalendar(jaar, week, 1)
    return maandag, maandag + timedelta(days=6)


def weken_in_bereik(van: date, tot: date) -> list[tuple[int, int]]:
    """ISO-(jaar, week) die het bereik raken, oplopend en zonder dubbelen."""
    if tot < van:
        return []
    gezien: list[tuple[int, int]] = []
    dag = van
    while dag <= tot:
        iso = dag.isocalendar()
        sleutel = (iso.year, iso.week)
        if not gezien or gezien[-1] != sleutel:
            gezien.append(sleutel)
        dag += timedelta(days=1)
    return gezien


def bereik_rond(vandaag: date, maanden_terug: int = 2, weken_vooruit: int = 5) -> tuple[date, date]:
    """Verleden dat we willen bewaren, en het rooster dat al gepubliceerd is.

    Twee maanden terug is ruim genoeg om een net afgesloten periode nog te
    zien; vijf weken vooruit dekt het rooster dat MyManus meestal al heeft.
    """
    jaar, maand = verschuif_maand(vandaag.year, vandaag.month, -maanden_terug)
    van = date(jaar, maand, 1)
    tot = vandaag + timedelta(weeks=weken_vooruit)
    return van, tot


def pasen(jaar: int) -> date:
    """Eerste paasdag, Gregoriaans.

    De anonieme computus. Hemelvaart en Pinksteren hangen hieraan, en die
    data staan niet als vaste lijst in de cao.
    """
    a = jaar % 19
    b = jaar // 100
    c = jaar % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    maand = (h + l - 7 * m + 114) // 31
    dag = ((h + l - 7 * m + 114) % 31) + 1
    return date(jaar, maand, dag)


def feestdagen(jaar: int) -> set[date]:
    """Feestdagen uit de cao Doe-het-zelfbranche, artikel 2.10.

    Koningsdag schuift naar 26 april als 27 april een zondag is.
    Bevrijdingsdag telt alleen in een lustrumjaar, eens in de vijf jaar.
    """
    eerste_paasdag = pasen(jaar)
    dagen = {
        date(jaar, 1, 1),
        eerste_paasdag,
        eerste_paasdag + timedelta(days=1),
        eerste_paasdag + timedelta(days=39),
        eerste_paasdag + timedelta(days=49),
        eerste_paasdag + timedelta(days=50),
        date(jaar, 12, 25),
        date(jaar, 12, 26),
    }
    koningsdag = date(jaar, 4, 27)
    if koningsdag.weekday() == 6:
        koningsdag = date(jaar, 4, 26)
    dagen.add(koningsdag)
    if jaar % 5 == 0:
        dagen.add(date(jaar, 5, 5))
    return dagen


def maand_uit_periodenaam(naam: str | None, van: date | None, tot: date | None) -> tuple[int, int] | None:
    """Bij welke kalendermaand een afgesloten periode hoort.

    MyManus noemt de periode 'september 2026'. Die naam wint van de
    serienummers, want de naam is wat de loonstrook ook gebruikt. Zonder
    herkenbare naam valt de periode in de maand van de einddatum.
    """
    tekst = (naam or "").lower()
    for nummer in range(1, 13):
        if MAANDNAMEN[nummer] in tekst:
            jaar = None
            for token in tekst.replace("-", " ").split():
                if len(token) == 4 and token.isdigit() and token.startswith("20"):
                    jaar = int(token)
                    break
            if jaar is None and tot is not None:
                jaar = tot.year
            if jaar is not None:
                return jaar, nummer
    if van and tot and (van.year, van.month) == (tot.year, tot.month):
        return van.year, van.month
    if tot:
        return tot.year, tot.month
    return None
