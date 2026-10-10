"""ICS-feed voor de iPhone en voor de agenda van Home Assistant.

De UID hangt af van de datum en het id uit MyManus, of van de volgorde op
die dag. Een verschoven tijd is dezelfde afspraak. Anders vult de agenda
zich met een verwijderde en een nieuwe dienst.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from datums import minuten_naar_klok

# Dezelfde slotregel als de afspraken die er al stonden. Eigen afspraken
# herkennen we aan de UID en aan X-ROOSTER-APP, niet aan deze tekst.
MARKERING = "[AUTO-ADDED]"


def _escape(tekst: str) -> str:
    return (
        tekst.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def _vouw(regel: str) -> str:
    """Regels langer dan 75 tekens vouwen, zoals RFC 5545 vraagt."""
    stukken = []
    while len(regel.encode("utf-8")) > 75:
        # Op tekens knippen is hier genoeg: de velden zijn kort en ASCII-zwaar.
        geknipt = regel[:70]
        stukken.append(geknipt)
        regel = " " + regel[70:]
    stukken.append(regel)
    return "\r\n".join(stukken)


def uid_dienst(datum: date, bron_id: str | None = None, volgorde: int = 1) -> str:
    """Zelfde dienst blijft dezelfde UID als alleen de tijd schuift.

    Het id uit MyManus hoort bij de regel, niet bij het tijdstip. Zonder id
    is de volgorde op die dag de tweede keus: de eerste dienst van de dag
    blijft de eerste, ook als hij een uur opschuift.
    """
    if bron_id:
        deel = f"id-{bron_id}"
    else:
        deel = f"nr-{int(volgorde)}"
    return f"dienst-{datum.isoformat()}-{deel}@rooster-app"


def uid_verlof(van: date, tot: date, code: str) -> str:
    return f"verlof-{van.isoformat()}-{tot.isoformat()}-{(code or 'v').lower()}@rooster-app"


def uid_voor_icloud(basis_uid: str, kenmerk: str) -> str:
    """UID voor de gedeelde agenda, herkenbaar als van deze installatie.

    De feed eindigt op @rooster-app. In een gezinsagenda is dat niet genoeg:
    alleen een UID met dit voorvoegsel én het kenmerk van deze add-on mag
    worden gewijzigd of verwijderd.
    """
    kern = (basis_uid or "afspraak").split("@", 1)[0]
    return f"rooster-app-{kern}@{kenmerk}"


def titel_dienst(eind: int, winkel: str) -> str:
    """Eindtijd en winkelnaam, zoals de afspraken die er al stonden.

    De begintijd staat niet in de titel. Wie de agenda openslaat ziet
    wanneer de dienst afloopt, niet wanneer hij begint.
    """
    naam = winkel.strip() if winkel else "Dienst"
    return f"{minuten_naar_klok(eind)} - {naam}"


def afdelingscode(waarde) -> str:
    """Code uit MyManus, met een voorloopnul als het één cijfer is.

    De notitie schrijft `03 - Voorbeeld`. Een losse 3 uit het rooster wordt
    zo dezelfde tekst. Een code die al twee tekens heeft blijft staan.
    """
    if waarde is None:
        return ""
    tekst = str(waarde).strip()
    if tekst.isdigit() and len(tekst) == 1:
        return tekst.zfill(2)
    return tekst


def _duur(minuten: int) -> str:
    """Netto of pauze als `6u15m`. Uren zonder voorloopnul, minuten met."""
    totaal = max(0, int(minuten))
    uren, rest = divmod(totaal, 60)
    return f"{uren}u{rest:02d}m"


def omschrijving_dienst(dienst: dict) -> str:
    """De notitie, in dezelfde volgorde als de afspraken die er al stonden.

    Geen locatieveld en geen URL: die horen niet in die afspraken.
    De laatste regel is de markering, ook bij onze eigen afspraken.
    """
    winkel = (dienst.get("winkel") or "").strip()
    winkel_code = (dienst.get("winkel_code") or "").strip()
    if winkel and winkel_code:
        locatie = f"Locatie: {winkel} ({winkel_code})"
    elif winkel:
        locatie = f"Locatie: {winkel}"
    elif winkel_code:
        locatie = f"Locatie: ({winkel_code})"
    else:
        locatie = "Locatie:"
    code = afdelingscode(dienst.get("afdeling_code"))
    afdeling = (dienst.get("afdeling") or "").strip()
    if code and afdeling:
        afdeling_regel = f"Afdeling: {code} - {afdeling}"
    elif code:
        afdeling_regel = f"Afdeling: {code}"
    elif afdeling:
        afdeling_regel = f"Afdeling: {afdeling}"
    else:
        afdeling_regel = "Afdeling:"
    return "\n".join([
        locatie,
        afdeling_regel,
        f"Werktijd: {_duur(dienst.get('totaal_minuten') or 0)}",
        f"Pauze: {_duur(dienst.get('pauze_minuten') or 0)}",
        "",
        MARKERING,
    ])


def _alarm(uren: int) -> list[str]:
    """Eén herinnering voor de dienst begint. 0 uur betekent geen alarm."""
    if uren <= 0:
        return []
    return [
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        "DESCRIPTION:Herinnering",
        f"TRIGGER:-PT{int(uren)}H",
        "END:VALARM",
    ]


def _tijdzone() -> str:
    # Een vaste VTIMEZONE, zodat de iPhone de tijden als Amsterdam leest en
    # niet als zwevende kloktijden die bij een reis verschuiven.
    return "\r\n".join([
        "BEGIN:VTIMEZONE",
        "TZID:Europe/Amsterdam",
        "BEGIN:DAYLIGHT",
        "DTSTART:19700329T020000",
        "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU",
        "TZOFFSETFROM:+0100",
        "TZOFFSETTO:+0200",
        "TZNAME:CEST",
        "END:DAYLIGHT",
        "BEGIN:STANDARD",
        "DTSTART:19701025T030000",
        "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU",
        "TZOFFSETFROM:+0200",
        "TZOFFSETTO:+0100",
        "TZNAME:CET",
        "END:STANDARD",
        "END:VTIMEZONE",
    ])


def _stamp(dag: date, minuten: int) -> str:
    return f"{dag.strftime('%Y%m%d')}T{minuten_naar_klok(minuten).replace(':', '')}00"


def _einde(datum: date, start: int, eind: int) -> tuple[date, int]:
    """DTEND hoort op een kloktijd. 24:00 (1440) is 00:00 de volgende dag."""
    if eind >= 24 * 60:
        dagen, rest = divmod(int(eind), 24 * 60)
        return datum + timedelta(days=dagen), rest
    if eind < start:
        return datum + timedelta(days=1), eind
    return datum, eind


def _dtstamp(nu: datetime | None) -> str:
    moment = nu or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    else:
        moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y%m%dT%H%M%SZ")


def ics_voor_icloud(
    dienst: dict | None,
    verlof: dict | None,
    kenmerk: str,
    nu: datetime | None = None,
    alarm_uren: int = 2,
) -> tuple[str, str]:
    """Eén VEVENT in een VCALENDAR, zelfde titel en tekst als de feed.

    De VTIMEZONE zit erbij omdat een losse PUT anders zwevende kloktijden
    wordt. Het kenmerk staat in de UID én in X-ROOSTER-APP: allebei moeten
    kloppen voor we een bestaande afspraak aanraken.
    """
    if dienst is not None:
        basis = dienst.get("uniek") or uid_dienst(
            dienst["datum"],
            dienst.get("bron_id") or None,
            int(dienst.get("volgorde") or 1),
        )
        uid = uid_voor_icloud(basis, kenmerk)
        start = int(dienst["start_minuten"])
        eind = int(dienst["eind_minuten"])
        eind_datum, eind_klok = _einde(dienst["datum"], start, eind)
        titel = titel_dienst(eind, dienst.get("winkel") or "")
        tekst = omschrijving_dienst(dienst)
        blok = [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{_dtstamp(nu)}",
            f"DTSTART;TZID=Europe/Amsterdam:{_stamp(dienst['datum'], start)}",
            f"DTEND;TZID=Europe/Amsterdam:{_stamp(eind_datum, eind_klok)}",
            f"SUMMARY:{_escape(titel)}",
            f"DESCRIPTION:{_escape(tekst)}",
            f"X-ROOSTER-APP:{kenmerk}",
        ]
        blok.extend(_alarm(alarm_uren))
        blok.append("END:VEVENT")
    elif verlof is not None:
        basis = verlof.get("uniek") or uid_verlof(
            verlof["van"], verlof["tot"], verlof.get("code") or ""
        )
        uid = uid_voor_icloud(basis, kenmerk)
        einde = verlof["tot"] + timedelta(days=1)
        titel = verlof.get("omschrijving") or "Verlof"
        blok = [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{_dtstamp(nu)}",
            f"DTSTART;VALUE=DATE:{verlof['van'].strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{einde.strftime('%Y%m%d')}",
            f"SUMMARY:{_escape(titel)}",
            "TRANSP:TRANSPARENT",
            f"X-ROOSTER-APP:{kenmerk}",
            "END:VEVENT",
        ]
    else:
        raise ValueError("geen dienst of verlof")
    regels = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Rooster App//NL",
        "CALSCALE:GREGORIAN",
        _tijdzone(),
    ]
    regels.extend(_vouw(regel) for regel in blok)
    regels.append("END:VCALENDAR")
    return uid, "\r\n".join(regels) + "\r\n"


def ontvouw_ics(ics: str) -> list[str]:
    tekst = ics.replace("\r\n", "\n").replace("\r", "\n")
    regels = []
    for regel in tekst.split("\n"):
        if regel[:1] in (" ", "\t") and regels:
            regels[-1] += regel[1:]
        elif regel:
            regels.append(regel)
    return regels


def _ics_unescape(tekst: str) -> str:
    uit = []
    index = 0
    while index < len(tekst):
        if tekst[index] == "\\" and index + 1 < len(tekst):
            teken = tekst[index + 1]
            if teken in ("n", "N"):
                uit.append("\n")
            else:
                uit.append(teken)
            index += 2
            continue
        uit.append(tekst[index])
        index += 1
    return "".join(uit)


def kern_van_ics(ics: str) -> dict:
    """Velden van de VEVENT. De VTIMEZONE telt niet mee.

    Die staat vóór de afspraak en heeft zelf een DTSTART en een RRULE.
    Wie de eerste de beste regel pakt, ziet 1970 en een reeks, en het
    venster of het voorbeeld klopt niet meer. Apple mag de tijdzone
    herschrijven zonder dat wij de afspraak opnieuw zetten.
    """
    velden: dict[str, str] = {}
    alarm = ""
    stapel: list[str] = []
    for regel in ontvouw_ics(ics):
        boven = regel.upper()
        if boven.startswith("BEGIN:"):
            stapel.append(boven.split(":", 1)[1].strip())
            continue
        if boven.startswith("END:"):
            if stapel:
                stapel.pop()
            continue
        if "VEVENT" not in stapel or ":" not in regel:
            continue
        naam, waarde = regel.split(":", 1)
        sleutel = naam.split(";", 1)[0].upper()
        # De herinnering zit in de afspraak. Zijn tekst is geen notitie.
        if stapel[-1] == "VALARM":
            if sleutel == "TRIGGER" and not alarm:
                alarm = waarde
            continue
        if stapel[-1] != "VEVENT":
            continue
        velden.setdefault(sleutel, waarde)
    return {
        "uid": velden.get("UID", ""),
        "samenvatting": _ics_unescape(velden.get("SUMMARY", "")),
        "omschrijving": _ics_unescape(velden.get("DESCRIPTION", "")),
        "url": _ics_unescape(velden.get("URL", "")),
        "start": velden.get("DTSTART", ""),
        "einde": velden.get("DTEND", ""),
        "kenmerk": velden.get("X-ROOSTER-APP", ""),
        "transparant": velden.get("TRANSP", ""),
        "alarm": alarm,
    }


def zelfde_afspraak(gewenst: dict, bestaand: dict) -> bool:
    """Alleen de afspraak zelf. Een andere VTIMEZONE is geen wijziging."""
    for sleutel in ("samenvatting", "omschrijving", "start", "einde", "alarm"):
        if gewenst.get(sleutel, "") != bestaand.get(sleutel, ""):
            return False
    return True


def maak_ics(
    diensten: list[dict],
    verloven: list[dict],
    nu: datetime | None = None,
    alarm_uren: int = 2,
) -> str:
    regels = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Rooster App//NL",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Rooster",
        "X-WR-TIMEZONE:Europe/Amsterdam",
        _tijdzone(),
    ]
    stempel = _dtstamp(nu)
    for dienst in diensten:
        datum = dienst["datum"]
        start = int(dienst["start_minuten"])
        eind = int(dienst["eind_minuten"])
        eind_datum, eind_klok = _einde(datum, start, eind)
        titel = titel_dienst(eind, dienst.get("winkel") or "")
        tekst = omschrijving_dienst(dienst)
        uid = dienst.get("uniek") or uid_dienst(
            datum, dienst.get("bron_id") or None, int(dienst.get("volgorde") or 1)
        )
        blok = [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{stempel}",
            f"DTSTART;TZID=Europe/Amsterdam:{_stamp(datum, start)}",
            f"DTEND;TZID=Europe/Amsterdam:{_stamp(eind_datum, eind_klok)}",
            f"SUMMARY:{_escape(titel)}",
            f"DESCRIPTION:{_escape(tekst)}",
        ]
        blok.extend(_alarm(alarm_uren))
        blok.append("END:VEVENT")
        regels.extend(_vouw(regel) for regel in blok)

    for verlof in verloven:
        van = verlof["van"]
        tot = verlof["tot"]
        # DTEND van een hele dag is de dag ná de laatste vrije dag.
        einde = tot + timedelta(days=1)
        titel = verlof.get("omschrijving") or "Verlof"
        uid = verlof.get("uniek") or uid_verlof(van, tot, verlof.get("code") or "")
        blok = [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{stempel}",
            f"DTSTART;VALUE=DATE:{van.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{einde.strftime('%Y%m%d')}",
            f"SUMMARY:{_escape(titel)}",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ]
        regels.extend(_vouw(regel) for regel in blok)

    regels.append("END:VCALENDAR")
    return "\r\n".join(regels) + "\r\n"
