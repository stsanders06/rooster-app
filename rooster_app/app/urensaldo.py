"""Urensaldo bij vast maandloon, per kalenderjaar.

Het maandloon staat vast. Het verschil tussen de uren die meetellen en de
contracturen loopt daarom op, en wordt volgens de cao uiterlijk aan het eind
van het kalenderjaar verrekend. Een nieuw jaar begint weer op nul.

Alleen dagen die onder een periode met vast maandloon vallen tellen mee.
De eerste of laatste maand van zo'n periode is naar rato van de kalenderdagen:
contracturen van een volle maand maal dagen in de periode gedeeld door de
dagen van de maand. Verlof telt als gewerkt, dezelfde regel als de plus/min
op het maandscherm.

Een afgesloten maand komt uit de periodesamenvatting van MyManus. De lopende
maand en de maanden erna komen uit het rooster en heten gepland. Een latere
maand zonder diensten en zonder verlof laten we uit het totaal: anders wordt
een nog leeg rooster een grote min, terwijl er gewoon nog niets gepland is.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from datums import dagen_in_maand, maandnaam
from salaris import (
    Periode,
    contracturen_per_maand,
    geld,
    periode_op,
    rond_uren,
    uurloon_voor_maand,
)

_KORT = (
    "",
    "jan",
    "feb",
    "mrt",
    "apr",
    "mei",
    "jun",
    "jul",
    "aug",
    "sep",
    "okt",
    "nov",
    "dec",
)


@dataclass(frozen=True)
class Maandregel:
    jaar: int
    maand: int
    naam: str
    kort: str
    contracturen: Decimal
    naar_rato: bool
    gewerkt: Decimal | None
    plusmin: Decimal | None
    cumulatief: Decimal | None
    status: str
    uurloon: Decimal | None
    manus_plusmin: Decimal | None
    manus_begin: Decimal | None
    manus_eind: Decimal | None

    @property
    def meegenomen(self) -> bool:
        return self.plusmin is not None


@dataclass(frozen=True)
class Saldoregel:
    """Het lopende saldo t/m een maand, voor onder de plus/min van die maand."""

    maandnaam: str
    deze_maand: str
    telt_mee: bool
    cumulatief: Decimal | None
    gepland_uren: Decimal
    heeft_gepland: bool
    indicatie: Decimal | None
    uurloon: Decimal | None
    manus_uren: Decimal | None
    manus_maand: str | None


@dataclass(frozen=True)
class Jaarsaldo:
    jaar: int
    maanden: tuple[Maandregel, ...]
    projectie: Decimal | None
    projectie_gepland: Decimal
    projectie_heeft_gepland: bool
    projectie_indicatie: Decimal | None
    projectie_uurloon: Decimal | None
    rooster_zin: str

    @property
    def vorig_jaar(self) -> int:
        return self.jaar - 1

    @property
    def volgend_jaar(self) -> int:
        return self.jaar + 1

    def regel_voor(self, maand: int) -> Saldoregel | None:
        """Saldo t/m deze maand. None als de maand niet onder vast maandloon valt."""
        deze = next((rij for rij in self.maanden if rij.maand == maand), None)
        if deze is None:
            return None
        mee = [rij for rij in self.maanden if rij.maand <= maand and rij.meegenomen]
        if not mee:
            return Saldoregel(
                maandnaam=deze.naam,
                deze_maand=deze.naam,
                telt_mee=False,
                cumulatief=None,
                gepland_uren=Decimal(0),
                heeft_gepland=False,
                indicatie=None,
                uurloon=None,
                manus_uren=None,
                manus_maand=None,
            )
        laatste = mee[-1]
        gepland = [rij for rij in mee if rij.status == "gepland"]
        gepland_uren = rond_uren(sum((rij.plusmin for rij in gepland), Decimal(0)))
        manus, manus_maand = _manus_t_m(self, laatste.maand)
        return Saldoregel(
            maandnaam=laatste.naam,
            deze_maand=deze.naam,
            telt_mee=deze.meegenomen,
            cumulatief=laatste.cumulatief,
            gepland_uren=gepland_uren,
            heeft_gepland=bool(gepland),
            indicatie=_indicatie(laatste.cumulatief, laatste.uurloon),
            uurloon=laatste.uurloon,
            manus_uren=manus,
            manus_maand=manus_maand,
        )


def jaarsaldo(
    jaar: int,
    perioden: list[Periode],
    diensten: list[dict],
    verloven: list[dict],
    samenvattingen: list[dict],
    vandaag: date,
    *,
    geboortedatum: date | None = None,
    loonschaal: str = "",
) -> Jaarsaldo:
    diensten = _diensten_ontdubbeld(diensten)
    ruw: list[Maandregel] = []
    for maand in range(1, 13):
        dekking = _dekking(perioden, jaar, maand)
        if dekking is None:
            continue
        contracturen, naar_rato = dekking
        samenvatting = _samenvatting_voor(jaar, maand, samenvattingen)
        if samenvatting is not None:
            gewerkt = _gewerkt_uit_samenvatting(samenvatting)
            status = "definitief"
        elif not _is_toekomst(jaar, maand, vandaag) or _heeft_inzet(
            jaar, maand, perioden, diensten, verloven
        ):
            gewerkt = _gewerkt_uit_rooster(jaar, maand, perioden, diensten, verloven)
            status = "gepland"
        else:
            gewerkt = None
            status = "geen rooster"
        plusmin = None if gewerkt is None else rond_uren(gewerkt - contracturen)
        ruw.append(
            Maandregel(
                jaar=jaar,
                maand=maand,
                naam=maandnaam(jaar, maand).split()[0],
                kort=_KORT[maand],
                contracturen=contracturen,
                naar_rato=naar_rato,
                gewerkt=gewerkt,
                plusmin=plusmin,
                cumulatief=None,
                status=status,
                uurloon=_uurloon(perioden, jaar, maand, geboortedatum, loonschaal),
                manus_plusmin=_uren_of_niets(samenvatting.get("plusmin_minuten") if samenvatting else None),
                manus_begin=_uren_of_niets(samenvatting.get("manus_begin_minuten") if samenvatting else None),
                manus_eind=_uren_of_niets(samenvatting.get("manus_eind_minuten") if samenvatting else None),
            )
        )

    lopend = Decimal(0)
    maanden: list[Maandregel] = []
    for rij in ruw:
        cumulatief = None
        if rij.plusmin is not None:
            lopend = rond_uren(lopend + rij.plusmin)
            cumulatief = lopend
        maanden.append(
            Maandregel(
                jaar=rij.jaar,
                maand=rij.maand,
                naam=rij.naam,
                kort=rij.kort,
                contracturen=rij.contracturen,
                naar_rato=rij.naar_rato,
                gewerkt=rij.gewerkt,
                plusmin=rij.plusmin,
                cumulatief=cumulatief,
                status=rij.status,
                uurloon=rij.uurloon,
                manus_plusmin=rij.manus_plusmin,
                manus_begin=rij.manus_begin,
                manus_eind=rij.manus_eind,
            )
        )

    mee = [rij for rij in maanden if rij.meegenomen]
    gepland = [rij for rij in mee if rij.status == "gepland"]
    if mee:
        projectie = mee[-1].cumulatief
        projectie_gepland = rond_uren(sum((rij.plusmin for rij in gepland), Decimal(0)))
        loon = mee[-1].uurloon
        indicatie = _indicatie(projectie, loon)
    else:
        projectie = None
        projectie_gepland = Decimal(0)
        loon = None
        indicatie = None

    return Jaarsaldo(
        jaar=jaar,
        maanden=tuple(maanden),
        projectie=projectie,
        projectie_gepland=projectie_gepland,
        projectie_heeft_gepland=bool(gepland),
        projectie_indicatie=indicatie,
        projectie_uurloon=loon,
        rooster_zin=_rooster_zin([rij.naam for rij in maanden if rij.status == "geen rooster"]),
    )


def _manus_t_m(overzicht: Jaarsaldo, maand: int) -> tuple[Decimal | None, str | None]:
    """Het eindsaldo van MyManus, naast het onze. Nooit erbij opgeteld.

    Ontbreekt het op deze maand, dan het laatste dat we wel hebben. De
    maandnaam erbij maakt dat het niet dezelfde peildatum lijkt.
    """
    gekozen = None
    for rij in overzicht.maanden:
        if rij.maand > maand:
            break
        if rij.manus_eind is not None:
            gekozen = rij
    if gekozen is None:
        return None, None
    if gekozen.maand == maand:
        return gekozen.manus_eind, None
    return gekozen.manus_eind, gekozen.naam


def _indicatie(uren: Decimal | None, uurloon: Decimal | None) -> Decimal | None:
    if uren is None or uurloon is None:
        return None
    return geld(uren * uurloon)


def _uurloon(
    perioden: list[Periode],
    jaar: int,
    maand: int,
    geboortedatum: date | None,
    loonschaal: str,
) -> Decimal | None:
    periode = None
    for nummer in range(dagen_in_maand(jaar, maand), 0, -1):
        kandidaat = periode_op(perioden, date(jaar, maand, nummer))
        if kandidaat is not None and kandidaat.vast_maandloon:
            periode = kandidaat
            break
    if periode is None:
        return None
    loon, _bron = uurloon_voor_maand(perioden, periode, jaar, maand, geboortedatum, loonschaal)
    return loon


def _dekking(perioden: list[Periode], jaar: int, maand: int) -> tuple[Decimal, bool] | None:
    """Contracturen van de dagen met vast maandloon, of None als het er geen zijn.

    Per dag geldt de periode die het laatst inging, net als bij het loon.
    Een deel van de maand is de volle contracturen maal dat deel.
    """
    dagen = dagen_in_maand(jaar, maand)
    per_periode: dict[int, list] = {}
    for nummer in range(1, dagen + 1):
        periode = periode_op(perioden, date(jaar, maand, nummer))
        if periode is None or not periode.vast_maandloon:
            continue
        emmer = per_periode.setdefault(id(periode), [periode, 0])
        emmer[1] += 1
    if not per_periode:
        return None
    totaal = Decimal(0)
    # Een volle maand van één periode is geen naar-rato. Een maand die
    # halverwege ingaat, of die over twee contracten is verdeeld, wel.
    deel = False
    for periode, aantal in per_periode.values():
        if aantal != dagen:
            deel = True
        totaal += contracturen_per_maand(periode) * Decimal(aantal) / Decimal(dagen)
    return rond_uren(totaal), deel


def _is_toekomst(jaar: int, maand: int, vandaag: date) -> bool:
    return (jaar, maand) > (vandaag.year, vandaag.month)


def _heeft_inzet(jaar: int, maand: int, perioden, diensten, verloven) -> bool:
    for dienst in diensten:
        dag = dienst["datum"]
        if dag.year != jaar or dag.month != maand:
            continue
        periode = periode_op(perioden, dag)
        if periode is not None and periode.vast_maandloon:
            return True
    dagen = dagen_in_maand(jaar, maand)
    for nummer in range(1, dagen + 1):
        dag = date(jaar, maand, nummer)
        if not _is_vrije_dag(verloven, dag):
            continue
        periode = periode_op(perioden, dag)
        if periode is not None and periode.vast_maandloon:
            return True
    return False


def _gewerkt_uit_samenvatting(samenvatting: dict) -> Decimal:
    """Gerealiseerde uren plus verlof. MyManus levert ze apart, allebei in minuten."""
    minuten = Decimal(str(samenvatting.get("gerealiseerd_minuten") or 0))
    minuten += Decimal(str(samenvatting.get("verlof_minuten") or 0))
    return rond_uren(minuten / Decimal(60))


def _gewerkt_uit_rooster(jaar, maand, perioden, diensten, verloven) -> Decimal:
    minuten = 0
    for dienst in diensten:
        dag = dienst["datum"]
        if dag.year != jaar or dag.month != maand:
            continue
        periode = periode_op(perioden, dag)
        if periode is None or not periode.vast_maandloon:
            continue
        minuten += int(dienst.get("totaal_minuten") or 0)
    uren = Decimal(minuten) / Decimal(60)
    dagen = dagen_in_maand(jaar, maand)
    for nummer in range(1, dagen + 1):
        dag = date(jaar, maand, nummer)
        if not _is_vrije_dag(verloven, dag):
            continue
        periode = periode_op(perioden, dag)
        if periode is None or not periode.vast_maandloon or periode.uren_per_week <= 0:
            continue
        # Een vrije maandag tot en met vrijdag is een vijfde van de weekuren.
        # Hetzelfde als verlofuren_in_maand, maar alleen op dagen van dít contract.
        uren += periode.uren_per_week / Decimal(5)
    return rond_uren(uren)


def _is_vrije_dag(verloven: list[dict], dag: date) -> bool:
    if dag.weekday() >= 5:
        return False
    for verlof in verloven:
        if verlof.get("gedeeltelijk"):
            continue
        if verlof["van"] <= dag <= verlof["tot"]:
            return True
    return False


def _samenvatting_voor(jaar: int, maand: int, samenvattingen: list[dict]) -> dict | None:
    from overzicht import samenvatting_voor

    return samenvatting_voor(jaar, maand, samenvattingen)


def _diensten_ontdubbeld(diensten: list[dict]) -> list[dict]:
    from overzicht import ontdubbel_diensten

    return ontdubbel_diensten(diensten)


def _uren_of_niets(minuten) -> Decimal | None:
    if minuten is None or minuten == "":
        return None
    return rond_uren(Decimal(str(minuten)) / Decimal(60))


def _rooster_zin(namen: list[str]) -> str:
    if not namen:
        return ""
    if len(namen) == 1:
        return f"{namen[0].capitalize()} heeft nog geen rooster en zit niet in dit getal."
    return f"{_opsomming(namen).capitalize()} hebben nog geen rooster en zitten niet in dit getal."


def _opsomming(namen: list[str]) -> str:
    if len(namen) == 2:
        return f"{namen[0]} en {namen[1]}"
    return ", ".join(namen[:-1]) + " en " + namen[-1]
