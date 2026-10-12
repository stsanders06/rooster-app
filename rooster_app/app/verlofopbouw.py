"""Verlofsaldo vanaf de startdatum van het contract.

Vóór die datum was het loon all-in: de verlofuren werden uitbetaald en er
is geen saldo. Vanaf de startdatum bouwt elke kalenderdag een deel van de
jaaruren op. Een gewoon jaar deelt door 365, een schrikkeljaar door 366,
zodat een heel jaar precies op het ingestelde aantal uitkomt. De peildatum
zelf telt mee: anders mist 1 januari tot en met 31 december een dag, en
zou verlof op die dag nog niet van het saldo af gaan.

Goedgekeurd verlof is opgenomen. Een aanvraag die nog openstaat blijft
apart en gaat alleen van het verwachte saldo af. Afgewezen aanvragen
zitten niet in deze lijst; de sync laat ze al weg.

Staan er uren op het verlof, dan zijn dat minuten uit MyManus, hetzelfde
als totalTime op een dienst. Eén totaal voor een reeks verdelen we over
de dagen naar rato van de schatting hieronder, zodat dagen vóór de
startdatum en ná de peildatum niet meetellen. Ontbreken de uren, dan
geldt de ingeroosterde dienst. Zonder dienst telt maandag tot en met
vrijdag een vijfde van de contracturen, net als de plus/min, en het
weekend niet. Een deel van de dag is het overlappende stuk van de dienst,
pauze naar rato. Zonder dienst is het de klokduur, niet meer dan die
vijfde. Kloktijden op een reeks gelden elke dag opnieuw: anders werd
"09:00-17:00" één blok van de eerste ochtend tot de laatste middag.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from overzicht import ontdubbel_diensten
from salaris import Periode, periode_op, rond_uren


@dataclass(frozen=True)
class Verlofregel:
    titel: str
    van: date
    tot: date
    uren: Decimal
    meegeteld: Decimal
    aangevraagd: bool
    geschat: bool


@dataclass(frozen=True)
class Verlofstand:
    peildatum: date
    start: date
    uren_per_jaar: Decimal
    opgebouwd: Decimal
    opgenomen: Decimal
    aangevraagd: Decimal
    openstaand: Decimal
    goedgekeurd_later: Decimal
    saldo: Decimal
    verwacht: Decimal
    regels: tuple[Verlofregel, ...]


def opbouw_uren(start: date, peildatum: date, uren_per_jaar: Decimal) -> Decimal:
    """Opgebouwde uren van start tot en met peildatum, nog niet afgerond."""
    if peildatum < start or uren_per_jaar <= 0:
        return Decimal(0)
    totaal = Decimal(0)
    jaar = start.year
    while jaar <= peildatum.year:
        dagen_jaar = 366 if calendar.isleap(jaar) else 365
        eerste = start if jaar == start.year else date(jaar, 1, 1)
        laatste = peildatum if jaar == peildatum.year else date(jaar, 12, 31)
        aantal = (laatste - eerste).days + 1
        totaal += uren_per_jaar * Decimal(aantal) / Decimal(dagen_jaar)
        jaar += 1
    return totaal


def verlofstand(
    peildatum: date,
    *,
    start: date,
    uren_per_jaar: Decimal,
    verloven: list[dict],
    diensten: list[dict],
    perioden: list[Periode],
) -> Verlofstand:
    if not isinstance(uren_per_jaar, Decimal):
        uren_per_jaar = Decimal(str(uren_per_jaar))
    if uren_per_jaar < 0:
        uren_per_jaar = Decimal(0)

    per_dag: dict[date, list[dict]] = {}
    for dienst in ontdubbel_diensten(diensten):
        per_dag.setdefault(dienst["datum"], []).append(dienst)

    exact_opgenomen = Decimal(0)
    exact_aangevraagd = Decimal(0)
    exact_openstaand = Decimal(0)
    exact_later = Decimal(0)
    regels: list[Verlofregel] = []
    geordend = sorted(
        verloven,
        key=lambda verlof: (verlof.get("van") or date.min, verlof.get("tot") or date.min),
    )
    for verlof in geordend:
        verdeling = _verdeling(verlof, per_dag, perioden, start, peildatum)
        if verdeling is None:
            continue
        heel, mee, geschat, van, tot = verdeling
        aangevraagd = bool(verlof.get("aangevraagd"))
        if aangevraagd:
            exact_aangevraagd += mee
            exact_openstaand += heel
        else:
            exact_opgenomen += mee
            exact_later += heel - mee
        uren = rond_uren(heel)
        meegeteld = rond_uren(mee)
        if uren == 0 and meegeteld == 0:
            continue
        regels.append(
            Verlofregel(
                titel=(verlof.get("titel") or "Vrij").strip() or "Vrij",
                van=van,
                tot=tot,
                uren=uren,
                meegeteld=meegeteld,
                aangevraagd=aangevraagd,
                geschat=geschat,
            )
        )

    opgebouwd = rond_uren(opbouw_uren(start, peildatum, uren_per_jaar))
    opgenomen = rond_uren(exact_opgenomen)
    aangevraagd = rond_uren(exact_aangevraagd)
    saldo = rond_uren(opgebouwd - opgenomen)
    return Verlofstand(
        peildatum=peildatum,
        start=start,
        uren_per_jaar=uren_per_jaar,
        opgebouwd=opgebouwd,
        opgenomen=opgenomen,
        aangevraagd=aangevraagd,
        openstaand=rond_uren(exact_openstaand),
        goedgekeurd_later=rond_uren(exact_later),
        saldo=saldo,
        verwacht=rond_uren(saldo - aangevraagd),
        regels=tuple(regels),
    )


def _verdeling(verlof, per_dag, perioden, start, peildatum):
    van = verlof.get("van")
    tot = verlof.get("tot")
    if not isinstance(van, date) or not isinstance(tot, date):
        return None
    if tot < van:
        van, tot = tot, van
    dagen = list(_dagen(van, tot))
    if not dagen:
        return None
    gewichten = [
        _uren_op_dag(dag, verlof, per_dag.get(dag, []), periode_op(perioden, dag))
        for dag in dagen
    ]
    minuten = _minuten_uit_verlof(verlof)
    geschat = minuten is None
    if geschat:
        per_dag_uren = gewichten
    else:
        per_dag_uren = _naar_rato(minuten / Decimal(60), gewichten, len(dagen))
    heel = Decimal(0)
    mee = Decimal(0)
    for dag, uren in zip(dagen, per_dag_uren):
        if dag < start:
            continue
        heel += uren
        if dag <= peildatum:
            mee += uren
    return heel, mee, geschat, van, tot


def _minuten_uit_verlof(verlof) -> Decimal | None:
    ruw = verlof.get("uren_minuten")
    if ruw is None or ruw == "":
        return None
    try:
        minuten = Decimal(str(ruw))
    except (InvalidOperation, ValueError):
        return None
    if minuten < 0:
        return None
    return minuten


def _naar_rato(totaal: Decimal, gewichten: list[Decimal], aantal_dagen: int) -> list[Decimal]:
    """Het MyManus-totaal verdelen. Dagen zonder schatting blijven nul.

    Zijn alle schattingen nul, dan toch gelijk over de kalenderdagen: anders
    verdwijnt een totaal dat we wél hebben, bijvoorbeeld verlof in het weekend
    zonder dienst.
    """
    som = sum(gewichten, Decimal(0))
    if som > 0:
        return [totaal * gewicht / som for gewicht in gewichten]
    if aantal_dagen <= 0:
        return []
    deel = totaal / Decimal(aantal_dagen)
    return [deel for _ in gewichten]


def _dagen(van: date, tot: date):
    dag = van
    while dag <= tot:
        yield dag
        dag += timedelta(days=1)


def _uren_op_dag(dag: date, verlof: dict, diensten: list[dict], periode: Periode | None) -> Decimal:
    if verlof.get("gedeeltelijk") and verlof.get("van_minuten") is not None:
        return _deel_van_dag(dag, verlof, diensten, periode)
    return _hele_dag(dag, diensten, periode)


def _hele_dag(dag: date, diensten: list[dict], periode: Periode | None) -> Decimal:
    if diensten:
        minuten = sum((Decimal(int(dienst.get("totaal_minuten") or 0)) for dienst in diensten), Decimal(0))
        return minuten / Decimal(60)
    if dag.weekday() >= 5 or periode is None or periode.uren_per_week <= 0:
        return Decimal(0)
    return periode.uren_per_week / Decimal(5)


def _deel_van_dag(dag: date, verlof: dict, diensten: list[dict], periode: Periode | None) -> Decimal:
    van = int(verlof.get("van_minuten") or 0)
    tot = 23 * 60 + 59 if verlof.get("tot_minuten") is None else int(verlof["tot_minuten"])
    if diensten:
        minuten = sum((_overlap_met_dienst(van, tot, dienst) for dienst in diensten), Decimal(0))
        return minuten / Decimal(60)
    if dag.weekday() >= 5 or periode is None or periode.uren_per_week <= 0:
        return Decimal(0)
    plafond = periode.uren_per_week / Decimal(5) * Decimal(60)
    return min(Decimal(_klokduur(van, tot)), plafond) / Decimal(60)


def _overlap_met_dienst(van: int, tot: int, dienst: dict) -> Decimal:
    """Minuten van de dienst die in het verlof vallen, pauze naar rato.

    totaal_minuten is de dienst ná de pauze. Het overlappende deel van de
    kloktijd krijgt hetzelfde deel van die netto uren.
    """
    bruto = Decimal(0)
    overlap = Decimal(0)
    for begin, eind in _stukken(int(dienst["start_minuten"]), int(dienst["eind_minuten"])):
        bruto += Decimal(eind - begin)
        for van_stuk, tot_stuk in _stukken(van, tot):
            overlap += Decimal(max(0, min(eind, tot_stuk) - max(begin, van_stuk)))
    if bruto <= 0:
        return Decimal(0)
    totaal = Decimal(int(dienst.get("totaal_minuten") or 0))
    return totaal * overlap / bruto


def _stukken(van: int, tot: int) -> list[tuple[int, int]]:
    if tot >= van:
        return [(van, tot)]
    return [(van, 24 * 60), (0, tot)]


def _klokduur(van: int, tot: int) -> int:
    if tot >= van:
        return tot - van
    return (24 * 60 - van) + tot
