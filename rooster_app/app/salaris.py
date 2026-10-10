"""Salaris uit gewerkte uren, per contractperiode.

Het maandscherm toont wat de uren van díe maand opleveren. De loonheffing
is de witte maandtabel over dat maandloon alleen. Twee maanden worden niet
samengevoegd.

De bedragen volgen de cao Doe-het-zelfbranche 2026-2027: uurloon, toeslag
op bijzondere uren, overwerk boven 9 uur per dag of gemiddeld 40 uur per
week, en bij all-in het uitbetaalde verlof plus 8% vakantiegeld daarover.
Een periode met vast maandloon betaalt de contracturen (weekuren × 52/12)
maal het uurloon, en uren erboven tegen het gewone uurloon tot de
overwerkgrens. Opgebouwd vakantiegeld blijft een reservering: het staat
op het scherm, maar niet in het netto van de maand.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
UUR = Decimal("0.01")

# Pensioenfonds Detailhandel, premieoverzicht 2026. Publieke bedragen, geen
# persoonlijke franchise: die rekenen we per maand naar rato van de uren.
MAX_PENSIOENGEVEND_JAAR = Decimal("79409")
STANDAARD_JAARFRANCHISE = Decimal("18680")
STANDAARD_PENSIOEN_PERCENTAGE = Decimal("6.1875")
STANDAARD_FULLTIME = Decimal("38")
# De werkgever verhaalt de premie voor het WGA-hiaat op de werknemer.
# Het percentage hoort bij de contractperiode, zodat een ander jaar een
# ander tarief kan hebben. De grondslag is het sv-loon: hetzelfde loon
# als de loonheffing.
STANDAARD_WGA_PERCENTAGE = Decimal("0.808")

# Tabel bijzondere beloningen 2026, jonger dan de AOW-leeftijd, mét
# loonheffingskorting. Het percentage is standaardtarief plus het
# verrekeningspercentage. Tussenliggende grenzen veranderen dat totaal
# voor deze kolom niet, die staan hier niet nog eens.
# https://download.belastingdienst.nl/belastingdienst/dl/rekenhulpen/loonheffing/2026/v01/pdf/wit_bb_nl_std_20260101.pdf
_BIJZONDER = {
    2026: (
        (Decimal("0"), Decimal("0")),
        (Decimal("11358"), Decimal("27.43")),
        (Decimal("12923"), Decimal("4.74")),
        (Decimal("23931"), Decimal("33.80")),
        (Decimal("29737"), Decimal("40.20")),
        (Decimal("38884"), Decimal("42.01")),
        (Decimal("45593"), Decimal("50.47")),
        (Decimal("78427"), Decimal("56.01")),
        (Decimal("143555"), Decimal("49.50")),
    ),
}

# Cao Doe-het-zelfbranche, lonen per 1 juli 2026. Publieke schaalbedragen.
# https://www.fnv.nl/getmedia/5ab70fbb-60c4-4009-b7a8-b45529f19094/1040-doe-het-zelfbranche-cao-01-07-2026-tm-30-06-2027-v11082026.pdf
_SCHAAL_1 = {19: Decimal("8.99"), 20: Decimal("11.99"), 21: Decimal("14.99")}
_SCHAAL_2_LEEFTIJD = {19: Decimal("9.18"), 20: Decimal("12.24"), 21: Decimal("15.30")}
_SCHAAL_2_TREDE = {1: Decimal("15.42"), 2: Decimal("15.54"), 3: Decimal("15.66")}

BRONNEN = (
    (
        "Cao Doe-het-zelfbranche, 1 juli 2026 tot en met 30 juni 2027",
        "https://www.fnv.nl/getmedia/5ab70fbb-60c4-4009-b7a8-b45529f19094/1040-doe-het-zelfbranche-cao-01-07-2026-tm-30-06-2027-v11082026.pdf",
    ),
    (
        "Pensioenfonds Detailhandel, premieoverzicht 2026",
        "https://pensioenfondsdetailhandel.nl/content/Publicaties/Rekenvoorbeelden/Premieoverzicht-2026.pdf",
    ),
    (
        "Belastingdienst, witte maandtabel 2026",
        "https://download.belastingdienst.nl/belastingdienst/dl/rekenhulpen/loonheffing/2026/v01/pdf/wit_mnd_nl_std_20260101.pdf",
    ),
    (
        "Belastingdienst, tabel bijzondere beloningen 2026",
        "https://download.belastingdienst.nl/belastingdienst/dl/rekenhulpen/loonheffing/2026/v01/pdf/wit_bb_nl_std_20260101.pdf",
    ),
)


def geld(bedrag: Decimal) -> Decimal:
    return bedrag.quantize(CENT, rounding=ROUND_HALF_UP)


def rond_uren(waarde: Decimal) -> Decimal:
    return waarde.quantize(UUR, rounding=ROUND_HALF_UP)


def _dec(waarde, standaard: str = "0") -> Decimal:
    if waarde is None or waarde == "":
        return Decimal(standaard)
    if isinstance(waarde, Decimal):
        return waarde
    return Decimal(str(waarde).replace(",", "."))


def _dec_of_niets(waarde) -> Decimal | None:
    if waarde is None or (isinstance(waarde, str) and not waarde.strip()):
        return None
    return _dec(waarde)


@dataclass(frozen=True)
class Periode:
    naam: str
    geldig_vanaf: date
    geldig_tot: date | None
    uren_per_week: Decimal
    uurloon: Decimal | None
    all_in: bool
    flex_verlof_percentage: Decimal
    vakantiegeld_percentage: Decimal
    vakantiegeld_maandelijks: bool
    vast_maandloon: bool
    pensioen_percentage: Decimal
    jaarfranchise: Decimal
    fulltime_uren_per_week: Decimal
    wga_percentage: Decimal
    avond_vanaf: int
    avond_percentage: Decimal
    zondag_percentage: Decimal
    zaterdag_percentage: Decimal
    nacht_tot: int = 6 * 60
    nacht_percentage: Decimal = Decimal("50")
    zaterdag_vanaf: int = 18 * 60
    feestdag_percentage: Decimal = Decimal("100")
    overwerk: bool = True
    overwerk_daguren: Decimal = Decimal("9")
    overwerk_weekuren: Decimal = Decimal("40")
    overwerk_weken: int = 4
    overwerk_eerste_uren: Decimal = Decimal("2")
    overwerk_eerste_percentage: Decimal = Decimal("125")
    overwerk_daarna_percentage: Decimal = Decimal("150")

    @property
    def max_pensioengevend_jaar(self) -> Decimal:
        return MAX_PENSIOENGEVEND_JAAR

    def dekt(self, dag: date) -> bool:
        if dag < self.geldig_vanaf:
            return False
        if self.geldig_tot is not None and dag > self.geldig_tot:
            return False
        return True


def standaard_periode_dicts() -> list[dict]:
    """Wat een nieuwe installatie al ingevuld heeft.

    Het uurloon blijft leeg. Dat is persoonlijk en hoort niet in de
    repository; een latere periode zonder uurloon erft het vorige zodra
    dat is ingevuld. De hulpkracht is all-in en krijgt vakantiegeld elke
    maand. De parttimer bouwt verlof en vakantiegeld op.
    """
    gedeeld = {
        "uurloon": "",
        # 24 dagen is 182,4 uur op een fulltimejaar van 1976 uur.
        "flex_verlof_percentage": "9.2308",
        "vakantiegeld_percentage": "8",
        "pensioen_percentage": "6.1875",
        "jaarfranchise": "18680",
        "fulltime_uren_per_week": "38",
        "wga_percentage": format(STANDAARD_WGA_PERCENTAGE, "f"),
        # Artikel 8.2.1: nacht, avond, zaterdagavond tot en met zondag, feestdag.
        "nacht_tot": "06:00",
        "nacht_percentage": "50",
        "avond_vanaf": "21:00",
        "avond_percentage": "50",
        "zaterdag_vanaf": "18:00",
        "zaterdag_percentage": "50",
        "zondag_percentage": "50",
        "feestdag_percentage": "100",
        "overwerk": True,
        "overwerk_daguren": "9",
        "overwerk_weekuren": "40",
        "overwerk_weken": "4",
        "overwerk_eerste_uren": "2",
        "overwerk_eerste_percentage": "125",
        "overwerk_daarna_percentage": "150",
    }
    return [
        {
            "naam": "Hulpkracht",
            "geldig_vanaf": "2020-01-01",
            "geldig_tot": "2026-09-30",
            # Flex van 3 tot 12 uur. 12 is het vergelijkingspunt voor plus/min;
            # in de instellingen zet je het aantal dat je zelf wilt aanhouden.
            "uren_per_week": "12",
            "all_in": True,
            "vakantiegeld_maandelijks": True,
            "vast_maandloon": False,
            **gedeeld,
        },
        {
            "naam": "Parttime verkoopmedewerker",
            "geldig_vanaf": "2026-10-01",
            "geldig_tot": "",
            "uren_per_week": "30",
            "all_in": False,
            "vakantiegeld_maandelijks": False,
            # Vast maandloon: de contracturen worden betaald, ook bij verlof.
            # Uren boven het contract komen er los bij.
            "vast_maandloon": True,
            **gedeeld,
        },
    ]


def _klok(rij: dict, sleutel: str, standaard: str) -> int:
    from datums import klok_naar_minuten

    gelezen = klok_naar_minuten(str(rij.get(sleutel) or standaard))
    if gelezen is None:
        gelezen = klok_naar_minuten(standaard)
    return gelezen if gelezen is not None else 0


def periode_uit_dict(rij: dict) -> Periode:
    tot = rij.get("geldig_tot") or None
    if isinstance(tot, str) and not tot.strip():
        tot = None
    if isinstance(tot, str):
        tot = date.fromisoformat(tot)
    vanaf = rij.get("geldig_vanaf")
    if isinstance(vanaf, str):
        vanaf = date.fromisoformat(vanaf)
    return Periode(
        naam=(rij.get("naam") or "Contract").strip() or "Contract",
        geldig_vanaf=vanaf,
        geldig_tot=tot,
        uren_per_week=_dec(rij.get("uren_per_week") or "0"),
        uurloon=_dec_of_niets(rij.get("uurloon")),
        all_in=bool(rij.get("all_in")),
        flex_verlof_percentage=_dec(rij.get("flex_verlof_percentage") or "0"),
        vakantiegeld_percentage=_dec(rij.get("vakantiegeld_percentage") or "0"),
        vakantiegeld_maandelijks=bool(rij.get("vakantiegeld_maandelijks")),
        vast_maandloon=bool(rij.get("vast_maandloon")),
        pensioen_percentage=_dec(rij.get("pensioen_percentage") or "0"),
        jaarfranchise=_dec(rij.get("jaarfranchise") or "0"),
        fulltime_uren_per_week=_dec(rij.get("fulltime_uren_per_week") or "38"),
        wga_percentage=_dec(rij.get("wga_percentage") or "0"),
        avond_vanaf=_klok(rij, "avond_vanaf", "21:00"),
        avond_percentage=_dec(rij.get("avond_percentage") or "0"),
        zondag_percentage=_dec(rij.get("zondag_percentage") or "0"),
        zaterdag_percentage=_dec(rij.get("zaterdag_percentage") or "0"),
        nacht_tot=_klok(rij, "nacht_tot", "06:00"),
        nacht_percentage=_dec(rij.get("nacht_percentage") if rij.get("nacht_percentage") not in (None, "") else "50"),
        zaterdag_vanaf=_klok(rij, "zaterdag_vanaf", "18:00"),
        feestdag_percentage=_dec(
            rij.get("feestdag_percentage") if rij.get("feestdag_percentage") not in (None, "") else "100"
        ),
        overwerk=bool(rij.get("overwerk", True)),
        overwerk_daguren=_dec(rij.get("overwerk_daguren") or "9"),
        overwerk_weekuren=_dec(rij.get("overwerk_weekuren") or "40"),
        overwerk_weken=int(rij.get("overwerk_weken") or 4),
        overwerk_eerste_uren=_dec(rij.get("overwerk_eerste_uren") or "2"),
        overwerk_eerste_percentage=_dec(rij.get("overwerk_eerste_percentage") or "125"),
        overwerk_daarna_percentage=_dec(rij.get("overwerk_daarna_percentage") or "150"),
    )


def periode_op(perioden: list[Periode], dag: date) -> Periode | None:
    """De periode die op deze dag geldt.

    Bij overlap wint de periode die het laatst is ingegaan. Een nieuw contract
    hoort het oude te vervangen, ook als de einddatum van het oude er een dag
    naast zit.
    """
    kandidaten = [p for p in perioden if p.dekt(dag)]
    if not kandidaten:
        return None
    return max(kandidaten, key=lambda p: p.geldig_vanaf)


def _eerder_uurloon(perioden: list[Periode], periode: Periode) -> Decimal | None:
    eerdere = [
        p for p in perioden
        if p.geldig_vanaf < periode.geldig_vanaf and p.uurloon is not None
    ]
    if not eerdere:
        return None
    return max(eerdere, key=lambda p: p.geldig_vanaf).uurloon


def uurloon_van(perioden: list[Periode], periode: Periode) -> Decimal | None:
    """Leeg uurloon betekent: het laatst ingevulde loon van een eerdere periode.

    Het loon van een net ingegaan contract is vaak nog niet bekend. Tot het
    is ingevuld rekenen we met het vorige, in plaats van met nul — anders
    lijkt een hele maand onbetaald. Een gekozen cao-schaal gaat vóór dit
    erven; die keuze zit in uurloon_voor_maand.
    """
    if periode.uurloon is not None:
        return periode.uurloon
    return _eerder_uurloon(perioden, periode)


def cao_uurloon(geboortedatum: date | None, schaal: str, jaar: int, maand: int) -> Decimal | None:
    """Uurloon uit de schaal voor deze kalendermaand.

    De stap gaat in voor de hele maand van de verjaardag. We vergelijken
    alleen de maand, zodat 29 februari ook in een jaar zonder die dag in
    februari verspringt. Na 21 jaar telt schaal 2 functiejaren, met trede 3
    als plafond. Schaal 1 heeft geen treden.
    """
    if geboortedatum is None or schaal not in ("1", "2"):
        return None
    leeftijd = jaar - geboortedatum.year
    if maand < geboortedatum.month:
        leeftijd -= 1
    if schaal == "1":
        if leeftijd < 19:
            return None
        if leeftijd >= 21:
            return _SCHAAL_1[21]
        return _SCHAAL_1.get(leeftijd)
    if leeftijd < 19:
        return None
    if leeftijd <= 21:
        return _SCHAAL_2_LEEFTIJD[leeftijd]
    return _SCHAAL_2_TREDE[min(leeftijd - 21, 3)]


def uurloon_voor_maand(
    perioden: list[Periode],
    periode: Periode,
    jaar: int,
    maand: int,
    geboortedatum: date | None = None,
    loonschaal: str = "",
) -> tuple[Decimal | None, str]:
    """Ingevuld uurloon wint. Anders de schaal, en pas daarna de vorige periode."""
    if periode.uurloon is not None:
        return periode.uurloon, "periode"
    if loonschaal in ("1", "2"):
        cao = cao_uurloon(geboortedatum, loonschaal, jaar, maand)
        if cao is not None:
            return cao, "cao"
    geerfd = _eerder_uurloon(perioden, periode)
    if geerfd is not None:
        return geerfd, "vorige"
    return None, ""


def _intervallen_zonder_pauze(start: int, eind: int, pauzes: list[tuple[int, int]]):
    stukken = [(start, eind)]
    for pauze_van, pauze_tot in pauzes:
        nieuw = []
        for van, tot in stukken:
            if pauze_tot <= van or pauze_van >= tot:
                nieuw.append((van, tot))
                continue
            if pauze_van > van:
                nieuw.append((van, min(pauze_van, tot)))
            if pauze_tot < tot:
                nieuw.append((max(pauze_tot, van), tot))
        stukken = [(van, tot) for van, tot in nieuw if tot > van]
    return stukken


_FEESTDAGEN: dict[int, set[date]] = {}


def _is_feestdag(dag: date) -> bool:
    if dag.year not in _FEESTDAGEN:
        from datums import feestdagen

        _FEESTDAGEN[dag.year] = feestdagen(dag.year)
    return dag in _FEESTDAGEN[dag.year]


def _vensters(periode: Periode, dag: date) -> list[tuple[int, int, Decimal]]:
    """Stukken van de dag met één toeslagpercentage.

    Een feestdag vervangt de 50%-vensters: die stapelen niet. Zondag is de
    hele dag het zondagpercentage, ook tussen 0:00 en 6:00. Het nachttarief
    geldt maandag tot en met zaterdag.
    """
    if _is_feestdag(dag):
        return [(0, 24 * 60, periode.feestdag_percentage)]
    weekdag = dag.weekday()
    grenzen = {0, 24 * 60}
    if weekdag <= 5:
        grenzen.add(min(24 * 60, max(0, periode.nacht_tot)))
    if weekdag <= 4:
        grenzen.add(min(24 * 60, max(0, periode.avond_vanaf)))
    if weekdag == 5:
        grenzen.add(min(24 * 60, max(0, periode.zaterdag_vanaf)))
    punten = sorted(grenzen)
    stukken = []
    for van, tot in zip(punten, punten[1:]):
        if weekdag <= 5 and van < periode.nacht_tot:
            percentage = periode.nacht_percentage
        elif weekdag <= 4 and van >= periode.avond_vanaf:
            percentage = periode.avond_percentage
        elif weekdag == 5 and van >= periode.zaterdag_vanaf:
            percentage = periode.zaterdag_percentage
        elif weekdag == 6:
            percentage = periode.zondag_percentage
        else:
            percentage = Decimal(0)
        stukken.append((van, tot, percentage))
    return stukken


def toeslag_minuten(
    dag: date,
    start: int,
    eind: int,
    pauzes: list[tuple[int, int]],
    periode: Periode,
) -> dict[Decimal, int]:
    """Minuten per toeslagpercentage.

    De vensters van artikel 8.2.1 overlappen niet. Een feestdag telt als
    100% en niet ook nog als avond of zondag.
    """
    if eind < start:
        # Dienst over middernacht: de uren na 24:00 horen bij de volgende dag,
        # anders krijgt maandagnacht nog de zondagtoeslag.
        stukken = [(dag, start, 24 * 60), (dag + timedelta(days=1), 0, eind)]
    else:
        stukken = [(dag, start, eind)]

    per_percentage: dict[Decimal, int] = {}
    for stuk_dag, stuk_start, stuk_eind in stukken:
        vensters = _vensters(periode, stuk_dag)
        for van, tot in _intervallen_zonder_pauze(stuk_start, stuk_eind, pauzes):
            for seg_van, seg_tot, percentage in vensters:
                overlap_van = max(van, seg_van)
                overlap_tot = min(tot, seg_tot)
                if percentage <= 0 or overlap_tot <= overlap_van:
                    continue
                per_percentage[percentage] = per_percentage.get(percentage, 0) + (overlap_tot - overlap_van)
    return per_percentage


def toeslag_specificatie(
    dag: date,
    start: int,
    eind: int,
    pauzes: list[tuple[int, int]],
    periode: Periode,
) -> list[tuple[Decimal, Decimal]]:
    """(uren, percentage), uren afgerond op twee decimalen zoals op de strook."""
    uit = []
    for percentage, minuten in sorted(toeslag_minuten(dag, start, eind, pauzes, periode).items()):
        uren = rond_uren(Decimal(minuten) / Decimal(60))
        if uren > 0:
            uit.append((uren, percentage))
    return uit


def _minuten_per_dag(diensten: list[dict]) -> dict[date, int]:
    """Netto minuten per kalenderdag. Een dienst over middernacht splitst."""
    per_dag: dict[date, int] = {}
    for dienst in diensten:
        start = int(dienst["start_minuten"])
        eind = int(dienst["eind_minuten"])
        pauzes = dienst.get("pauzes") or []
        dag = dienst["datum"]
        if eind < start:
            stukken = [(dag, start, 24 * 60), (dag + timedelta(days=1), 0, eind)]
        else:
            stukken = [(dag, start, eind)]
        for stuk_dag, stuk_start, stuk_eind in stukken:
            netto = sum(
                tot - van for van, tot in _intervallen_zonder_pauze(stuk_start, stuk_eind, pauzes)
            )
            if netto:
                per_dag[stuk_dag] = per_dag.get(stuk_dag, 0) + netto
    return per_dag


def _week_erna(jaar: int, week: int) -> tuple[int, int]:
    maandag = date.fromisocalendar(jaar, week, 1) + timedelta(weeks=1)
    iso = maandag.isocalendar()
    return iso.year, iso.week


def overwerk_uit_diensten(
    diensten: list[dict],
    periode: Periode,
    jaar: int,
    maand: int,
) -> tuple[Decimal, Decimal]:
    """(uren à het eerste percentage, uren à het percentage daarna).

    De percentages zijn het totaal, standaard 125% en 150%. Het uur zelf
    zit al in het salaris, dus het bedrag is alleen het stuk erboven.
    Uren tussen het contract en deze grenzen blijven op het gewone tarief.

    Overuren tellen één keer. Wat al dagtijd boven 9 uur is, telt niet
    nog eens mee voor het gemiddelde van 40 uur over 4 weken. Het
    weekoverschot gaat naar de laatste weken die zelf boven de 40 uur
    zaten. Overlappende vensters tellen het maximum, niet de som.

    Een afgesloten maand roept dit niet aan. MyManus levert daar één
    toeslaggetal, zonder uitsplitsing naar overwerk.
    """
    if not periode.overwerk:
        return Decimal(0), Decimal(0)
    eigen = [dienst for dienst in diensten if periode.dekt(dienst["datum"])]
    per_dag = _minuten_per_dag(eigen)
    if not per_dag:
        return Decimal(0), Decimal(0)

    dag_grens = int(periode.overwerk_daguren * 60)
    eerste_grens = int(periode.overwerk_eerste_uren * 60)
    week_grens = int(periode.overwerk_weekuren * 60)

    dag_eerste: dict[date, int] = {}
    dag_daarna: dict[date, int] = {}
    for dag, minuten in per_dag.items():
        extra = max(0, minuten - dag_grens)
        eerste = min(eerste_grens, extra)
        dag_eerste[dag] = eerste
        dag_daarna[dag] = extra - eerste

    week_gewoon: dict[tuple[int, int], int] = defaultdict(int)
    week_per_maand: dict[tuple[int, int], dict[tuple[int, int], int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for dag, minuten in per_dag.items():
        iso = dag.isocalendar()
        sleutel = (iso.year, iso.week)
        week_gewoon[sleutel] += minuten - dag_eerste[dag] - dag_daarna[dag]
        week_per_maand[sleutel][(dag.year, dag.month)] += minuten

    # Weken tussen de eerste en de laatste dienst zijn bekend. Een gat
    # daartussen is een week zonder werk, niet een week die ontbreekt.
    start = min(week_gewoon)
    eind = max(week_gewoon)
    reeks = [start]
    while reeks[-1] != eind and len(reeks) < 80:
        reeks.append(_week_erna(*reeks[-1]))

    aantal = max(1, int(periode.overwerk_weken))
    toekenning = {week: 0 for week in reeks}
    if aantal <= len(reeks):
        venster_grens = week_grens * aantal
        for begin in range(0, len(reeks) - aantal + 1):
            venster = reeks[begin:begin + aantal]
            totaal = sum(week_gewoon.get(week, 0) for week in venster)
            teveel = max(0, totaal - venster_grens)
            if teveel <= 0:
                continue
            rest = teveel
            voorstel: dict[tuple[int, int], int] = {}
            for week in reversed(venster):
                ruimte = max(0, week_gewoon.get(week, 0) - week_grens)
                if ruimte <= 0:
                    continue
                pak = min(ruimte, rest)
                voorstel[week] = pak
                rest -= pak
                if rest <= 0:
                    break
            for week, pak in voorstel.items():
                if pak > toekenning[week]:
                    toekenning[week] = pak

    def hoort_bij(week: tuple[int, int]) -> tuple[int, int] | None:
        verdeling = week_per_maand.get(week)
        if not verdeling:
            return None
        # De meeste minuten winnen. Bij gelijk hoort de week bij de latere maand.
        return max(verdeling.items(), key=lambda item: (item[1], item[0]))[0]

    eerste_min = 0
    daarna_min = 0
    for dag, minuten in dag_eerste.items():
        if (dag.year, dag.month) == (jaar, maand):
            eerste_min += minuten
            daarna_min += dag_daarna[dag]
    for week, minuten in toekenning.items():
        if minuten <= 0 or hoort_bij(week) != (jaar, maand):
            continue
        eerste = min(eerste_grens, minuten)
        eerste_min += eerste
        daarna_min += minuten - eerste
    return (
        rond_uren(Decimal(eerste_min) / Decimal(60)),
        rond_uren(Decimal(daarna_min) / Decimal(60)),
    )


@dataclass
class Deel:
    """Eén contractstuk van een gewerkte maand, inclusief het geschatte netto.

    De loonheffing gaat over het sv-loon van dit stuk alleen, alsof het een
    eigen maandloon is. Opgebouwd vakantiegeld staat apart en zit niet in
    bruto of netto.
    """

    naam: str
    werk_jaar: int
    werk_maand: int
    uren: Decimal
    verlof_uren: Decimal
    contracturen: Decimal
    extra_uren: Decimal
    basis_bedrag: Decimal
    vast_maandloon: bool
    gewerkte_dagen: int
    toeslagen: list[tuple[Decimal, Decimal, Decimal]]
    salaris: Decimal
    flex_uren: Decimal
    flex_bedrag: Decimal
    vakantiegeld: Decimal
    vakantiegeld_opbouw: Decimal
    bruto: Decimal
    pensioen: Decimal
    franchise: Decimal
    grondslag: Decimal
    sv_loon: Decimal
    wga: Decimal
    loonheffing: Decimal
    netto: Decimal
    tabellen_jaar: int
    overwerk_125_uren: Decimal
    overwerk_150_uren: Decimal
    overwerk_125_bedrag: Decimal
    overwerk_150_bedrag: Decimal
    overwerk_bedrag: Decimal
    heffing_opbouw: Decimal
    uurloon_bron: str
    definitief: bool
    onvolledig: bool
    uurloon: Decimal | None
    all_in: bool
    plusmin_manus: Decimal | None

    @property
    def plusmin(self) -> Decimal:
        # Verlof telt als gewerkt. Een vrije dag hoort het contract niet
        # als minuren te laten zien.
        return rond_uren(self.uren + self.verlof_uren - self.contracturen)

    @property
    def extra_bedrag(self) -> Decimal:
        if self.uurloon is None:
            return Decimal(0)
        return geld(self.extra_uren * self.uurloon)

    @property
    def toeslag_uren(self) -> Decimal:
        return rond_uren(sum((uren for uren, _pct, _bedrag in self.toeslagen), Decimal(0)))

    @property
    def toeslag_bedrag(self) -> Decimal:
        return geld(sum((bedrag for _uren, _pct, bedrag in self.toeslagen), Decimal(0)))


def pensioenpremie(bruto: Decimal, uren: Decimal, periode: Periode) -> tuple[Decimal, Decimal, Decimal]:
    """Werknemersdeel OP/NP.

    Het pensioengevend loon is het brutoloon ná de eigen premie (het
    SV-loon). Daardoor zit de premie in zijn eigen grondslag. Oplossen geeft
    premie = p / (1 + p) × (bruto − franchise), in plaats van p × bruto.

    De franchise van € 18.680 per jaar gaat naar rato van de deeltijdfactor,
    met een fulltime maand van (uren per week × 52 / 12). Boven de 100%
    stijgt de franchise niet verder, en het loon telt niet mee boven het
    maximum van het fonds.
    """
    norm = periode.fulltime_uren_per_week * Decimal(52) / Decimal(12)
    if norm <= 0 or uren <= 0:
        factor = Decimal(0)
    else:
        factor = min(Decimal(1), uren / norm)
    franchise = periode.jaarfranchise / Decimal(12) * factor
    maximum = periode.max_pensioengevend_jaar / Decimal(12) * factor
    bruto_begrensd = min(bruto, maximum) if maximum > 0 else bruto
    percentage = periode.pensioen_percentage / Decimal(100)
    ruimte = bruto_begrensd - franchise
    if ruimte <= 0 or percentage <= 0:
        return Decimal(0), geld(franchise), Decimal(0)
    premie = geld(percentage / (1 + percentage) * ruimte)
    grondslag = geld(bruto_begrensd - premie - franchise)
    if grondslag < 0:
        grondslag = Decimal(0)
    return premie, geld(franchise), grondslag


def contracturen_per_maand(periode: Periode) -> Decimal:
    """Weekuren × 52/12. Een maand is geen vast aantal dagen.

    30 uur per week is daarmee 130 uur per maand, niet 30 × dagen/7.
    """
    if periode.uren_per_week <= 0:
        return Decimal(0)
    return rond_uren(periode.uren_per_week * Decimal(52) / Decimal(12))


def deel_uit_uren(
    werk_jaar: int,
    werk_maand: int,
    uren: Decimal,
    toeslagen: list[tuple[Decimal, Decimal]],
    periode: Periode,
    perioden: list[Periode],
    *,
    dagen: int | None = None,
    gewerkte_dagen: int = 0,
    verlof_uren: Decimal = Decimal(0),
    definitief: bool = False,
    plusmin_manus: Decimal | None = None,
    overwerk_uren: tuple[Decimal, Decimal] = (Decimal(0), Decimal(0)),
    geboortedatum: date | None = None,
    loonschaal: str = "",
) -> Deel:
    """Reken een werkmaand (of een stuk ervan) door alsof de uren vaststaan.

    `toeslagen` is een lijst van (uren, percentage). De uren zijn de uren
    waarover de toeslag wordt berekend, niet de toeslag zelf: 8 uur à
    50% geeft een half uurloon extra. `verlof_uren` tellen mee in plus/min
    en, bij vast maandloon, in de uren boven het contract.
    """
    # `dagen` blijft in de aanroep staan. De contracturen zijn weekuren × 52/12
    # en hangen niet meer af van het aantal dagen in de maand.
    del dagen
    loon, bron = uurloon_voor_maand(
        perioden, periode, werk_jaar, werk_maand, geboortedatum, loonschaal
    )
    contracturen = contracturen_per_maand(periode)
    uren = rond_uren(_dec(uren))
    verlof_uren = rond_uren(_dec(verlof_uren))
    tabellen_jaar, _tabel = tabellen_voor(werk_jaar)

    leeg = dict(
        naam=periode.naam,
        werk_jaar=werk_jaar,
        werk_maand=werk_maand,
        uren=uren,
        verlof_uren=verlof_uren,
        contracturen=contracturen,
        vast_maandloon=periode.vast_maandloon,
        gewerkte_dagen=gewerkte_dagen,
        definitief=definitief,
        uurloon=loon,
        all_in=periode.all_in,
        plusmin_manus=plusmin_manus,
        tabellen_jaar=tabellen_jaar,
        uurloon_bron=bron,
    )
    if loon is None:
        return Deel(
            toeslagen=[],
            extra_uren=Decimal(0),
            basis_bedrag=Decimal(0),
            salaris=Decimal(0),
            flex_uren=Decimal(0),
            flex_bedrag=Decimal(0),
            vakantiegeld=Decimal(0),
            vakantiegeld_opbouw=Decimal(0),
            bruto=Decimal(0),
            pensioen=Decimal(0),
            franchise=Decimal(0),
            grondslag=Decimal(0),
            sv_loon=Decimal(0),
            wga=Decimal(0),
            loonheffing=Decimal(0),
            netto=Decimal(0),
            overwerk_125_uren=Decimal(0),
            overwerk_150_uren=Decimal(0),
            overwerk_125_bedrag=Decimal(0),
            overwerk_150_bedrag=Decimal(0),
            overwerk_bedrag=Decimal(0),
            heffing_opbouw=Decimal(0),
            onvolledig=True,
            **leeg,
        )

    if periode.vast_maandloon:
        # Het maandloon staat vast. Minuren blijven een saldo, ze gaan niet
        # van het loon af. Uren boven het contract, verlof meegerekend, wel.
        telling = rond_uren(uren + verlof_uren)
        extra_uren = rond_uren(max(Decimal(0), telling - contracturen))
        basis_bedrag = geld(contracturen * loon)
        salaris = geld(basis_bedrag + geld(extra_uren * loon))
        pensioen_uren = rond_uren(contracturen + extra_uren)
    else:
        extra_uren = Decimal(0)
        basis_bedrag = geld(uren * loon)
        salaris = basis_bedrag
        pensioen_uren = uren
    toeslag_regels = []
    for toeslag_uren, percentage in toeslagen:
        toeslag_uren = rond_uren(_dec(toeslag_uren))
        percentage = _dec(percentage)
        if toeslag_uren <= 0 or percentage <= 0:
            continue
        bedrag = geld(toeslag_uren * loon * percentage / Decimal(100))
        toeslag_regels.append((toeslag_uren, percentage, bedrag))

    if periode.all_in and periode.flex_verlof_percentage > 0:
        flex_uren = rond_uren(uren * periode.flex_verlof_percentage / Decimal(100))
        flex_bedrag = geld(flex_uren * loon)
    else:
        flex_uren = Decimal(0)
        flex_bedrag = Decimal(0)

    # Vakantiegeld over het uurloon plus het uitbetaalde verlof, niet over de
    # toeslag en niet over de overwerktoeslag. Die zitten wel in het bruto.
    uren_125 = rond_uren(_dec(overwerk_uren[0]))
    uren_150 = rond_uren(_dec(overwerk_uren[1]))
    # 125% en 150% zijn het totaal. Het uur is al betaald, dus alleen het
    # stuk boven de 100% komt erbij.
    premie_125 = max(Decimal(0), periode.overwerk_eerste_percentage - Decimal(100))
    premie_150 = max(Decimal(0), periode.overwerk_daarna_percentage - Decimal(100))
    overwerk_125_bedrag = geld(uren_125 * loon * premie_125 / Decimal(100))
    overwerk_150_bedrag = geld(uren_150 * loon * premie_150 / Decimal(100))
    overwerk_bedrag = geld(overwerk_125_bedrag + overwerk_150_bedrag)

    vg_grondslag = salaris + flex_bedrag
    vg_bedrag = geld(vg_grondslag * periode.vakantiegeld_percentage / Decimal(100))
    if periode.vakantiegeld_maandelijks:
        vakantiegeld = vg_bedrag
        opbouw = Decimal(0)
    else:
        vakantiegeld = Decimal(0)
        opbouw = vg_bedrag

    bruto = (
        salaris
        + sum(bedrag for _u, _p, bedrag in toeslag_regels)
        + flex_bedrag
        + vakantiegeld
        + overwerk_bedrag
    )
    premie, franchise, grondslag = pensioenpremie(bruto, pensioen_uren, periode)
    sv = geld(bruto - premie)
    # Zelfde grondslag als de loonheffing: het sv-loon, op de strook het
    # loon voor de loonheffing. De premie gaat daarna van het netto af;
    # de heffing zelf blijft over het hele sv-loon.
    wga = geld(sv * periode.wga_percentage / Decimal(100)) if periode.wga_percentage else Decimal(0)
    # De heffing hoort bij deze gewerkte maand. Opgebouwd vakantiegeld zit
    # niet in het sv-loon, dus ook niet in het netto. De tabel bijzondere
    # beloningen schat alleen wat er bij uitbetaling afgaat.
    heffing = loonheffing_maand(sv, werk_jaar)
    heffing_opbouw = heffing_bijzonder(opbouw, sv * 12, werk_jaar) if opbouw > 0 else Decimal(0)
    return Deel(
        toeslagen=toeslag_regels,
        extra_uren=extra_uren,
        basis_bedrag=basis_bedrag,
        salaris=salaris,
        flex_uren=flex_uren,
        flex_bedrag=flex_bedrag,
        vakantiegeld=vakantiegeld,
        vakantiegeld_opbouw=opbouw,
        bruto=bruto,
        pensioen=premie,
        franchise=franchise,
        grondslag=grondslag,
        sv_loon=sv,
        wga=wga,
        loonheffing=heffing,
        netto=geld(sv - wga - heffing),
        overwerk_125_uren=uren_125,
        overwerk_150_uren=uren_150,
        overwerk_125_bedrag=overwerk_125_bedrag,
        overwerk_150_bedrag=overwerk_150_bedrag,
        overwerk_bedrag=overwerk_bedrag,
        heffing_opbouw=heffing_opbouw,
        onvolledig=False,
        **leeg,
    )


def tabellen_voor(jaar: int) -> tuple[int, int]:
    """Het tabeljaar. Een onbekend jaar valt terug op het laatste."""
    if jaar in _BIJZONDER:
        return jaar, jaar
    laatste = max(_BIJZONDER)
    return laatste, laatste


def loonheffing_maand(sv_loon: Decimal, jaar: int = 2026) -> Decimal:
    """Loonheffing volgens de witte maandtabel, mét loonheffingskorting.

    De tabel loopt in stappen van € 4,50. Het loon valt in de hoogste regel
    die niet boven het loon uitkomt. Een jaar zonder eigen tabel gebruikt
    de laatste die de app heeft; het scherm zegt dat erbij.
    """
    if sv_loon <= 0:
        return Decimal(0)
    # De aanroep legt vast welk tabeljaar geldt. Ingebouwd is 2026.
    tabellen_voor(jaar)
    from witte_maand_2026 import EERSTE_CENT, HEFFING_CENTEN, STAP_CENT

    centen = int((sv_loon * 100).to_integral_value(rounding=ROUND_DOWN))
    if centen < EERSTE_CENT:
        return Decimal(0)
    index = centen // STAP_CENT - 1
    if index >= len(HEFFING_CENTEN):
        index = len(HEFFING_CENTEN) - 1
    return Decimal(HEFFING_CENTEN[index]) / Decimal(100)


def percentage_bijzonder(jaarloon: Decimal, jaar: int = 2026) -> Decimal:
    """Percentage bijzondere beloningen bij dit jaarloon, mét korting."""
    gebruikt, _zelfde = tabellen_voor(jaar)
    gekozen = _BIJZONDER[gebruikt][0][1]
    for grens, percentage in _BIJZONDER[gebruikt]:
        if jaarloon >= grens:
            gekozen = percentage
        else:
            break
    return gekozen


def heffing_bijzonder(bedrag: Decimal, jaarloon: Decimal, jaar: int = 2026) -> Decimal:
    """Loonheffing over vakantiegeld, afgerond in het voordeel van de werknemer.

    Dit bedrag gaat niet van het netto van de maand af. Het is de schatting
    voor het moment waarop de reservering wordt uitbetaald.
    """
    if bedrag <= 0:
        return Decimal(0)
    ruw = bedrag * percentage_bijzonder(jaarloon, jaar) / Decimal(100)
    if ruw <= 0:
        return Decimal(0)
    return ruw.quantize(CENT, rounding=ROUND_DOWN)


def mei_waarin_vakantiegeld_valt(jaar: int, maand: int) -> tuple[int, int]:
    """De mei waarin opgebouwd vakantiegeld van deze werkmaand vrijkomt.

    Opbouw van juni tot en met december wacht tot mei van het jaar erna.
    Opbouw van januari tot en met mei hoort bij de mei van datzelfde jaar.
    Het blijft een reservering: het gaat niet mee in het netto van die mei.
    """
    if maand <= 5:
        return jaar, 5
    return jaar + 1, 5


def voeg_toeslagen_samen(groepen: list[list[tuple[Decimal, Decimal]]]) -> list[tuple[Decimal, Decimal]]:
    per_percentage: dict[Decimal, Decimal] = {}
    for groep in groepen:
        for uren, percentage in groep:
            per_percentage[percentage] = per_percentage.get(percentage, Decimal(0)) + uren
    return [(rond_uren(uren), percentage) for percentage, uren in sorted(per_percentage.items()) if uren > 0]
