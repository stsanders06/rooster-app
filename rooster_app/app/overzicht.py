"""Van opgeslagen diensten naar wat het maandscherm laat zien.

De loonheffing zit op de uitbetaling, niet op de gewerkte maand. Daarom
rekent dit scherm niet alleen de gekozen maand door, maar ook de maanden
die in dezelfde uitbetaling vallen — september hoort bij oktober als die
periode achteraf betaalt.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from datums import (
    dagen_in_maand,
    maand_uit_periodenaam,
    maandnaam,
    minuten_naar_klok,
    verschuif_maand,
    WEEKDAGEN,
)
from salaris import (
    Deel,
    Uitbetaling,
    deel_uit_uren,
    mei_waarin_vakantiegeld_valt,
    periode_op,
    periode_uit_dict,
    rond_uren,
    toeslag_specificatie,
    uitbetaling_van,
    voeg_toeslagen_samen,
)


def perioden_uit_rijen(rijen: list[dict]):
    return [periode_uit_dict(rij) for rij in rijen]


def _minuten_naar_uren(minuten) -> Decimal:
    return rond_uren(Decimal(str(minuten)) / Decimal(60))


def samenvatting_voor(jaar: int, maand: int, samenvattingen: list[dict]) -> dict | None:
    kandidaten = []
    for samenvatting in samenvattingen:
        if maand_uit_periodenaam(samenvatting.get("naam"), samenvatting.get("van"), samenvatting.get("tot")) == (jaar, maand):
            kandidaten.append(samenvatting)
    if not kandidaten:
        return None
    # Meerdere antwoorden voor dezelfde maand: de laatste periode-id is het
    # nieuwste overzicht dat we hebben zien langskomen.
    return max(kandidaten, key=lambda s: s.get("periode_id") or 0)


def verlofuren_in_maand(verloven: list[dict], jaar: int, maand: int, periode) -> Decimal:
    """Weekdagen in het verlof tellen als gewerkt: een vijfde van de weekuren.

    Een contract van 30 uur is dan 6 uur per vrije maandag tot en met vrijdag.
    Het weekend in een van-tot-reeks telt niet mee.
    """
    if periode.uren_per_week <= 0:
        return Decimal(0)
    per_dag = periode.uren_per_week / Decimal(5)
    eerste = date(jaar, maand, 1)
    laatste = date(jaar, maand, dagen_in_maand(jaar, maand))
    dagen = 0
    for verlof in verloven:
        dag = max(verlof["van"], eerste)
        eind = min(verlof["tot"], laatste)
        while dag <= eind:
            if dag.weekday() < 5 and periode.dekt(dag):
                dagen += 1
            dag += timedelta(days=1)
    return rond_uren(per_dag * Decimal(dagen))


def delen_van_maand(
    jaar: int,
    maand: int,
    diensten: list[dict],
    samenvattingen: list[dict],
    perioden: list,
    verloven: list[dict] | None = None,
    *,
    lege_meenemen: bool = False,
) -> list[Deel]:
    verloven = verloven or []
    van_deze_maand = [d for d in diensten if d["datum"].year == jaar and d["datum"].month == maand]
    samenvatting = samenvatting_voor(jaar, maand, samenvattingen)
    if samenvatting is not None:
        anker = samenvatting.get("tot") or date(jaar, maand, min(15, dagen_in_maand(jaar, maand)))
        periode = periode_op(perioden, anker) or periode_op(perioden, date(jaar, maand, 1))
        if periode is None:
            return []
        if samenvatting.get("van") and samenvatting.get("tot"):
            dagen = (samenvatting["tot"] - samenvatting["van"]).days + 1
        else:
            dagen = dagen_in_maand(jaar, maand)
        # compensationGained is de toeslag zélf, in minuten, niet de uren
        # waarover hij berekend is. Bij 50% is 300 minuten de helft van 10 uur.
        percentage = periode.avond_percentage if periode.avond_percentage > 0 else Decimal(50)
        toeslag_uren = _minuten_naar_uren(samenvatting.get("compensatie_minuten") or 0) / (percentage / Decimal(100))
        toeslag_uren = rond_uren(toeslag_uren)
        toeslagen = [(toeslag_uren, percentage)] if toeslag_uren > 0 else []
        plusmin = samenvatting.get("plusmin_minuten")
        return [
            deel_uit_uren(
                jaar,
                maand,
                _minuten_naar_uren(samenvatting.get("gerealiseerd_minuten") or 0),
                toeslagen,
                periode,
                perioden,
                dagen=dagen,
                gewerkte_dagen=len({d["datum"] for d in van_deze_maand}),
                verlof_uren=_minuten_naar_uren(samenvatting.get("verlof_minuten") or 0),
                definitief=True,
                plusmin_manus=_minuten_naar_uren(plusmin) if plusmin is not None else None,
            )
        ]

    emmers: dict[int, dict] = {}
    for nummer in range(1, dagen_in_maand(jaar, maand) + 1):
        dag = date(jaar, maand, nummer)
        periode = periode_op(perioden, dag)
        if periode is None:
            continue
        emmer = emmers.setdefault(id(periode), {"periode": periode, "dagen": 0, "diensten": []})
        emmer["dagen"] += 1
    for dienst in van_deze_maand:
        periode = periode_op(perioden, dienst["datum"])
        if periode is None:
            continue
        emmers.setdefault(id(periode), {"periode": periode, "dagen": 0, "diensten": []})["diensten"].append(dienst)

    delen = []
    for emmer in emmers.values():
        if not emmer["diensten"] and not lege_meenemen:
            continue
        groepen = [
            toeslag_specificatie(
                dienst["datum"],
                dienst["start_minuten"],
                dienst["eind_minuten"],
                dienst.get("pauzes") or [],
                emmer["periode"],
            )
            for dienst in emmer["diensten"]
        ]
        totaal = sum(int(dienst["totaal_minuten"]) for dienst in emmer["diensten"])
        delen.append(
            deel_uit_uren(
                jaar,
                maand,
                _minuten_naar_uren(totaal),
                voeg_toeslagen_samen(groepen),
                emmer["periode"],
                perioden,
                dagen=emmer["dagen"],
                gewerkte_dagen=len({dienst["datum"] for dienst in emmer["diensten"]}),
                verlof_uren=verlofuren_in_maand(verloven, jaar, maand, emmer["periode"]),
                definitief=False,
            )
        )
    return delen


def _maanden(diensten, samenvattingen, extra: set[tuple[int, int]]) -> set[tuple[int, int]]:
    maanden = set(extra)
    for dienst in diensten:
        maanden.add((dienst["datum"].year, dienst["datum"].month))
    for samenvatting in samenvattingen:
        gevonden = maand_uit_periodenaam(
            samenvatting.get("naam"), samenvatting.get("van"), samenvatting.get("tot")
        )
        if gevonden:
            maanden.add(gevonden)
    return maanden


def alle_delen(diensten, samenvattingen, perioden, middelpunt: tuple[int, int], verloven=None) -> list[Deel]:
    vorige = verschuif_maand(*middelpunt, -1)
    maanden = _maanden(diensten, samenvattingen, {middelpunt, vorige})
    uit = []
    for jaar, maand in sorted(maanden):
        uit.extend(
            delen_van_maand(
                jaar,
                maand,
                diensten,
                samenvattingen,
                perioden,
                verloven,
                lege_meenemen=(jaar, maand) == middelpunt,
            )
        )
    return uit


def vakantiegeld_open(delen: list[Deel], vandaag: date) -> Decimal:
    """Opbouw die nog niet in een mei-uitbetaling is meegenomen."""
    totaal = Decimal(0)
    for deel in delen:
        mei = mei_waarin_vakantiegeld_valt(deel.uit_jaar, deel.uit_maand)
        if mei > (vandaag.year, vandaag.month):
            totaal += deel.vakantiegeld_opbouw
    return _geld(totaal)


def _geld(bedrag: Decimal) -> Decimal:
    from salaris import geld
    return geld(bedrag)


def _badge(werk: list[Deel]) -> tuple[str, str]:
    if werk and all(deel.definitief for deel in werk):
        return "definitief", "definitief"
    if werk and any(deel.definitief for deel in werk):
        return "deels definitief", "gemengd"
    return "gepland/geschat", "geschat"


def bouw_maand(
    jaar: int,
    maand: int,
    diensten: list[dict],
    verloven: list[dict],
    periode_rijen: list[dict],
    samenvattingen: list[dict],
    saldo: dict | None,
    vandaag: date,
    nu_minuten: int,
) -> dict:
    perioden = perioden_uit_rijen(periode_rijen)
    delen = alle_delen(diensten, samenvattingen, perioden, (jaar, maand), verloven)
    werk = [deel for deel in delen if (deel.werk_jaar, deel.werk_maand) == (jaar, maand)]
    uit_deze_maand = uitbetaling_van(jaar, maand, delen, perioden)

    gerelateerd: list[Uitbetaling] = []
    gezien = set()
    for deel in werk:
        sleutel = (deel.uit_jaar, deel.uit_maand)
        if sleutel in gezien:
            continue
        gezien.add(sleutel)
        uitbetaling = uitbetaling_van(deel.uit_jaar, deel.uit_maand, delen, perioden)
        if uitbetaling is not None:
            gerelateerd.append(uitbetaling)

    betaalt_later = any((deel.uit_jaar, deel.uit_maand) != (jaar, maand) for deel in werk)
    dubbel = bool(
        uit_deze_maand
        and len({(deel.werk_jaar, deel.werk_maand) for deel in uit_deze_maand.delen}) > 1
    )
    simpel = (
        len(werk) == 1
        and not betaalt_later
        and uit_deze_maand is not None
        and len(uit_deze_maand.delen) == 1
        and uit_deze_maand.vakantiegeld_extra == 0
        and not werk[0].onvolledig
    )
    badge, badge_klasse = _badge(werk)
    vorige = verschuif_maand(jaar, maand, -1)
    volgende = verschuif_maand(jaar, maand, 1)

    def _dienst_kaart(dienst: dict) -> dict:
        return {
            "datum": dienst["datum"],
            "weekdag": WEEKDAGEN[dienst["datum"].weekday()],
            "van": minuten_naar_klok(dienst["start_minuten"]),
            "tot": minuten_naar_klok(dienst["eind_minuten"]),
            "winkel": dienst.get("winkel") or "",
            "afdeling": dienst.get("afdeling") or "",
            "pauze": int(dienst.get("pauze_minuten") or 0),
            "uren": _minuten_naar_uren(dienst.get("totaal_minuten") or 0),
            "vandaag": dienst["datum"] == vandaag,
        }

    komende = []
    for dienst in diensten:
        if dienst["datum"] < vandaag:
            continue
        if dienst["datum"] == vandaag and dienst["eind_minuten"] <= nu_minuten and dienst["eind_minuten"] >= dienst["start_minuten"]:
            continue
        komende.append(dienst)
    komende.sort(key=lambda d: (d["datum"], d["start_minuten"]))

    vrije = [v for v in verloven if v["tot"] >= vandaag]
    vrije.sort(key=lambda v: v["van"])

    def _verlof_uren(sleutel):
        if not saldo or saldo.get(sleutel) is None:
            return None
        return _minuten_naar_uren(saldo[sleutel])

    return {
        "jaar": jaar,
        "maand": maand,
        "titel": maandnaam(jaar, maand),
        "badge": badge,
        "badge_klasse": badge_klasse,
        "vorige": f"{vorige[0]:04d}-{vorige[1]:02d}",
        "volgende": f"{volgende[0]:04d}-{volgende[1]:02d}",
        "werk": werk,
        "uitbetaling": uit_deze_maand,
        "gerelateerd": gerelateerd,
        "betaalt_later": betaalt_later,
        "dubbel": dubbel,
        "simpel": simpel,
        "onvolledig": any(deel.onvolledig for deel in werk),
        "diensten": [_dienst_kaart(d) for d in van_maand(diensten, jaar, maand)],
        "eerstvolgende": [_dienst_kaart(d) for d in komende[:4]],
        "verlof_komt": vrije[:3],
        "verlof_nu": _verlof_uren("nu_minuten"),
        "verlof_einde": _verlof_uren("einde_minuten"),
        "vakantiegeld_open": vakantiegeld_open(delen, vandaag),
        "heeft_perioden": bool(perioden),
    }


def van_maand(diensten, jaar, maand):
    return sorted(
        (d for d in diensten if d["datum"].year == jaar and d["datum"].month == maand),
        key=lambda d: (d["datum"], d["start_minuten"]),
    )
