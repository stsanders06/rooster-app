"""Salaris uit gewerkte uren, per contractperiode.

Twee dingen lopen door elkaar en moeten uit elkaar blijven: de maand waarin
je werkt, en de maand waarin dat loon op je rekening staat. Een periode kan
achteraf betalen (de uren van september in oktober) of in dezelfde maand.
Oktober 2026 telt daardoor twee perioden in één uitbetaling — niet omdat die
maand een uitzondering is, maar omdat de ene periode achteraf betaalt en de
andere niet.

De bedragen volgen de opbouw van een all-in maand: uurloon, toeslag over de
bijzondere uren, uitbetaald flexverlof, en 8% vakantiegeld over uurloon plus
dat verlof. Een periode met vast maandloon betaalt in plaats daarvan de
contracturen (weekuren × 52/12) maal het uurloon, en uren erboven extra.

De loonheffing op gewoon loon is de jaarberekening van het tabeljaar gedeeld
door twaalf. Het vakantiegeld in mei is een bijzondere beloning: daar geldt
het percentage uit de tabel bijzondere beloningen bij het jaarloon, niet de
maandtabel over het opgeblazen bedrag. De witte tabel rondt naar tabelloon,
dus dit wijkt een fractie af; overal waar dit bedrag staat heet het een
schatting.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from datums import verschuif_maand

CENT = Decimal("0.01")
UUR = Decimal("0.01")

# Pensioenfonds Detailhandel, premieoverzicht 2026. Publieke bedragen, geen
# persoonlijke franchise: die rekenen we per maand naar rato van de uren.
MAX_PENSIOENGEVEND_JAAR = Decimal("79409")
STANDAARD_JAARFRANCHISE = Decimal("18680")
STANDAARD_PENSIOEN_PERCENTAGE = Decimal("6.1875")
STANDAARD_FULLTIME = Decimal("38")

# Tabellen per jaar, jonger dan de AOW-leeftijd, mét loonheffingskorting.
# Bron: Belastingdienst, cijferbijlage loonheffingen en witte tabel
# bijzondere beloningen, 1 januari 2026. Een jaar dat hier niet in staat
# gebruikt de laatste bekende tabel; het scherm zegt dat erbij.
_TABELLEN = {
    2026: {
        "schijven": (
            (Decimal("38883"), Decimal("0.3575")),
            (Decimal("78426"), Decimal("0.3756")),
            (None, Decimal("0.4950")),
        ),
        "ahk_max": Decimal("3115"),
        "ahk_grens": Decimal("29736"),
        "ahk_afbouw": Decimal("0.06398"),
        "ak": {
            "tot_1": Decimal("11965"),
            "pct_1": Decimal("0.08324"),
            "tot_2": Decimal("25845"),
            "basis_2": Decimal("996"),
            "pct_2": Decimal("0.31009"),
            "tot_3": Decimal("45592"),
            "basis_3": Decimal("5300"),
            "pct_3": Decimal("0.01950"),
            "tot_4": Decimal("132920"),
            "basis_4": Decimal("5685"),
            "pct_4": Decimal("0.06510"),
        },
        # Standaardtarief plus verrekeningspercentage, ondergrens van de schijf.
        "bijzonder": (
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
    },
}


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
    vast_maandloon: bool
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
            "achteraf": False,
            # Vast maandloon: de contracturen worden betaald, ook bij verlof.
            # Uren boven het contract komen er los bij.
            "vast_maandloon": True,
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
        vast_maandloon=bool(rij.get("vast_maandloon")),
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
    definitief: bool
    onvolledig: bool
    uurloon: Decimal | None
    all_in: bool
    achteraf: bool
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
    uit_jaar, uit_maand = uitbetaalmaand(werk_jaar, werk_maand, periode)
    loon = uurloon_van(perioden, periode)
    contracturen = contracturen_per_maand(periode)
    uren = rond_uren(_dec(uren))
    verlof_uren = rond_uren(_dec(verlof_uren))

    leeg = dict(
        naam=periode.naam,
        werk_jaar=werk_jaar,
        werk_maand=werk_maand,
        uit_jaar=uit_jaar,
        uit_maand=uit_maand,
        uren=uren,
        verlof_uren=verlof_uren,
        contracturen=contracturen,
        vast_maandloon=periode.vast_maandloon,
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
    premie, franchise, grondslag = pensioenpremie(bruto, pensioen_uren, periode)
    sv = geld(bruto - premie)
    wga = geld(sv * periode.wga_percentage / Decimal(100)) if periode.wga_percentage else Decimal(0)
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
        onvolledig=False,
        **leeg,
    )


def tabellen_voor(jaar: int) -> tuple[int, dict]:
    """Het tabeljaar en de tabel. Een onbekend jaar valt terug op het laatste."""
    if jaar in _TABELLEN:
        return jaar, _TABELLEN[jaar]
    laatste = max(_TABELLEN)
    return laatste, _TABELLEN[laatste]


def belasting_over_jaar(inkomen: Decimal, tabel: dict) -> Decimal:
    if inkomen <= 0:
        return Decimal(0)
    totaal = Decimal(0)
    vorige = Decimal(0)
    for grens, tarief in tabel["schijven"]:
        boven = inkomen if grens is None else min(inkomen, grens)
        stuk = boven - vorige
        if stuk > 0:
            totaal += stuk * tarief
        if grens is None or inkomen <= grens:
            break
        vorige = grens
    return totaal


def algemene_heffingskorting(inkomen: Decimal, tabel: dict) -> Decimal:
    if inkomen <= tabel["ahk_grens"]:
        return tabel["ahk_max"]
    korting = tabel["ahk_max"] - tabel["ahk_afbouw"] * (inkomen - tabel["ahk_grens"])
    return max(Decimal(0), korting)


def arbeidskorting(inkomen: Decimal, tabel: dict) -> Decimal:
    ak = tabel["ak"]
    if inkomen <= 0:
        return Decimal(0)
    if inkomen <= ak["tot_1"]:
        return ak["pct_1"] * inkomen
    if inkomen <= ak["tot_2"]:
        return ak["basis_2"] + ak["pct_2"] * (inkomen - ak["tot_1"])
    if inkomen <= ak["tot_3"]:
        return ak["basis_3"] + ak["pct_3"] * (inkomen - ak["tot_2"])
    if inkomen <= ak["tot_4"]:
        return max(Decimal(0), ak["basis_4"] - ak["pct_4"] * (inkomen - ak["tot_3"]))
    return Decimal(0)


def loonheffing_maand(sv_loon: Decimal, jaar: int = 2026) -> Decimal:
    """Geschatte loonheffing over een gewoon maandloon, mét loonheffingskorting.

    We jaarlijken dit loon en delen de jaarbelasting door twaalf. Twee
    gewone lonen in één maand — september achteraf plus oktober — gaan samen
    door deze tabel. Vakantiegeld niet: dat is een bijzondere beloning.
    """
    if sv_loon <= 0:
        return Decimal(0)
    _, tabel = tabellen_voor(jaar)
    jaarlon = sv_loon * 12
    jaar_heffing = belasting_over_jaar(jaarlon, tabel) - algemene_heffingskorting(jaarlon, tabel) - arbeidskorting(jaarlon, tabel)
    if jaar_heffing < 0:
        jaar_heffing = Decimal(0)
    return geld(jaar_heffing / 12)


def percentage_bijzonder(jaarloon: Decimal, jaar: int) -> Decimal:
    """Percentage tabel bijzondere beloningen bij dit jaarloon, mét korting."""
    _, tabel = tabellen_voor(jaar)
    percentage = Decimal(0)
    for grens, pct in tabel["bijzonder"]:
        if jaarloon >= grens:
            percentage = pct
        else:
            break
    return percentage


def loonheffing_bijzonder(bedrag: Decimal, jaarloon: Decimal, jaar: int) -> Decimal:
    """Inhouding op vakantiegeld. Afronden in het voordeel van de werknemer."""
    if bedrag <= 0:
        return Decimal(0)
    ruw = bedrag * percentage_bijzonder(jaarloon, jaar) / Decimal(100)
    return ruw.quantize(CENT, rounding=ROUND_DOWN)


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
    tabellen_jaar: int
    bijzonder_percentage: Decimal | None

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
    mee in bruto en pensioen. De loonheffing erover komt uit de tabel
    bijzondere beloningen, op basis van het jaarloon zónder die beloning
    (het gewone loon van deze uitbetaling, keer twaalf).
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
    sv_gewoon = geld(bruto_zonder - pensioen_zonder)
    sv_extra = geld(max(Decimal(0), extra - extra_premie))
    sv = geld(sv_gewoon + sv_extra)
    wga = geld(wga_zonder + extra_wga)
    tabellen_jaar, _tabel = tabellen_voor(jaar)
    heffing = loonheffing_maand(sv_gewoon, jaar)
    bijzonder_pct = None
    if sv_extra > 0:
        jaarloon = geld(sv_gewoon * 12)
        bijzonder_pct = percentage_bijzonder(jaarloon, jaar)
        heffing = geld(heffing + loonheffing_bijzonder(sv_extra, jaarloon, jaar))
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
        tabellen_jaar=tabellen_jaar,
        bijzonder_percentage=bijzonder_pct,
    )


def voeg_toeslagen_samen(groepen: list[list[tuple[Decimal, Decimal]]]) -> list[tuple[Decimal, Decimal]]:
    per_percentage: dict[Decimal, Decimal] = {}
    for groep in groepen:
        for uren, percentage in groep:
            per_percentage[percentage] = per_percentage.get(percentage, Decimal(0)) + uren
    return [(rond_uren(uren), percentage) for percentage, uren in sorted(per_percentage.items()) if uren > 0]
