"""Haal rooster, periode en verlof op en bewaar ze lokaal.

Een sync loopt eens in de zoveel uur, plus als je zelf op Vernieuwen tikt.
Tussen de weken zit een korte pauze, zodat een handmatige keer niet als een
burst aankomt. Wat eerder is opgeslagen en nu buiten het venster valt, blijft
staan: daar is de lokale database voor.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone

from agenda import uid_dienst, uid_verlof
from datums import (
    bereik_rond,
    datum_naar_excel,
    excel_naar_datum,
    iso_week_dagen,
    weken_in_bereik,
)
from manus import ManusFout

# Een jaar zonder afgesloten periodes. Geen storing: de lijst is dan leeg.
_GEEN_AFGESLOTEN_PERIODES = "ERR_NO_AGREED_PERIODS"


def synchroniseer(client, opslag, vandaag: date, *, pauze: float = 0.15, weken=None) -> dict:
    """Retourneert een kort verslag. Persoonsgegevens zitten er niet in."""
    gebruikersnaam, wachtwoord, bron = opslag.inloggegevens()
    if bron == "geen":
        raise ManusFout("Vul eerst je MyManus-gebruikersnaam en wachtwoord in.")

    verslag = {"weken": 0, "diensten": 0, "verloven": 0, "periodes": 0, "waarschuwingen": []}
    _zorg_voor_token(client, opslag, gebruikersnaam, wachtwoord)

    me = _get_opnieuw(client, "user/me", gebruikersnaam, wachtwoord, opslag)
    own = None
    if not isinstance(me, dict) or not (me.get("employeeId") or me.get("id")):
        try:
            own = _get_opnieuw(client, "user/own", gebruikersnaam, wachtwoord, opslag)
        except ManusFout as fout:
            if fout.status != 404:
                verslag["waarschuwingen"].append(str(fout))
    wie = identiteit_uit(me if isinstance(me, dict) else {}, own)
    if not wie["node_id"] or not wie["employee_id"]:
        raise ManusFout("MyManus gaf geen winkel of medewerker terug. Sync gestopt.")
    opslag.meta_set("node_id", wie["node_id"])
    opslag.meta_set("employee_id", wie["employee_id"])
    if wie["winkel"]:
        opslag.meta_set("winkel", wie["winkel"])
    if wie["functie"]:
        opslag.meta_set("functie", wie["functie"])

    van, tot = bereik_rond(vandaag)
    if weken is None:
        weken = weken_in_bereik(van, tot)

    for jaar, week in weken:
        pad = (
            f"node/{wie['node_id']}/employee/{wie['employee_id']}"
            f"/schedule/{jaar}/{week}/fromData"
        )
        try:
            payload = _get_opnieuw(client, pad, gebruikersnaam, wachtwoord, opslag)
        except ManusFout as fout:
            if fout.status == 404:
                continue
            verslag["waarschuwingen"].append(f"Week {week} van {jaar} niet opgehaald.")
            continue
        maandag, zondag = iso_week_dagen(jaar, week)
        diensten = diensten_uit_rooster(payload, wie["winkel"])
        opslag.vervang_week(maandag, zondag, diensten)
        verslag["weken"] += 1
        verslag["diensten"] += len(diensten)
        if pauze:
            time.sleep(pauze)

    try:
        komend = _get_opnieuw(
            client,
            (
                f"node/{wie['node_id']}/employee/{wie['employee_id']}"
                f"/schedule/{datum_naar_excel(vandaag)}/upcoming"
            ),
            gebruikersnaam,
            wachtwoord,
            opslag,
        )
        extra = diensten_uit_komend(komend, wie["winkel"])
        opslag.bewaar_diensten(extra)
        verslag["diensten"] += len(extra)
    except ManusFout as fout:
        if fout.status != 404:
            verslag["waarschuwingen"].append("Het komende rooster is niet opgehaald.")

    jaren = sorted({van.year, tot.year, vandaag.year})
    verloven = []
    gelukt_jaren = []
    for jaar in jaren:
        pad = f"node/{wie['node_id']}/employee/{wie['employee_id']}/vacation/{jaar}"
        try:
            payload = _get_opnieuw(client, pad, gebruikersnaam, wachtwoord, opslag)
        except ManusFout as fout:
            if fout.status != 404:
                verslag["waarschuwingen"].append(f"Verlof van {jaar} niet opgehaald.")
            continue
        gelukt_jaren.append(jaar)
        verloven.extend(verlof_uit_lijst(payload))
    # Alleen jaren die we echt terugkregen vervangen. Een mislukte aanroep
    # mag het verlof dat vorige keer wél binnen was niet wissen.
    if gelukt_jaren:
        opslag.vervang_verlof_van_jaren(gelukt_jaren, verloven)
        verslag["verloven"] = len(verloven)

    try:
        status = _get_opnieuw(
            client,
            f"node/{wie['node_id']}/employee/{wie['employee_id']}/vacation-status",
            gebruikersnaam,
            wachtwoord,
            opslag,
        )
        saldo = saldo_uit(status)
        if saldo:
            opslag.bewaar_verlofsaldo(saldo)
    except ManusFout as fout:
        if fout.status != 404:
            verslag["waarschuwingen"].append("Het verlofsaldo is niet opgehaald.")

    _haal_afgesloten_periodes(
        client,
        opslag,
        wie,
        _periode_jaren(van, tot, vandaag),
        gebruikersnaam,
        wachtwoord,
        verslag,
    )

    return verslag


def _periode_jaren(van: date, tot: date, vandaag: date) -> list[int]:
    """Minstens dit jaar en vorig jaar, plus elk jaar dat het roosterbereik raakt.

    Twee maanden rooster terug is te kort voor een maand die al eerder
    dichtging. Die staat anders voor altijd op gepland.
    """
    return sorted({van.year, tot.year, vandaag.year, vandaag.year - 1})


def _haal_afgesloten_periodes(client, opslag, wie, jaren, gebruikersnaam, wachtwoord, verslag) -> None:
    """Bewaar elk afgesloten overzicht één keer, en de nieuwste elke sync.

    additionalinfo/agreedperiod-summary bestaat niet: die aanroep is altijd
    404 en leverde dus nooit een oudere maand. De ESS-module report-period-ess
    vraagt de periodes per jaar op en daarna één samenvatting per periode.
    Een afgesloten periode verandert niet meer. De nieuwste kan net dicht
    zijn, dus die halen we altijd opnieuw. Lukt dat niet, dan blijft
    lastagreedperiod-summary de terugval voor in elk geval de laatste maand.
    """
    medewerker = wie["employee_id"]
    node = wie["node_id"]
    bekend = _bekende_periode_ids(opslag)
    gevonden: dict[int, dict] = {}

    for jaar in jaren:
        pad = f"node/{node}/employee/{medewerker}/salary-period/{jaar}"
        try:
            payload = _get_opnieuw(client, pad, gebruikersnaam, wachtwoord, opslag)
        except ManusFout as fout:
            if _geen_afgesloten_periodes(fout):
                continue
            verslag["waarschuwingen"].append(
                f"De afgesloten periodes van {jaar} zijn niet opgehaald."
            )
            continue
        for periode in periodes_uit_lijst(payload):
            gevonden[periode["periode_id"]] = periode

    nieuwste_id = _nieuwste_periode_id(
        client, medewerker, gebruikersnaam, wachtwoord, opslag, verslag, gevonden
    )
    nodig = {pid for pid in gevonden if pid not in bekend}
    if nieuwste_id is not None:
        nodig.add(nieuwste_id)

    opgehaald: set[int] = set()
    for pid in sorted(nodig, key=lambda waarde: _sorteersleutel(waarde, gevonden)):
        pad = f"additionalinfo/periodsummary/{medewerker}/{pid}"
        try:
            payload = _get_opnieuw(client, pad, gebruikersnaam, wachtwoord, opslag)
        except ManusFout as fout:
            if fout.status != 404:
                verslag["waarschuwingen"].append("Een periodeoverzicht is niet opgehaald.")
            continue
        opgehaald.update(_bewaar_samenvattingen(opslag, payload, verslag))

    if nieuwste_id is not None and nieuwste_id in opgehaald:
        return
    pad = f"additionalinfo/lastagreedperiod-summary/{medewerker}"
    try:
        payload = _get_opnieuw(client, pad, gebruikersnaam, wachtwoord, opslag)
    except ManusFout as fout:
        if fout.status != 404:
            verslag["waarschuwingen"].append("Een periodeoverzicht is niet opgehaald.")
        return
    _bewaar_samenvattingen(opslag, payload, verslag)


def _sorteersleutel(periode_id: int, gevonden: dict[int, dict]):
    periode = gevonden.get(periode_id) or {}
    return (periode.get("tot") or date.min, periode_id)


def _bekende_periode_ids(opslag) -> set[int]:
    ids = set()
    for samenvatting in opslag.alle_samenvattingen():
        periode_id = samenvatting.get("periode_id")
        if periode_id is None:
            continue
        ids.add(int(periode_id))
    return ids


def _nieuwste_periode_id(client, medewerker, gebruikersnaam, wachtwoord, opslag, verslag, gevonden) -> int | None:
    """Id uit lastagreedperiod, anders de periode met de laatste einddatum.

    De jaarlijst staat waarschijnlijk nieuwste-eerst. Daar leunen we niet op,
    anders verversen we de verkeerde maand als de volgorde andersom is.
    """
    pad = f"additionalinfo/lastagreedperiod/{medewerker}"
    try:
        payload = _get_opnieuw(client, pad, gebruikersnaam, wachtwoord, opslag)
    except ManusFout as fout:
        if not _geen_afgesloten_periodes(fout):
            verslag["waarschuwingen"].append("De laatst afgesloten periode is niet opgehaald.")
        payload = None
    periode = periode_uit(payload)
    if periode is not None:
        gevonden.setdefault(periode["periode_id"], periode)
        return periode["periode_id"]
    nieuwste = _nieuwste_periode(list(gevonden.values()))
    if nieuwste is None:
        return None
    return nieuwste["periode_id"]


def _geen_afgesloten_periodes(fout: ManusFout) -> bool:
    """Geen afgesloten periodes in dat jaar is een lege lijst, geen storing."""
    if fout.status == 401:
        return False
    if fout.status == 404:
        return True
    inhoud = getattr(fout, "inhoud", None)
    if not isinstance(inhoud, dict):
        return False
    detail = inhoud.get("detail")
    return isinstance(detail, dict) and detail.get("message") == _GEEN_AFGESLOTEN_PERIODES


def _bewaar_samenvattingen(opslag, payload, verslag) -> set[int]:
    ids = set()
    for samenvatting in samenvattingen_uit_antwoord(payload):
        if samenvatting.get("periode_id") is None:
            continue
        opslag.bewaar_samenvatting(samenvatting)
        verslag["periodes"] += 1
        ids.add(int(samenvatting["periode_id"]))
    return ids


def _zorg_voor_token(client, opslag, gebruikersnaam: str, wachtwoord: str) -> None:
    """Hergebruik het token tot het bijna afloopt.

    Elke sync opnieuw inloggen is onnodig: het token blijft een tot veertien
    dagen geldig, en een wachtwoord dat om de paar uur langs de server gaat
    is een grotere kans op een blokkade dan een verlopen sessie.
    """
    token = opslag.meta_get("access_token")
    geldig_tot = opslag.meta_get("token_geldig_tot")
    if token and geldig_tot:
        try:
            tot = datetime.fromisoformat(geldig_tot)
        except ValueError:
            tot = None
        if tot is not None and tot > datetime.now(timezone.utc) + timedelta(minutes=5):
            client.token = token
            return
    _bewaar_token(opslag, client.login(gebruikersnaam, wachtwoord))


def _bewaar_token(opslag, antwoord: dict) -> None:
    seconden = int(antwoord.get("expires_in") or 12 * 3600)
    # Een paar minuten speling, zodat we niet nét op het verloopmoment starten.
    tot = datetime.now(timezone.utc) + timedelta(seconds=max(300, seconden - 300))
    opslag.meta_set("access_token", antwoord["access_token"])
    opslag.meta_set("token_geldig_tot", tot.replace(microsecond=0).isoformat())


def _get_opnieuw(client, pad: str, gebruikersnaam: str, wachtwoord: str, opslag=None):
    try:
        return client.get_json(pad)
    except ManusFout as fout:
        if fout.status != 401:
            raise
        # Een verlopen token is de normale gang van zaken, niet een storing.
        # Eén keer opnieuw inloggen en hetzelfde verzoek herhalen.
        antwoord = client.login(gebruikersnaam, wachtwoord)
        if opslag is not None:
            _bewaar_token(opslag, antwoord)
        return client.get_json(pad)


def identiteit_uit(me: dict, own=None) -> dict:
    """Winkel en medewerker uit user/me, en anders uit user/own.

    Die id's horen niet vast in de code: ze verschillen per persoon en komen
    pas na het inloggen beschikbaar.
    """
    node = me.get("nodeId")
    medewerker = me.get("employeeId") or None
    winkel = me.get("nodeName") or ""
    functie = me.get("funcName") or ""
    if not medewerker:
        bron = own
        if isinstance(bron, list) and bron:
            bron = bron[0]
        if isinstance(bron, dict):
            medewerker = bron.get("employeeId") or bron.get("id")
            node = node or bron.get("nodeId")
            winkel = winkel or bron.get("nodeName") or ""
    return {
        "node_id": node,
        "employee_id": medewerker,
        "winkel": winkel,
        "functie": functie,
    }


def _pauze_lijst(entry: dict) -> list[tuple[int, int]]:
    pauzes = []
    for pauze in entry.get("breaks") or []:
        if not isinstance(pauze, dict):
            continue
        if pauze.get("from") is None or pauze.get("to") is None:
            continue
        pauzes.append((int(pauze["from"]), int(pauze["to"])))
    return pauzes


def _dienst_uit_entry(datum: date, entry: dict, winkel: str, afdeling: str, afdeling_id) -> dict | None:
    if entry.get("startTime") is None or entry.get("endTime") is None:
        return None
    start = int(entry["startTime"])
    eind = int(entry["endTime"])
    totaal = entry.get("totalTime")
    if totaal is None:
        # Zonder totalTime is de dienst de kloktijd min de pauze, één keer.
        # Bij een nachtdienst (einde vóór het begin) hoort die pauze niet
        # nog een keer van het stuk na middernacht af.
        if eind >= start:
            span = eind - start
        else:
            span = (24 * 60 - start) + eind
        pauze = int(entry.get("breakTime") or 0)
        totaal = max(0, span - pauze)
    return {
        "datum": datum,
        "start_minuten": start,
        "eind_minuten": eind,
        "pauze_minuten": int(entry.get("breakTime") or 0),
        "totaal_minuten": int(totaal),
        "winkel": entry.get("nodeName") or winkel or "",
        "afdeling": entry.get("departmentName") or afdeling or "",
        "afdeling_id": int(afdeling_id) if afdeling_id not in (None, "") else None,
        "pauzes": _pauze_lijst(entry),
        "uniek": uid_dienst(
            datum,
            start,
            eind,
            int(afdeling_id) if afdeling_id not in (None, "") else None,
        ),
    }


def diensten_uit_rooster(payload, winkel_fallback: str = "") -> list[dict]:
    if not isinstance(payload, dict):
        return []
    afdelingen = payload.get("departments") or {}
    winkels = payload.get("nodes") or {}
    uit = []
    for dag in payload.get("schedule") or []:
        if not isinstance(dag, dict):
            continue
        datum = excel_naar_datum(dag.get("date"))
        if datum is None:
            continue
        for entry in dag.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            afdeling_id = entry.get("departmentId")
            afdeling = ""
            if afdeling_id is not None and str(afdeling_id) in afdelingen:
                afdeling = afdelingen[str(afdeling_id)].get("name") or ""
            winkel = winkel_fallback
            node = entry.get("nodeId")
            if node and str(node) in winkels:
                winkel = winkels[str(node)].get("name") or winkel
            dienst = _dienst_uit_entry(datum, entry, winkel, afdeling, afdeling_id)
            if dienst:
                uit.append(dienst)
    return uit


def diensten_uit_komend(payload, winkel_fallback: str = "") -> list[dict]:
    if not isinstance(payload, dict):
        return []
    uit = []
    for sleutel, entries in payload.items():
        if not str(sleutel).isdigit() or not isinstance(entries, list):
            continue
        datum = excel_naar_datum(int(sleutel))
        if datum is None:
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            dienst = _dienst_uit_entry(
                datum,
                entry,
                entry.get("nodeName") or winkel_fallback,
                entry.get("departmentName") or "",
                entry.get("departmentId"),
            )
            if dienst:
                uit.append(dienst)
    return uit


def verlof_uit_lijst(payload) -> list[dict]:
    if isinstance(payload, dict):
        payload = payload.get("entries") or payload.get("items") or payload.get("vacations") or []
    if not isinstance(payload, list):
        return []
    uit = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        van = excel_naar_datum(item.get("fromDate"))
        tot = excel_naar_datum(item.get("toDate")) or van
        if van is None or tot is None:
            continue
        if tot < van:
            van, tot = tot, van
        code = item.get("abbr") or ""
        omschrijving = item.get("hcodeDescription") or item.get("description") or "Verlof"
        uit.append({
            "van": van,
            "tot": tot,
            "code": code,
            "omschrijving": omschrijving,
            "uniek": uid_verlof(van, tot, code),
        })
    return uit


def _uren_veld(blok: dict | None, sleutel: str):
    if not isinstance(blok, dict):
        return None
    eind = blok.get(sleutel) or {}
    if isinstance(eind, dict):
        return eind.get("hours")
    return None


def saldo_uit(payload) -> dict | None:
    if not isinstance(payload, dict):
        return None
    # Het veld heet hours, maar de waarde is minuten: 1800 is 30 uur,
    # en het rooster doet hetzelfde met totalTime.
    return {
        "nu_minuten": _uren_veld(payload.get("currentSumBalance"), "end"),
        "einde_minuten": _uren_veld(payload.get("endSumBalance"), "end"),
        "opbouw_minuten": _uren_veld(payload.get("endSumBalance"), "holidayEntitlement"),
        "opgenomen_minuten": _uren_veld(payload.get("endSumBalance"), "used"),
    }


def periode_uit(payload) -> dict | None:
    """Eén afgesloten periode uit de jaarlijst of uit lastagreedperiod."""
    if not isinstance(payload, dict) or payload.get("id") is None:
        return None
    try:
        periode_id = int(payload["id"])
    except (TypeError, ValueError):
        return None
    jaar = payload.get("year")
    try:
        jaar = int(jaar) if jaar is not None else None
    except (TypeError, ValueError):
        jaar = None
    return {
        "periode_id": periode_id,
        "naam": payload.get("name") or "",
        "van": excel_naar_datum(payload.get("fromDate")),
        "tot": excel_naar_datum(payload.get("toDate")),
        "jaar": jaar,
    }


def periodes_uit_lijst(payload) -> list[dict]:
    if not isinstance(payload, list):
        return []
    uit = []
    gezien = set()
    for item in payload:
        periode = periode_uit(item)
        if periode is None or periode["periode_id"] in gezien:
            continue
        gezien.add(periode["periode_id"])
        uit.append(periode)
    return uit


def _nieuwste_periode(periodes: list[dict]) -> dict | None:
    if not periodes:
        return None
    return max(
        periodes,
        key=lambda periode: (periode.get("tot") or date.min, periode["periode_id"]),
    )


def samenvatting_uit(payload) -> dict | None:
    if not isinstance(payload, dict) or "selectedPeriod" not in payload:
        return None
    gekozen = payload.get("selectedPeriod") or {}
    if not isinstance(gekozen, dict):
        return None
    return {
        "periode_id": gekozen.get("id"),
        "naam": gekozen.get("name") or "",
        "van": excel_naar_datum(gekozen.get("fromDate")),
        "tot": excel_naar_datum(gekozen.get("toDate")),
        "jaar": gekozen.get("year"),
        "gerealiseerd_minuten": payload.get("realizedHours") or 0,
        "compensatie_minuten": payload.get("compensationGained") or 0,
        "plusmin_minuten": payload.get("plusMinusGained"),
        "verlof_minuten": payload.get("vacationUsed") or 0,
        "toeslagen": payload.get("allowances"),
    }


def samenvattingen_uit_antwoord(payload) -> list[dict]:
    if isinstance(payload, list):
        return [s for item in payload if (s := samenvatting_uit(item))]
    een = samenvatting_uit(payload)
    if een:
        return [een]
    if isinstance(payload, dict):
        uit = []
        for waarde in payload.values():
            gevonden = samenvatting_uit(waarde)
            if gevonden:
                uit.append(gevonden)
        return uit
    return []

