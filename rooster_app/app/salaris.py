"""Salaris uit gewerkte uren, per contractperiode.

Twee dingen lopen door elkaar en moeten uit elkaar blijven: de maand waarin
je werkt, en de maand waarin dat loon op je rekening staat. Een periode kan
achteraf betalen (de uren van september in oktober) of in dezelfde maand.
Oktober 2026 telt daardoor twee perioden in één uitbetaling — niet omdat die
maand een uitzondering is, maar omdat de ene periode achteraf betaalt en de
andere niet.

De bedragen volgen de opbouw van een all-in loonstrook voor een hulpkracht:
uurloon, toeslag over de bijzondere uren, uitbetaald flexverlof, en 8%
vakantiegeld over uurloon plus dat verlof. De loonheffing is de jaarberekening
van 2026 gedeeld door twaalf. De witte tabel rondt naar tabelloon, dus dit
wijkt een fractie af; overal waar dit bedrag staat heet het daarom een
schatting. Bij een dubbele uitbetaling of het vakantiegeld in mei rekenen we
over het hele bedrag van die uitbetaling, want de tabel kent één loon per
tijdvak.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from datums import dagen_in_maand, verschuif_maand

CENT = Decimal("0.01")
UUR = Decimal("0.01")

# Pensioenfonds Detailhandel, premieoverzicht 2026. Publieke bedragen, geen
# persoonlijke franchise: die rekenen we per maand naar rato van de uren.
MAX_PENSIOENGEVEND_JAAR = Decimal("79409")
STANDAARD_JAARFRANCHISE = Decimal("18680")
STANDAARD_PENSIOEN_PERCENTAGE = Decimal("6.1875")
STANDAARD_FULLTIME = Decimal("38")

# Schijven en kortingen 2026, jonger dan de AOW-leeftijd.
# Bron: Belastingdienst, cijferbijlage loonheffingen 1 januari 2026.
_SCHIJVEN = (
    (Decimal("38883"), Decimal("0.3575")),
    (Decimal("78426"), Decimal("0.3756")),
    (None, Decimal("0.4950")),
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
    achteraf: bool
    pensioen_percentage: Decimal
    jaarfranchise: Decimal
    fulltime_uren_per_week: Decimal
    wga_percentage: Decimal
    avond_vanaf: int
    avond_percentage: Decimal
    zondag_percentage: Decimal
    zaterdag_percentage: Decimal

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
    dat is ingevuld. De hulpkracht is all-in en wordt een maand later
    betaald, de parttimer bouwt verlof en vakantiegeld op en krijgt de
    uren in dezelfde maand.
    """
    gedeeld = {
        "uurloon": "",
        "flex_verlof_percentage": "9.23",
        "vakantiegeld_percentage": "8",
        "pensioen_percentage": "6.1875",
        "jaarfranchise": "18680",
        "fulltime_uren_per_week": "38",
        "wga_percentage": "0",
        "avond_vanaf": "18:00",
        "avond_percentage": "50",
        "zondag_percentage": "50",
        "zaterdag_percentage": "0",
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
            "achteraf": True,
            **gedeeld,
        },
        {
            "naam": "Parttime verkoopmedewerker",
            "geldig_vanaf": "2026-10-01",
            "geldig_tot": "",
            "uren_per_week": "30",
            "all_in": False,
            "vakantiegeld_maandelijks": False,
            "achteraf": False,
            **gedeeld,
        },
    ]


def periode_uit_dict(rij: dict) -> Periode:
    from datums import klok_naar_minuten

    avond = klok_naar_minuten(str(rij.get("avond_vanaf") or "18:00"))
    if avond is None:
        avond = 18 * 60
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
        achteraf=bool(rij.get("achteraf")),
        pensioen_percentage=_dec(rij.get("pensioen_percentage") or "0"),
        jaarfranchise=_dec(rij.get("jaarfranchise") or "0"),
        fulltime_uren_per_week=_dec(rij.get("fulltime_uren_per_week") or "38"),
        wga_percentage=_dec(rij.get("wga_percentage") or "0"),
        avond_vanaf=avond,
        avond_percentage=_dec(rij.get("avond_percentage") or "0"),
        zondag_percentage=_dec(rij.get("zondag_percentage") or "0"),
        zaterdag_percentage=_dec(rij.get("zaterdag_percentage") or "0"),
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


def uurloon_van(perioden: list[Periode], periode: Periode) -> Decimal | None:
    """Leeg uurloon betekent: het laatst ingevulde loon van een eerdere periode.

    Het loon van een net ingegaan contract is vaak nog niet bekend. Tot het
    is ingevuld rekenen we met het vorige, in plaats van met nul — anders
    lijkt een hele maand onbetaald.
    """
    if periode.uurloon is not None:
        return periode.uurloon
    eerdere = [
        p for p in perioden
        if p.geldig_vanaf < periode.geldig_vanaf and p.uurloon is not None
    ]
    if not eerdere:
        return None
    return max(eerdere, key=lambda p: p.geldig_vanaf).uurloon


def uitbetaalmaand(jaar: int, maand: int, periode: Periode) -> tuple[int, int]:
    if periode.achteraf:
        return verschuif_maand(jaar, maand, 1)
    return jaar, maand


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


def _dagpercentage(periode: Periode, dag: date) -> Decimal:
    # Maandag = 0. Zaterdag en zondag hebben een eigen regel; door de week
    # telt alleen het avondvenster.
    if dag.weekday() == 6:
        return periode.zondag_percentage
    if dag.weekday() == 5:
        return periode.zaterdag_percentage
    return Decimal(0)


def toeslag_minuten(
    dag: date,
    start: int,
    eind: int,
    pauzes: list[tuple[int, int]],
    periode: Periode,
) -> dict[Decimal, int]:
    """Minuten per toeslagpercentage.

    Avond en zondag stapelen niet. Op een zondagavond geldt het hoogste
    percentage van die minuut, niet de som — anders zou dezelfde minuut
    twee keer toeslag krijgen.
    """
    from datetime import timedelta

    if eind < start:
        # Dienst over middernacht: de uren na 24:00 horen bij de volgende dag,
        # anders krijgt maandagnacht nog de zondagtoeslag.
        stukken = [(dag, start, 24 * 60), (dag + timedelta(days=1), 0, eind)]
    else:
        stukken = [(dag, start, eind)]

    per_percentage: dict[Decimal, int] = {}
    for stuk_dag, stuk_start, stuk_eind in stukken:
        dagpct = _dagpercentage(periode, stuk_dag)
        for van, tot in _intervallen_zonder_pauze(stuk_start, stuk_eind, pauzes):
            grens = periode.avond_vanaf
            delen = []
            if tot <= grens or van >= grens:
                percentage = dagpct if tot <= grens else max(dagpct, periode.avond_percentage)
                delen.append((van, tot, percentage))
            else:
                delen.append((van, grens, dagpct))
                delen.append((grens, tot, max(dagpct, periode.avond_percentage)))
            for deel_van, deel_tot, percentage in delen:
                if percentage <= 0 or deel_tot <= deel_van:
                    continue
                per_percentage[percentage] = per_percentage.get(percentage, 0) + (deel_tot - deel_van)
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


@dataclass
class Deel:
    """Eén contractstuk van een werkmaand. Nog zonder loonheffing.

    De heffing hoort bij de uitbetaling, niet bij de gewerkte maand: twee
    maanden die samen worden uitbetaald delen één tabel.
    """

    naam: str
    werk_jaar: int
    werk_maand: int
    uit_jaar: int
    uit_maand: int
    uren: Decimal
    contracturen: Decimal
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
    definitief: bool
    onvolledig: bool
    uurloon: Decimal | None
    all_in: bool
    achteraf: bool
    plusmin_manus: Decimal | None

    @property
    def plusmin(self) -> Decimal:
        return rond_uren(self.uren - self.contracturen)

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


def _contracturen(periode: Periode, dagen: int) -> Decimal:
    if dagen <= 0:
        return Decimal(0)
    return rond_uren(periode.uren_per_week * Decimal(dagen) / Decimal(7))


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
    definitief: bool = False,
    plusmin_manus: Decimal | None = None,
) -> Deel:
    """Reken een werkmaand (of een stuk ervan) door alsof de uren vaststaan.

    `toeslagen` is een lijst van (uren, percentage). De uren zijn de uren
    waarover de toeslag wordt berekend, niet de toeslag zelf: 12,50 uur à
    50% geeft een half uurloon extra.
    """
    if dagen is None:
        dagen = dagen_in_maand(werk_jaar, werk_maand)
    uit_jaar, uit_maand = uitbetaalmaand(werk_jaar, werk_maand, periode)
    loon = uurloon_van(perioden, periode)
    contracturen = _contracturen(periode, dagen)
    uren = rond_uren(_dec(uren))

    leeg = dict(
        naam=periode.naam,
        werk_jaar=werk_jaar,
        werk_maand=werk_maand,
        uit_jaar=uit_jaar,
        uit_maand=uit_maand,
        uren=uren,
        contracturen=contracturen,
        gewerkte_dagen=gewerkte_dagen,
        definitief=definitief,
        uurloon=loon,
        all_in=periode.all_in,
        achteraf=periode.achteraf,
        plusmin_manus=plusmin_manus,
    )
    if loon is None:
        return Deel(
            toeslagen=[],
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
            onvolledig=True,
            **leeg,
        )

    salaris = geld(uren * loon)
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
    # toeslag. Zo is de strook opgebouwd; de toeslag zit wel in het bruto.
    vg_grondslag = salaris + flex_bedrag
    vg_bedrag = geld(vg_grondslag * periode.vakantiegeld_percentage / Decimal(100))
    if periode.vakantiegeld_maandelijks:
        vakantiegeld = vg_bedrag
        opbouw = Decimal(0)
    else:
        vakantiegeld = Decimal(0)
        opbouw = vg_bedrag

    bruto = salaris + sum(bedrag for _u, _p, bedrag in toeslag_regels) + flex_bedrag + vakantiegeld
    premie, franchise, grondslag = pensioenpremie(bruto, uren, periode)
    sv = geld(bruto - premie)
    wga = geld(sv * periode.wga_percentage / Decimal(100)) if periode.wga_percentage else Decimal(0)
    return Deel(
        toeslagen=toeslag_regels,
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
        onvolledig=False,
        **leeg,
    )


def belasting_over_jaar(inkomen: Decimal) -> Decimal:
    if inkomen <= 0:
        return Decimal(0)
    totaal = Decimal(0)
    vorige = Decimal(0)
    for grens, tarief in _SCHIJVEN:
        boven = inkomen if grens is None else min(inkomen, grens)
        stuk = boven - vorige
        if stuk > 0:
            totaal += stuk * tarief
        if grens is None or inkomen <= grens:
            break
        vorige = grens
    return totaal


def algemene_heffingskorting(inkomen: Decimal) -> Decimal:
    if inkomen <= Decimal("29736"):
        return Decimal("3115")
    korting = Decimal("3115") - Decimal("0.06398") * (inkomen - Decimal("29736"))
    return max(Decimal(0), korting)


def arbeidskorting(inkomen: Decimal) -> Decimal:
    if inkomen <= 0:
        return Decimal(0)
    if inkomen <= Decimal("11965"):
        return Decimal("0.08324") * inkomen
    if inkomen <= Decimal("25845"):
        return Decimal("996") + Decimal("0.31009") * (inkomen - Decimal("11965"))
    if inkomen <= Decimal("45592"):
        return Decimal("5300") + Decimal("0.01950") * (inkomen - Decimal("25845"))
    if inkomen <= Decimal("132920"):
        return max(Decimal(0), Decimal("5685") - Decimal("0.06510") * (inkomen - Decimal("45592")))
    return Decimal(0)


def loonheffing_maand(sv_loon: Decimal) -> Decimal:
    """Geschatte loonheffing over een maandloon, mét loonheffingskorting.

    We jaarlijken het loon van deze uitbetaling en delen de jaarbelasting
    door twaalf. Dat volgt de schijven en de opbouw van de arbeidskorting,
    dus een maand waarin twee perioden tegelijk worden betaald — of mei,
    met het vakantiegeld erbij — krijgt een hogere inhouding dan de som van
    de losse maanden zolang je daardoor in een vlakker stuk van de korting
    komt.
    """
    if sv_loon <= 0:
        return Decimal(0)
    jaar = sv_loon * 12
    jaar_heffing = belasting_over_jaar(jaar) - algemene_heffingskorting(jaar) - arbeidskorting(jaar)
    if jaar_heffing < 0:
        jaar_heffing = Decimal(0)
    return geld(jaar_heffing / 12)


def mei_waarin_vakantiegeld_valt(uit_jaar: int, uit_maand: int) -> tuple[int, int]:
    """De mei-uitbetaling waarin opgebouwd vakantiegeld van dit loon meegaat.

    Wat in juni of later wordt uitbetaald, wacht tot mei van het jaar erna.
    Wat in januari tot en met mei wordt uitbetaald, gaat mee met de mei van
    datzelfde jaar.
    """
    if uit_maand <= 5:
        return uit_jaar, 5
    return uit_jaar + 1, 5


@dataclass
class Uitbetaling:
    jaar: int
    maand: int
    delen: list[Deel]
    vakantiegeld_extra: Decimal
    bruto: Decimal
    pensioen: Decimal
    sv_loon: Decimal
    wga: Decimal
    loonheffing: Decimal
    netto: Decimal

    @property
    def onvolledig(self) -> bool:
        return any(deel.onvolledig for deel in self.delen)


def uitbetaling_van(
    jaar: int,
    maand: int,
    alle_delen: list[Deel],
    perioden: list[Periode],
) -> Uitbetaling | None:
    """Alles wat in deze kalendermaand wordt uitbetaald, als één loon.

    Het vakantiegeld dat het jaar is opgebouwd, komt er in mei bij. Dat telt
    mee in bruto, pensioen en loonheffing van die uitbetaling.
    """
    gekozen = [deel for deel in alle_delen if (deel.uit_jaar, deel.uit_maand) == (jaar, maand)]
    extra = Decimal(0)
    if maand == 5:
        for deel in alle_delen:
            if mei_waarin_vakantiegeld_valt(deel.uit_jaar, deel.uit_maand) == (jaar, maand):
                extra += deel.vakantiegeld_opbouw
        extra = geld(extra)
    if not gekozen and extra <= 0:
        return None

    bruto_zonder = geld(sum((deel.bruto for deel in gekozen), Decimal(0)))
    pensioen_zonder = geld(sum((deel.pensioen for deel in gekozen), Decimal(0)))
    wga_zonder = geld(sum((deel.wga for deel in gekozen), Decimal(0)))

    extra_premie = Decimal(0)
    extra_wga = Decimal(0)
    if extra > 0:
        # De franchise is in de gewerkte maanden al verrekend. Het vakantiegeld
        # komt daar bovenop, dus hier telt alleen het percentage nog een keer.
        periode = periode_op(perioden, date(jaar, maand, 1))
        if periode is None and gekozen:
            periode = periode_op(perioden, date(gekozen[-1].werk_jaar, gekozen[-1].werk_maand, 1))
        if periode is not None and periode.pensioen_percentage > 0:
            percentage = periode.pensioen_percentage / Decimal(100)
            extra_premie = geld(percentage / (1 + percentage) * extra)
        if periode is not None and periode.wga_percentage > 0:
            extra_wga = geld((extra - extra_premie) * periode.wga_percentage / Decimal(100))

    bruto = geld(bruto_zonder + extra)
    pensioen = geld(pensioen_zonder + extra_premie)
    sv = geld(bruto - pensioen)
    wga = geld(wga_zonder + extra_wga)
    heffing = loonheffing_maand(sv)
    netto = geld(sv - wga - heffing)
    return Uitbetaling(
        jaar=jaar,
        maand=maand,
        delen=gekozen,
        vakantiegeld_extra=extra,
        bruto=bruto,
        pensioen=pensioen,
        sv_loon=sv,
        wga=wga,
        loonheffing=heffing,
        netto=netto,
    )


def voeg_toeslagen_samen(groepen: list[list[tuple[Decimal, Decimal]]]) -> list[tuple[Decimal, Decimal]]:
    per_percentage: dict[Decimal, Decimal] = {}
    for groep in groepen:
        for uren, percentage in groep:
            per_percentage[percentage] = per_percentage.get(percentage, Decimal(0)) + uren
    return [(rond_uren(uren), percentage) for percentage, uren in sorted(per_percentage.items()) if uren > 0]
